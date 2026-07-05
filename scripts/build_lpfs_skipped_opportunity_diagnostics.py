"""Build LPFS skipped-opportunity diagnostics from local journal copies.

This script is reporting-only. It consumes archived, synthetic, or safely
collected local JSONL lifecycle journals and writes an ignored report packet
under ``reports/live_ops/lpfs_skipped_opportunity_diagnostics``.

Never pass an active VPS runtime journal directly. Use a copied/snapshotted
journal packet or a filtered lifecycle packet.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_skipped_opportunity_diagnostics"

NON_ACTIONS = (
    "no_live_runner_change",
    "no_vps_access",
    "no_mt5_access",
    "no_broker_mutation",
    "no_strategy_logic_change",
    "no_risk_sizing_sl_tp_change",
    "no_config_change",
    "no_scheduler_or_watchdog_change",
    "no_runtime_state_or_journal_mutation",
    "no_recovery_enablement",
    "no_reconciliation",
    "no_canary",
)

DECISION_EVENTS = {
    "setup_rejected",
    "setup_skipped",
    "order_intent_created",
}
PLACEMENT_EVENTS = {"order_sent", "order_adopted", "market_recovery_sent"}
STRATEGY_RELEVANT_REASONS = {"volume_below_min"}
EXECUTION_QUALITY_REASONS = {
    "spread_too_wide",
    "spread_too_wide_before_send",
    "market_closed",
    "autotrading_disabled",
    "final_quote_unavailable_before_send",
    "market_recovery_spread_too_wide",
    "market_recovery_not_better",
}
ENTRY_PATH_REASONS = {
    "entry_not_pending_pullback",
    "entry_already_touched_before_placement",
    "missed_entry",
    "pending_expired",
    "bar_expired",
    "market_recovery_stop_touched",
    "market_recovery_target_touched",
}
RISK_OR_SAFETY_REASONS = {
    "risk_pct_limit",
    "max_open_risk",
    "same_symbol_stack_limit",
    "concurrent_trade_limit",
    "duplicate_signal",
    "missing_risk_bucket",
    "invalid_volume_spec",
    "invalid_symbol_value",
    "invalid_trade_geometry",
    "sl_tp_too_close",
    "pending_too_close",
}

VOLUME_DETAIL_PATTERN = re.compile(
    r"raw_volume=(?P<raw>[-+]?\d+(?:\.\d+)?)\s+"
    r"rounded_volume=(?P<rounded>[-+]?\d+(?:\.\d+)?)\s+"
    r"min=(?P<minimum>[-+]?\d+(?:\.\d+)?)"
)


class SkippedOpportunityError(RuntimeError):
    """Raised for invalid skipped-opportunity diagnostics inputs."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal",
        action="append",
        default=[],
        help="Local copied journal path, or LANE=path. Repeat for multiple lanes.",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--as-of-utc", default=None)
    args = parser.parse_args(argv)

    if not args.journal:
        parser.error("provide at least one --journal")

    try:
        as_of = _parse_as_of(args.as_of_utc)
        output_root = Path(args.output_root)
        output_dir = output_root / as_of.strftime("%Y%m%d_%H%M%S")
        _ensure_output_dir_under_root(output_root=output_root, output_dir=output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        result = build_skipped_opportunity_diagnostics(
            journal_specs=[_split_label(raw) for raw in args.journal],
            output_dir=output_dir,
            as_of_utc=as_of,
        )
    except SkippedOpportunityError as exc:
        parser.exit(2, f"error: {exc}\n")

    print(f"skipped_opportunity_report={result['output_dir']}")
    print(f"skipped_opportunity_events={result['events_csv']}")
    print(f"skipped_opportunity_summary={result['summary_csv']}")
    print(f"volume_below_min_opportunities={result['volume_below_min_csv']}")
    print(f"manifest={result['manifest']}")
    print(f"manifest_sha256={result['manifest_sha256']}")
    return 0


def build_skipped_opportunity_diagnostics(
    *,
    journal_specs: Sequence[tuple[str, str]],
    output_dir: Path,
    as_of_utc: datetime,
) -> dict[str, str]:
    source_inputs: list[dict[str, Any]] = []
    events_by_key: dict[tuple[str, str, str, str, str, str, str], dict[str, str]] = {}

    for label, raw_path in journal_specs:
        path = Path(raw_path).resolve()
        if not path.exists():
            raise SkippedOpportunityError(f"journal not found: {path}")
        lane = (label or path.stem).upper()
        source_inputs.append(_source_input(lane, path))
        for row_index, row in enumerate(_load_jsonl(path), start=1):
            parsed = _skipped_event_row(row, lane=lane, source_path=path, row_index=row_index)
            if parsed is None:
                continue
            dedupe_key = (
                parsed["lane"],
                parsed["signal_key"],
                parsed["rejection_reason"],
                parsed["opportunity_class"],
                parsed["symbol"],
                parsed["timeframe"],
                parsed["side"],
            )
            existing = events_by_key.get(dedupe_key)
            if existing is not None and _row_quality(existing) >= _row_quality(parsed):
                continue
            events_by_key[dedupe_key] = parsed

    event_rows = list(events_by_key.values())
    event_rows.sort(key=lambda row: (row["lane"], row["occurred_at_utc"], row["symbol"], row["timeframe"], row["signal_key"]))
    summary_rows = _summary_rows(event_rows)
    volume_rows = [row for row in event_rows if row["rejection_reason"] == "volume_below_min"]

    paths = {
        "events_csv": output_dir / "skipped_opportunity_events.csv",
        "summary_csv": output_dir / "skipped_opportunity_summary.csv",
        "volume_below_min_csv": output_dir / "volume_below_min_opportunities.csv",
        "summary_md": output_dir / "summary.md",
        "manifest": output_dir / "manifest.json",
    }
    _write_csv(paths["events_csv"], event_rows)
    _write_csv(paths["summary_csv"], summary_rows)
    _write_csv(paths["volume_below_min_csv"], volume_rows)
    paths["summary_md"].write_text(
        _render_summary(event_rows=event_rows, summary_rows=summary_rows, as_of_utc=as_of_utc),
        encoding="utf-8",
    )
    manifest = _manifest(
        as_of_utc=as_of_utc,
        output_dir=output_dir,
        source_inputs=source_inputs,
        outputs=[paths["events_csv"], paths["summary_csv"], paths["volume_below_min_csv"], paths["summary_md"]],
        event_rows=event_rows,
        summary_rows=summary_rows,
    )
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_hash = _sha256_file(paths["manifest"])
    (output_dir / "manifest.sha256.txt").write_text(f"{manifest_hash}  manifest.json\n", encoding="utf-8")

    return {
        "output_dir": str(output_dir),
        "events_csv": str(paths["events_csv"]),
        "summary_csv": str(paths["summary_csv"]),
        "volume_below_min_csv": str(paths["volume_below_min_csv"]),
        "manifest": str(paths["manifest"]),
        "manifest_sha256": manifest_hash,
    }


def _parse_as_of(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_output_dir_under_root(*, output_root: Path, output_dir: Path) -> None:
    root = output_root.resolve()
    resolved = output_dir.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SkippedOpportunityError(f"output path must stay under output root: {resolved}") from exc


def _split_label(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        return "", raw
    label, value = raw.split("=", 1)
    return label.strip(), value.strip()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SkippedOpportunityError(f"malformed JSONL row in {path} at line {line_number}") from exc
            if not isinstance(payload, dict):
                raise SkippedOpportunityError(f"JSONL row in {path} at line {line_number} is not an object")
            rows.append(payload)
    return rows


def _skipped_event_row(row: dict[str, Any], *, lane: str, source_path: Path, row_index: int) -> dict[str, str] | None:
    event_name = str(row.get("event") or "")
    if event_name not in DECISION_EVENTS:
        return None
    if event_name in PLACEMENT_EVENTS:
        return None

    reason = _row_reason(row)
    if not reason or reason == "ready" or reason not in STRATEGY_RELEVANT_REASONS:
        return None
    signal_key = _row_signal_key(row)
    if not signal_key:
        return None

    notification = _dict(row.get("notification_event"))
    decision = _dict(row.get("decision"))
    intent = _dict(decision.get("intent"))
    fields = _dict(notification.get("fields"))
    diagnostics = _row_diagnostics(row, notification=notification, fields=fields)
    setup = _dict(diagnostics.get("setup"))
    market = _dict(diagnostics.get("market"))
    spread_gate = _dict(diagnostics.get("spread_gate"))
    strategy = _dict(diagnostics.get("strategy"))
    execution = _dict(diagnostics.get("execution"))
    backtest_join = _dict(diagnostics.get("backtest_join"))
    detail = str(decision.get("detail") or notification.get("message") or row.get("message") or "")
    volume_detail = _volume_detail(detail)
    opportunity_class = _opportunity_class(reason)
    occurred = _row_timestamp(row, notification=notification)
    symbol = _first_text(row.get("symbol"), notification.get("symbol"), intent.get("symbol"), setup.get("symbol"), _signal_part(signal_key, 1)).upper()
    timeframe = _first_text(row.get("timeframe"), notification.get("timeframe"), intent.get("timeframe"), setup.get("timeframe"), _signal_part(signal_key, 2)).upper()
    side = _first_text(row.get("side"), notification.get("side"), intent.get("side"), setup.get("side"), _signal_part(signal_key, 4)).upper()

    return {
        "lane": lane,
        "source_path": str(source_path),
        "source_row_index": str(row_index),
        "event": event_name,
        "event_key": str(row.get("event_key") or ""),
        "occurred_at_utc": occurred,
        "signal_key": signal_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "decision_status": str(decision.get("status") or notification.get("status") or ""),
        "rejection_reason": reason,
        "opportunity_class": opportunity_class,
        "strategy_relevant": "true",
        "counts_as_closed_trade": "false",
        "include_in_closed_trade_performance": "false",
        "detail": detail,
        "raw_volume": volume_detail.get("raw_volume", ""),
        "rounded_volume": volume_detail.get("rounded_volume", ""),
        "min_volume": volume_detail.get("min_volume", ""),
        "setup_id": _first_text(setup.get("setup_id"), backtest_join.get("setup_id")),
        "candidate_id": _first_text(backtest_join.get("candidate_id"), setup.get("candidate_id")),
        "entry_price": _fmt(setup.get("entry_price")),
        "stop_price": _fmt(setup.get("stop_price")),
        "take_profit": _fmt(setup.get("take_profit")),
        "risk_distance": _fmt(setup.get("risk_distance")),
        "target_r": _fmt(setup.get("target_r")),
        "risk_atr": _fmt(setup.get("risk_atr")),
        "atr": _fmt(setup.get("atr")),
        "fs_total_bars": _fmt(setup.get("fs_total_bars")),
        "bars_from_lp_break": _fmt(setup.get("bars_from_lp_break")),
        "setup_age_bars_bucket": _bucket_int(setup.get("bars_from_lp_break")),
        "spread_points": _fmt(market.get("spread_points")),
        "spread_risk_fraction": _fmt(spread_gate.get("spread_risk_fraction")),
        "risk_bucket_scale": _fmt(strategy.get("risk_bucket_scale")),
        "target_risk_pct": _fmt(intent.get("target_risk_pct")),
        "actual_risk_pct": _fmt(intent.get("actual_risk_pct")),
        "execution_stage": str(execution.get("stage") or ""),
        "trade_key": _first_text(backtest_join.get("trade_key"), signal_key),
        "analysis_note": _analysis_note(reason),
    }


def _row_reason(row: dict[str, Any]) -> str:
    decision = _dict(row.get("decision"))
    rejection = str(decision.get("rejection_reason") or "").strip()
    if rejection:
        return rejection
    notification = _dict(row.get("notification_event"))
    status = str(notification.get("status") or "").strip()
    if status:
        return status
    skipped = _dict(row.get("skipped"))
    return str(skipped.get("skip_reason") or skipped.get("reason") or skipped.get("status") or "").strip()


def _row_signal_key(row: dict[str, Any]) -> str:
    direct = str(row.get("signal_key") or "")
    if direct:
        return direct
    notification = _dict(row.get("notification_event"))
    nested = str(notification.get("signal_key") or "")
    if nested:
        return nested
    decision = _dict(row.get("decision"))
    intent = _dict(decision.get("intent"))
    nested = str(intent.get("signal_key") or "")
    if nested:
        return nested
    skipped = _dict(row.get("skipped"))
    return str(skipped.get("signal_key") or "")


def _row_diagnostics(row: dict[str, Any], *, notification: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    diagnostics = row.get("diagnostics")
    if isinstance(diagnostics, dict):
        return diagnostics
    nested = fields.get("diagnostics")
    if isinstance(nested, dict):
        return nested
    notification_fields = _dict(notification.get("fields"))
    nested = notification_fields.get("diagnostics")
    return nested if isinstance(nested, dict) else {}


def _row_timestamp(row: dict[str, Any], *, notification: dict[str, Any]) -> str:
    value = row.get("occurred_at_utc") or notification.get("occurred_at_utc") or ""
    if not value:
        return ""
    return str(value)


def _opportunity_class(reason: str) -> str:
    if reason in STRATEGY_RELEVANT_REASONS:
        return "strategy_relevant_untradeable_volume"
    if reason in EXECUTION_QUALITY_REASONS:
        return "execution_quality_or_retryable_block"
    if reason in ENTRY_PATH_REASONS:
        return "entry_path_or_expiry_block"
    if reason in RISK_OR_SAFETY_REASONS:
        return "risk_policy_or_safety_block"
    return "other_non_executed_setup"


def _analysis_note(reason: str) -> str:
    if reason == "volume_below_min":
        return "Broker/account minimum-volume skip; analyze separately from executed trades and execution rejects."
    if reason in EXECUTION_QUALITY_REASONS:
        return "Execution-quality or retryable broker/session block; do not treat as a missed strategy trade."
    if reason in ENTRY_PATH_REASONS:
        return "Entry path or expiry outcome; analyze separately from closed trades."
    if reason in RISK_OR_SAFETY_REASONS:
        return "Risk/safety policy block; do not infer signal edge without policy context."
    return "Non-executed setup evidence; inspect before strategy conclusions."


def _volume_detail(detail: str) -> dict[str, str]:
    match = VOLUME_DETAIL_PATTERN.search(detail)
    if not match:
        return {}
    return {
        "raw_volume": match.group("raw"),
        "rounded_volume": match.group("rounded"),
        "min_volume": match.group("minimum"),
    }


def _summary_rows(event_rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in event_rows:
        key = (
            row["lane"],
            row["opportunity_class"],
            row["rejection_reason"],
            row["symbol"],
            row["timeframe"],
            row["side"],
        )
        item = grouped.setdefault(
            key,
            {
                "lane": row["lane"],
                "opportunity_class": row["opportunity_class"],
                "rejection_reason": row["rejection_reason"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "side": row["side"],
                "skipped_setups": 0,
                "strategy_relevant_skips": 0,
                "first_seen_utc": row["occurred_at_utc"],
                "last_seen_utc": row["occurred_at_utc"],
                "signal_keys": set(),
            },
        )
        item["skipped_setups"] += 1
        if row["strategy_relevant"] == "true":
            item["strategy_relevant_skips"] += 1
        if row["occurred_at_utc"] and (not item["first_seen_utc"] or row["occurred_at_utc"] < item["first_seen_utc"]):
            item["first_seen_utc"] = row["occurred_at_utc"]
        if row["occurred_at_utc"] and row["occurred_at_utc"] > item["last_seen_utc"]:
            item["last_seen_utc"] = row["occurred_at_utc"]
        item["signal_keys"].add(row["signal_key"])

    rows: list[dict[str, str]] = []
    for item in grouped.values():
        rows.append(
            {
                "lane": item["lane"],
                "opportunity_class": item["opportunity_class"],
                "rejection_reason": item["rejection_reason"],
                "symbol": item["symbol"],
                "timeframe": item["timeframe"],
                "side": item["side"],
                "skipped_setups": str(item["skipped_setups"]),
                "unique_signal_keys": str(len(item["signal_keys"])),
                "strategy_relevant_skips": str(item["strategy_relevant_skips"]),
                "first_seen_utc": item["first_seen_utc"],
                "last_seen_utc": item["last_seen_utc"],
                "closed_trade_count_impact": "0",
                "live_change_authorized": "false",
            }
        )
    return sorted(rows, key=lambda row: (-int(row["skipped_setups"]), row["lane"], row["opportunity_class"], row["symbol"]))


def _row_quality(row: dict[str, str]) -> int:
    score = 0
    for key in ("raw_volume", "rounded_volume", "min_volume", "detail", "risk_atr", "spread_risk_fraction"):
        if row.get(key):
            score += 1
    if row.get("event_key"):
        score += 1
    return score


def _render_summary(
    *,
    event_rows: Sequence[dict[str, str]],
    summary_rows: Sequence[dict[str, str]],
    as_of_utc: datetime,
) -> str:
    total = len(event_rows)
    volume = sum(1 for row in event_rows if row["rejection_reason"] == "volume_below_min")
    strategy_relevant = sum(1 for row in event_rows if row["strategy_relevant"] == "true")
    lines = [
        "# LPFS Skipped Opportunity Diagnostics",
        "",
        f"Generated UTC: `{as_of_utc.isoformat()}`",
        "",
        "This packet is offline/reporting-only. It reads local copied journal rows and does not touch VPS, MT5, broker state, runtime state, live configs, or production journals.",
        "",
        "Skipped opportunities are not closed trades and are not included in closed-trade performance. `volume_below_min` is classified separately because it represents a strategy-relevant signal blocked by broker/account minimum volume.",
        "",
        "## Totals",
        "",
        f"- Logical skipped opportunities: `{total}`",
        f"- Strategy-relevant skipped opportunities: `{strategy_relevant}`",
        f"- `volume_below_min` rows: `{volume}`",
        "",
        "## Top Groups",
        "",
    ]
    if not summary_rows:
        lines.append("_No skipped opportunity rows found._")
    else:
        lines.extend(["| lane | class | reason | symbol | timeframe | side | setups |", "|---|---|---|---|---|---|---:|"])
        for row in summary_rows[:20]:
            lines.append(
                f"| `{row['lane']}` | `{row['opportunity_class']}` | `{row['rejection_reason']}` | "
                f"`{row['symbol']}` | `{row['timeframe']}` | `{row['side']}` | {row['skipped_setups']} |"
            )
    lines.extend(
        [
            "",
            "## Non-Actions",
            "",
            "- No strategy, risk, sizing, SL/TP, broker-send, config, scheduler, recovery, VPS, MT5, runtime-state, production-journal, reconciliation, canary, or broker mutation is approved by this packet.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _manifest(
    *,
    as_of_utc: datetime,
    output_dir: Path,
    source_inputs: Sequence[dict[str, Any]],
    outputs: Sequence[Path],
    event_rows: Sequence[dict[str, str]],
    summary_rows: Sequence[dict[str, str]],
) -> dict[str, Any]:
    return {
        "report": "lpfs_skipped_opportunity_diagnostics",
        "scope": "offline_read_only_skipped_opportunity_diagnostics",
        "schema_version": 1,
        "generated_at_utc": as_of_utc.isoformat(),
        "output_dir": str(output_dir),
        "inputs": {"journals": list(source_inputs)},
        "outputs": [_file_record(path) for path in outputs],
        "row_counts": {
            "skipped_opportunity_events": len(event_rows),
            "skipped_opportunity_summary": len(summary_rows),
            "volume_below_min_opportunities": sum(1 for row in event_rows if row["rejection_reason"] == "volume_below_min"),
            "strategy_relevant_skips": sum(1 for row in event_rows if row["strategy_relevant"] == "true"),
        },
        "classification": {
            "strategy_relevant_reasons": sorted(STRATEGY_RELEVANT_REASONS),
            "closed_trade_count_impact": 0,
            "performance_impact": "not_counted_as_closed_trades",
        },
        "non_actions": list(NON_ACTIONS),
    }


def _source_input(lane: str, path: Path) -> dict[str, Any]:
    return {
        "lane": lane,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "sha256": _sha256_file(path) if path.exists() else "",
    }


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "sha256": _sha256_file(path) if path.exists() else "",
    }


def _write_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    if not fieldnames:
        fieldnames = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _bucket_int(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return ""


def _signal_part(signal_key: str, index: int) -> str:
    parts = str(signal_key).split(":")
    if len(parts) <= index:
        return ""
    return parts[index]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
