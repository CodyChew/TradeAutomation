"""Build LPFS offline factor-attribution matrices from diagnostics packets.

This script is local/reporting-only. It consumes an existing
``reports/live_ops/lpfs_trade_diagnostics/<timestamp>`` packet and writes an
ignored report packet under ``reports/live_ops/lpfs_factor_attribution``.

It must not read active VPS/runtime journals, import MT5, access broker state,
or change live strategy behavior.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_factor_attribution"

REQUIRED_FILES = ("closed_trade_diagnostics.csv", "backtest_diagnostics.csv")
REQUIRED_LIVE_COLUMNS = {
    "lane",
    "symbol",
    "timeframe",
    "side",
    "excluded_from_strategy_analysis",
}
REQUIRED_BACKTEST_COLUMNS = {
    "lane",
    "symbol",
    "timeframe",
    "side",
    "r_result",
}
RECENT_WINDOW_COLUMNS = ("recent_last_3m", "recent_last_6m", "recent_last_12m")

FACTOR_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("core", "timeframe"),
    ("core", "symbol"),
    ("core", "side"),
    ("price_structure", "risk_atr_bucket"),
    ("price_structure", "setup_age_bars_bucket"),
    ("price_structure", "bars_from_lp_break_bucket"),
    ("price_structure", "fs_total_bars_bucket"),
    ("price_structure", "spread_risk_bucket"),
    ("price_structure", "candle_atr_regime_252"),
    ("price_structure", "candle_spread_regime_252"),
    ("momentum", "candle_rsi_regime"),
    ("momentum", "candle_macd_histogram_regime"),
    ("momentum", "candle_momentum_3_regime"),
    ("momentum", "candle_close_vs_ema_20"),
    ("momentum", "candle_ema_20_slope_regime"),
    ("volume", "candle_tick_volume_regime_252"),
    ("time", "analysis_session_utc"),
    ("time", "analysis_hour_utc"),
    ("time", "analysis_weekday_utc"),
)

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
)


class FactorAttributionError(RuntimeError):
    """Raised for invalid factor-attribution inputs."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostics-dir",
        required=True,
        help="Local reports/live_ops/lpfs_trade_diagnostics/<timestamp> directory.",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument(
        "--policy-ledger",
        default=None,
        help="Optional local policy ledger CSV. If omitted, policy_id is marked unavailable.",
    )
    parser.add_argument("--min-live-trades", type=int, default=10)
    parser.add_argument("--investigate-live-trades", type=int, default=3)
    parser.add_argument("--candidate-net-r", type=float, default=-3.0)
    parser.add_argument("--investigate-net-r", type=float, default=-2.0)
    parser.add_argument("--candidate-gap-vs-all", type=float, default=-0.15)
    args = parser.parse_args(argv)

    try:
        as_of = _parse_as_of(args.as_of_utc)
        diagnostics_dir = Path(args.diagnostics_dir)
        output_root = Path(args.output_root)
        output_dir = output_root / as_of.strftime("%Y%m%d_%H%M%S")
        _ensure_output_dir_under_root(output_root=output_root, output_dir=output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        result = build_factor_attribution(
            diagnostics_dir=diagnostics_dir,
            output_dir=output_dir,
            as_of_utc=as_of,
            policy_ledger=None if args.policy_ledger is None else Path(args.policy_ledger),
            min_live_trades=args.min_live_trades,
            investigate_live_trades=args.investigate_live_trades,
            candidate_net_r=args.candidate_net_r,
            investigate_net_r=args.investigate_net_r,
            candidate_gap_vs_all=args.candidate_gap_vs_all,
        )
    except FactorAttributionError as exc:
        parser.exit(2, f"error: {exc}\n")

    print(f"factor_attribution_report={result['output_dir']}")
    print(f"factor_attribution_matrix={result['factor_attribution_matrix']}")
    print(f"cross_lane_factor_confluence={result['cross_lane_factor_confluence']}")
    print(f"summary={result['summary']}")
    print(f"manifest={result['manifest']}")
    return 0


def build_factor_attribution(
    *,
    diagnostics_dir: Path,
    output_dir: Path,
    as_of_utc: datetime,
    policy_ledger: Path | None,
    min_live_trades: int = 10,
    investigate_live_trades: int = 3,
    candidate_net_r: float = -3.0,
    investigate_net_r: float = -2.0,
    candidate_gap_vs_all: float = -0.15,
) -> dict[str, str]:
    diagnostics_dir = diagnostics_dir.resolve()
    output_dir = output_dir.resolve()
    source_manifest = _load_source_manifest(diagnostics_dir)
    for filename in REQUIRED_FILES:
        _verify_manifest_file(diagnostics_dir, source_manifest, filename)

    live_path = diagnostics_dir / "closed_trade_diagnostics.csv"
    backtest_path = diagnostics_dir / "backtest_diagnostics.csv"
    live_rows, live_columns = _read_csv_rows(live_path)
    backtest_rows, backtest_columns = _read_csv_rows(backtest_path)
    _require_columns("closed_trade_diagnostics.csv", live_columns, REQUIRED_LIVE_COLUMNS)
    _require_result_column(live_columns)
    _require_columns("backtest_diagnostics.csv", backtest_columns, REQUIRED_BACKTEST_COLUMNS)

    missing_window_columns = sorted(set(RECENT_WINDOW_COLUMNS) - set(backtest_columns))
    active_factor_dimensions, candle_policy_flags = _active_factor_dimensions(
        source_manifest=source_manifest,
        live_columns=live_columns,
        backtest_columns=backtest_columns,
    )
    factor_columns = {dimension for _, dimension in active_factor_dimensions}
    live_missing_factor_columns = sorted(factor_columns - set(live_columns))
    backtest_missing_factor_columns = sorted(factor_columns - set(backtest_columns))

    data_flags: list[str] = []
    data_flags.extend(candle_policy_flags)
    if live_missing_factor_columns:
        data_flags.append("live_missing_factor_columns")
    if backtest_missing_factor_columns:
        data_flags.append("backtest_missing_factor_columns")
    if missing_window_columns:
        data_flags.append("backtest_missing_recent_window_columns")
    if policy_ledger is None:
        data_flags.append("policy_id_unavailable")
    elif not policy_ledger.exists():
        data_flags.append("policy_ledger_missing")

    live_counts = _live_counts(live_rows)
    usable_live_rows = [row for row in live_rows if not _truthy(row.get("excluded_from_strategy_analysis"))]
    if not usable_live_rows:
        raise FactorAttributionError("no non-excluded live rows available for attribution")
    if not backtest_rows:
        raise FactorAttributionError("no backtest rows available for attribution")

    matrix_rows = _factor_matrix_rows(
        live_rows=usable_live_rows,
        backtest_rows=backtest_rows,
        min_live_trades=min_live_trades,
        investigate_live_trades=investigate_live_trades,
        candidate_net_r=candidate_net_r,
        investigate_net_r=investigate_net_r,
        candidate_gap_vs_all=candidate_gap_vs_all,
        factor_dimensions=active_factor_dimensions,
    )
    if not matrix_rows:
        data_flags.append("no_factor_rows")
    confluence_rows = _cross_lane_rows(matrix_rows, min_live_trades=min_live_trades, candidate_net_r=candidate_net_r)

    live_timestamps = _timestamps(usable_live_rows)
    backtest_timestamps = _timestamps(backtest_rows)
    factor_coverage = _factor_coverage(usable_live_rows, backtest_rows, factor_dimensions=active_factor_dimensions)
    backtest_missing_factor_values = sorted(
        dimension
        for dimension, coverage in factor_coverage.items()
        if int(coverage["live_rows_with_value"]) > 0 and int(coverage["backtest_rows_with_value"]) == 0
    )
    if backtest_missing_factor_values:
        data_flags.append("backtest_missing_factor_values")

    factor_csv = output_dir / "factor_attribution_matrix.csv"
    confluence_csv = output_dir / "cross_lane_factor_confluence.csv"
    summary_md = output_dir / "summary.md"
    manifest_json = output_dir / "manifest.json"
    _write_csv(factor_csv, matrix_rows)
    _write_csv(confluence_csv, confluence_rows)
    summary_md.write_text(
        _render_summary(
            diagnostics_dir=diagnostics_dir,
            matrix_rows=matrix_rows,
            confluence_rows=confluence_rows,
            live_timestamps=live_timestamps,
            data_flags=data_flags,
        ),
        encoding="utf-8",
    )
    manifest_payload = _manifest(
        diagnostics_dir=diagnostics_dir,
        source_manifest=source_manifest,
        as_of_utc=as_of_utc,
        live_path=live_path,
        backtest_path=backtest_path,
        outputs=[factor_csv, confluence_csv, summary_md],
        matrix_rows=matrix_rows,
        confluence_rows=confluence_rows,
        live_counts=live_counts,
        live_timestamps=live_timestamps,
        backtest_timestamps=backtest_timestamps,
        backtest_row_count=len(backtest_rows),
        factor_coverage=factor_coverage,
        data_flags=data_flags,
        factor_dimensions=active_factor_dimensions,
        policy_ledger=policy_ledger,
        missing_columns={
            "live_missing_factor_columns": live_missing_factor_columns,
            "backtest_missing_factor_columns": backtest_missing_factor_columns,
            "backtest_missing_recent_window_columns": missing_window_columns,
            "backtest_missing_factor_values": backtest_missing_factor_values,
        },
    )
    manifest_json.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "factor_attribution_matrix": str(factor_csv),
        "cross_lane_factor_confluence": str(confluence_csv),
        "summary": str(summary_md),
        "manifest": str(manifest_json),
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
        raise FactorAttributionError(f"output path must stay under output root: {resolved}") from exc


def _load_source_manifest(diagnostics_dir: Path) -> dict[str, Any]:
    manifest_path = diagnostics_dir / "manifest.json"
    if not manifest_path.exists():
        raise FactorAttributionError(f"missing diagnostics manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FactorAttributionError(f"malformed diagnostics manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise FactorAttributionError("diagnostics manifest is not an object")
    if manifest.get("scope") != "offline_read_only_strategy_attribution":
        raise FactorAttributionError("diagnostics manifest scope is not offline_read_only_strategy_attribution")
    return manifest


def _verify_manifest_file(diagnostics_dir: Path, manifest: dict[str, Any], filename: str) -> None:
    path = diagnostics_dir / filename
    if not path.exists():
        raise FactorAttributionError(f"missing required diagnostics file: {path}")
    output = None
    for candidate in manifest.get("outputs", []):
        if isinstance(candidate, dict) and Path(str(candidate.get("path", ""))).name == filename:
            output = candidate
            break
    if output is None:
        raise FactorAttributionError(f"source manifest does not list {filename}")
    expected = str(output.get("sha256", "")).strip().lower()
    if not expected:
        raise FactorAttributionError(f"source manifest lacks sha256 for {filename}")
    actual = _sha256_file(path)
    if actual.lower() != expected:
        raise FactorAttributionError(f"source hash mismatch for {filename}: expected {expected}, got {actual}")


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _require_columns(label: str, columns: Sequence[str], required: Iterable[str]) -> None:
    missing = sorted(set(required) - set(columns))
    if missing:
        raise FactorAttributionError(f"{label} missing required columns: {', '.join(missing)}")


def _require_result_column(columns: Sequence[str]) -> None:
    if "r_result" not in columns and "aggregate_r_result" not in columns:
        raise FactorAttributionError("closed_trade_diagnostics.csv missing r_result or aggregate_r_result")


def _active_factor_dimensions(
    *,
    source_manifest: dict[str, Any],
    live_columns: Sequence[str],
    backtest_columns: Sequence[str],
) -> tuple[tuple[tuple[str, str], ...], list[str]]:
    candle_dimensions = {dimension for _, dimension in FACTOR_DIMENSIONS if dimension.startswith("candle_")}
    candle_columns_present = bool((set(live_columns) | set(backtest_columns)) & candle_dimensions)
    if not candle_columns_present:
        return FACTOR_DIMENSIONS, []
    candle_sources = ((source_manifest.get("inputs") or {}).get("candle_sources") or [])
    sources_safe = bool(candle_sources) and all(
        isinstance(source, dict) and source.get("safe_for_strategy_analysis") is True for source in candle_sources
    )
    if sources_safe:
        return FACTOR_DIMENSIONS, []
    active = tuple((family, dimension) for family, dimension in FACTOR_DIMENSIONS if not dimension.startswith("candle_"))
    return active, ["candle_source_provenance_unverified"]


def _live_counts(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    by_lane: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "excluded": 0, "usable": 0})
    excluded = 0
    for row in rows:
        lane = _lane(row)
        by_lane[lane]["total"] += 1
        if _truthy(row.get("excluded_from_strategy_analysis")):
            excluded += 1
            by_lane[lane]["excluded"] += 1
        else:
            by_lane[lane]["usable"] += 1
    return {
        "total": len(rows),
        "excluded_from_strategy_analysis": excluded,
        "usable_for_strategy_attribution": len(rows) - excluded,
        "by_lane": dict(sorted(by_lane.items())),
    }


def _factor_matrix_rows(
    *,
    live_rows: Sequence[dict[str, str]],
    backtest_rows: Sequence[dict[str, str]],
    min_live_trades: int,
    investigate_live_trades: int,
    candidate_net_r: float,
    investigate_net_r: float,
    candidate_gap_vs_all: float,
    factor_dimensions: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    live_buckets: dict[tuple[str, str, str, str], _Stats] = defaultdict(_Stats)
    backtest_buckets: dict[tuple[str, str, str, str, str], _Stats] = defaultdict(_Stats)

    for row in live_rows:
        lane = _lane(row)
        result = _row_result(row)
        if result is None:
            continue
        for family, dimension in factor_dimensions:
            value = _factor_value(row, dimension)
            if value == "":
                continue
            live_buckets[(lane, family, dimension, value)].add(result)

    for row in backtest_rows:
        lane = _lane(row)
        result = _float(row.get("r_result"))
        if result is None:
            continue
        for family, dimension in factor_dimensions:
            value = _factor_value(row, dimension)
            if value == "":
                continue
            for window in _windows_for_row(row):
                backtest_buckets[(lane, family, dimension, value, window)].add(result)

    rows: list[dict[str, Any]] = []
    for key, live_stats in live_buckets.items():
        lane, family, dimension, value = key
        live_payload = live_stats.payload()
        row: dict[str, Any] = {
            "lane": lane,
            "factor_family": family,
            "dimension": dimension,
            "value": value,
            **{f"live_{name}": val for name, val in live_payload.items()},
        }
        for window in ("all", "last_12m", "last_6m", "last_3m"):
            payload = backtest_buckets[(lane, family, dimension, value, window)].payload()
            for name, val in payload.items():
                row[f"backtest_{window}_{name}"] = val

        row["avg_r_gap_vs_all"] = _delta(row["live_avg_r"], row["backtest_all_avg_r"])
        row["avg_r_gap_vs_12m"] = _delta(row["live_avg_r"], row["backtest_last_12m_avg_r"])
        row["avg_r_gap_vs_6m"] = _delta(row["live_avg_r"], row["backtest_last_6m_avg_r"])
        row["avg_r_gap_vs_3m"] = _delta(row["live_avg_r"], row["backtest_last_3m_avg_r"])
        row["sample_status"] = _sample_status(
            int(row["live_trades"]),
            int(row["backtest_all_trades"]),
            min_live_trades=min_live_trades,
            investigate_live_trades=investigate_live_trades,
        )
        row["lane_signal_status"] = _lane_signal_status(
            row,
            min_live_trades=min_live_trades,
            investigate_live_trades=investigate_live_trades,
            candidate_net_r=candidate_net_r,
            investigate_net_r=investigate_net_r,
            candidate_gap_vs_all=candidate_gap_vs_all,
        )
        row["decision_boundary"] = "research_only_not_live_approval"
        row["caveats"] = _row_caveats(row)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            _lane_status_rank(str(item["lane_signal_status"])),
            str(item["lane"]),
            _sort_number(item["live_net_r"]),
            str(item["factor_family"]),
            str(item["dimension"]),
            str(item["value"]),
        )
    )
    return rows


def _cross_lane_rows(matrix_rows: Sequence[dict[str, Any]], *, min_live_trades: int, candidate_net_r: float) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in matrix_rows:
        grouped[(str(row["factor_family"]), str(row["dimension"]), str(row["value"]))][str(row["lane"])] = row

    rows: list[dict[str, Any]] = []
    for (family, dimension, value), lanes in grouped.items():
        ftmo = lanes.get("FTMO")
        ic = lanes.get("IC")
        if ftmo is None and ic is None:
            continue
        ftmo_net = _optional_float(None if ftmo is None else ftmo.get("live_net_r"))
        ic_net = _optional_float(None if ic is None else ic.get("live_net_r"))
        ftmo_trades = int(ftmo.get("live_trades", 0)) if ftmo else 0
        ic_trades = int(ic.get("live_trades", 0)) if ic else 0
        combined_net = (ftmo_net or 0.0) + (ic_net or 0.0)
        combined_trades = ftmo_trades + ic_trades
        if ftmo is not None and ic is not None and (ftmo_net or 0.0) < 0 and (ic_net or 0.0) < 0:
            status = "both_lanes_negative"
            if combined_trades >= min_live_trades and combined_net <= candidate_net_r:
                decision = "research_triggered"
            else:
                decision = "investigate_small_sample"
        elif ftmo is None or ic is None or (ftmo_net or 0.0) < 0 or (ic_net or 0.0) < 0:
            status = "one_lane_divergence_or_missing_lane"
            decision = "watch_divergence"
        else:
            status = "not_negative_confluence"
            decision = "context"
        rows.append(
            {
                "factor_family": family,
                "dimension": dimension,
                "value": value,
                "ftmo_trades": ftmo_trades,
                "ftmo_net_r": _round_or_blank(ftmo_net),
                "ftmo_avg_r_gap_vs_all": "" if ftmo is None else ftmo.get("avg_r_gap_vs_all", ""),
                "ic_trades": ic_trades,
                "ic_net_r": _round_or_blank(ic_net),
                "ic_avg_r_gap_vs_all": "" if ic is None else ic.get("avg_r_gap_vs_all", ""),
                "combined_live_trades": combined_trades,
                "combined_live_net_r": _round(combined_net),
                "confluence_status": status,
                "strategy_research_decision": decision,
                "decision_boundary": "research_only_not_live_approval",
            }
        )
    rows.sort(
        key=lambda item: (
            {"research_triggered": 0, "investigate_small_sample": 1, "watch_divergence": 2, "context": 3}[
                str(item["strategy_research_decision"])
            ],
            _sort_number(item["combined_live_net_r"]),
            str(item["factor_family"]),
            str(item["dimension"]),
            str(item["value"]),
        )
    )
    return rows


class _Stats:
    def __init__(self) -> None:
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.net_r = 0.0
        self.gross_win = 0.0
        self.gross_loss = 0.0

    def add(self, result: float) -> None:
        self.trades += 1
        self.net_r += result
        if result > 0:
            self.wins += 1
            self.gross_win += result
        elif result < 0:
            self.losses += 1
            self.gross_loss += abs(result)

    def payload(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "net_r": _round(self.net_r),
            "avg_r": _round(self.net_r / self.trades) if self.trades else "",
            "win_rate": _round(self.wins / self.trades) if self.trades else "",
            "profit_factor": _round(self.gross_win / self.gross_loss) if self.gross_loss else ("" if self.gross_win == 0 else "inf"),
        }


def _windows_for_row(row: dict[str, str]) -> list[str]:
    windows = ["all"]
    if _truthy(row.get("recent_last_12m")):
        windows.append("last_12m")
    if _truthy(row.get("recent_last_6m")):
        windows.append("last_6m")
    if _truthy(row.get("recent_last_3m")):
        windows.append("last_3m")
    return windows


def _lane(row: dict[str, str]) -> str:
    return str(row.get("lane", "")).strip().upper()


def _factor_value(row: dict[str, str], dimension: str) -> str:
    value = str(row.get(dimension, "") or "").strip().lower()
    if value in {"nan", "none", "null"}:
        return ""
    return value


def _row_result(row: dict[str, str]) -> float | None:
    return _float(row.get("aggregate_r_result")) if str(row.get("aggregate_r_result", "")).strip() else _float(row.get("r_result"))


def _float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed != parsed:
        return None
    return parsed


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _float(value)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _delta(left: Any, right: Any) -> float | str:
    parsed_left = _optional_float(left)
    parsed_right = _optional_float(right)
    if parsed_left is None or parsed_right is None:
        return ""
    return _round(parsed_left - parsed_right)


def _round(value: float) -> float:
    return round(float(value), 6)


def _round_or_blank(value: float | None) -> float | str:
    return "" if value is None else _round(value)


def _sort_number(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _sample_status(live_trades: int, backtest_trades: int, *, min_live_trades: int, investigate_live_trades: int) -> str:
    if live_trades >= min_live_trades and backtest_trades > 0:
        return "candidate_sample"
    if live_trades >= investigate_live_trades and backtest_trades > 0:
        return "investigation_sample"
    if live_trades > 0:
        return "small_live_sample"
    return "no_live_sample"


def _lane_signal_status(
    row: dict[str, Any],
    *,
    min_live_trades: int,
    investigate_live_trades: int,
    candidate_net_r: float,
    investigate_net_r: float,
    candidate_gap_vs_all: float,
) -> str:
    live_trades = int(row["live_trades"])
    live_net_r = float(row["live_net_r"])
    gap = _optional_float(row.get("avg_r_gap_vs_all"))
    if (
        live_trades >= min_live_trades
        and live_net_r <= candidate_net_r
        and gap is not None
        and gap <= candidate_gap_vs_all
    ):
        return "lane_research_candidate"
    if live_trades >= investigate_live_trades and live_net_r <= investigate_net_r:
        return "lane_investigate"
    if live_net_r < 0:
        return "lane_watch"
    return "lane_context"


def _lane_status_rank(status: str) -> int:
    return {"lane_research_candidate": 0, "lane_investigate": 1, "lane_watch": 2, "lane_context": 3}.get(status, 9)


def _row_caveats(row: dict[str, Any]) -> str:
    caveats: list[str] = []
    if row["sample_status"] in {"small_live_sample", "investigation_sample"}:
        caveats.append(row["sample_status"])
    if int(row.get("backtest_all_trades", 0) or 0) == 0:
        caveats.append("missing_backtest_bucket")
    if row["lane_signal_status"] != "lane_context":
        caveats.append("not_live_approval")
    return ";".join(caveats)


def _factor_coverage(
    live_rows: Sequence[dict[str, str]],
    backtest_rows: Sequence[dict[str, str]],
    *,
    factor_dimensions: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for family, dimension in factor_dimensions:
        live_present = sum(1 for row in live_rows if _factor_value(row, dimension) != "")
        backtest_present = sum(1 for row in backtest_rows if _factor_value(row, dimension) != "")
        result[dimension] = {
            "family": family,
            "live_rows_with_value": live_present,
            "backtest_rows_with_value": backtest_present,
        }
    return result


def _timestamps(rows: Sequence[dict[str, str]]) -> dict[str, str]:
    values: list[str] = []
    for row in rows:
        for column in ("result_time_utc", "closed_utc", "exit_time_utc", "analysis_time_utc"):
            value = str(row.get(column, "") or "").strip()
            if value:
                values.append(value)
                break
    return {"min": min(values) if values else "", "max": max(values) if values else ""}


def _render_summary(
    *,
    diagnostics_dir: Path,
    matrix_rows: Sequence[dict[str, Any]],
    confluence_rows: Sequence[dict[str, Any]],
    live_timestamps: dict[str, str],
    data_flags: Sequence[str],
) -> str:
    top_lanes = list(matrix_rows[:12])
    top_confluence = [row for row in confluence_rows if row["strategy_research_decision"] in {"research_triggered", "investigate_small_sample"}][:12]
    lines = [
        "# LPFS Factor Attribution Matrix",
        "",
        "Scope: offline/read-only factor attribution from an existing local diagnostics packet.",
        "",
        "This report is not live approval, not deployment approval, and not approval for any strategy, risk, sizing, SL/TP, recovery, config, scheduler, watchdog, or broker-send change.",
        "",
        f"Input diagnostics: `{diagnostics_dir}`.",
        f"Live result timestamp range: `{live_timestamps.get('min', '')}` to `{live_timestamps.get('max', '')}`.",
        "",
    ]
    if data_flags:
        lines.extend(["## Data Validity Flags", ""])
        for flag in data_flags:
            lines.append(f"- `{flag}`")
        lines.append("")
    lines.extend(["## Strongest Lane-First Rows", ""])
    for row in top_lanes:
        lines.append(
            "- "
            f"{row['lane']} {row['factor_family']}/{row['dimension']}={row['value']}: "
            f"live {row['live_trades']} trades / {float(row['live_net_r']):+.2f}R, "
            f"avg {float(row['live_avg_r']):+.3f}R, "
            f"all-history avg {_fmt_signed(row['backtest_all_avg_r'])}R, "
            f"gap {_fmt_signed(row['avg_r_gap_vs_all'])}; "
            f"`{row['lane_signal_status']}`."
        )
    lines.extend(["", "## Cross-Lane Rows", ""])
    for row in top_confluence:
        lines.append(
            "- "
            f"{row['factor_family']}/{row['dimension']}={row['value']}: "
            f"FTMO {row['ftmo_trades']} / {_fmt_signed(row['ftmo_net_r'])}R, "
            f"IC {row['ic_trades']} / {_fmt_signed(row['ic_net_r'])}R, "
            f"combined {row['combined_live_trades']} / {_fmt_signed(row['combined_live_net_r'])}R; "
            f"`{row['strategy_research_decision']}`."
        )
    lines.extend(
        [
            "",
            "## Decision Boundary",
            "",
            "Rows marked as research candidates only justify offline investigation and backtests. They do not approve live filters or production rule changes.",
            "",
        ]
    )
    return "\n".join(lines)


def _fmt_signed(value: Any) -> str:
    parsed = _optional_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:+.2f}"


def _manifest(
    *,
    diagnostics_dir: Path,
    source_manifest: dict[str, Any],
    as_of_utc: datetime,
    live_path: Path,
    backtest_path: Path,
    outputs: Sequence[Path],
    matrix_rows: Sequence[dict[str, Any]],
    confluence_rows: Sequence[dict[str, Any]],
    live_counts: dict[str, Any],
    live_timestamps: dict[str, str],
    backtest_timestamps: dict[str, str],
    backtest_row_count: int,
    factor_coverage: dict[str, Any],
    data_flags: Sequence[str],
    factor_dimensions: Sequence[tuple[str, str]],
    policy_ledger: Path | None,
    missing_columns: dict[str, list[str]],
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "scope": "offline_read_only_factor_attribution",
        "generated_at_utc": as_of_utc.isoformat(),
        "diagnostics_dir": str(diagnostics_dir),
        "source_manifest_sha256": _sha256_file(diagnostics_dir / "manifest.json"),
        "source_manifest_scope": source_manifest.get("scope", ""),
        "inputs": [
            _file_info(live_path),
            _file_info(backtest_path),
        ],
        "policy_ledger": _file_info(policy_ledger) if policy_ledger is not None and policy_ledger.exists() else None,
        "row_counts": {
            "factor_attribution_matrix": len(matrix_rows),
            "cross_lane_factor_confluence": len(confluence_rows),
            "closed_trade_diagnostics": live_counts["total"],
            "backtest_diagnostics": backtest_row_count,
            **live_counts,
        },
        "timestamps": {
            "live": live_timestamps,
            "backtest": backtest_timestamps,
        },
        "factor_coverage": factor_coverage,
        "factor_dimensions_used": [
            {"family": family, "dimension": dimension} for family, dimension in factor_dimensions
        ],
        "data_validity_flags": sorted(set(data_flags)),
        "missing_columns": missing_columns,
        "non_actions": list(NON_ACTIONS),
        "decision_boundary": "research_only_not_live_approval",
        "outputs": [_file_info(path) for path in outputs],
    }
    return payload


def _file_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    exists = path.exists()
    info: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if exists and path.is_file():
        info.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return info


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
