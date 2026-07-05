"""Build LPFS offline candidate backtest matrices.

This script is local/reporting-only. It consumes an existing
``reports/live_ops/lpfs_trade_diagnostics/<timestamp>`` packet and a
research-only candidate config, then writes an ignored report packet under
``reports/live_ops/lpfs_candidate_backtest_matrix``.

It must not read active VPS/runtime journals, import MT5, access broker state,
or change live strategy behavior.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_candidate_backtest_matrix"
DEFAULT_CANDIDATE_CONFIG = REPO_ROOT / "configs" / "strategy_research" / "lpfs_candidate_matrix_current.json"

REQUIRED_DIAGNOSTIC_FILES = ("closed_trade_diagnostics.csv", "backtest_diagnostics.csv")
REQUIRED_LIVE_COLUMNS = {"lane", "symbol", "timeframe", "side", "excluded_from_strategy_analysis"}
REQUIRED_BACKTEST_COLUMNS = {"lane", "symbol", "timeframe", "side", "r_result"}
RECENT_WINDOW_COLUMNS = ("recent_last_3m", "recent_last_6m", "recent_last_12m")
WINDOWS: tuple[tuple[str, str, str | None], ...] = (
    ("all", "Long-history guardrail", None),
    ("last_12m", "Recent 12M", "recent_last_12m"),
    ("last_6m", "Recent 6M", "recent_last_6m"),
    ("last_3m", "Recent 3M", "recent_last_3m"),
)
LANES = ("COMBINED", "FTMO", "IC")
CANDLE_FIELDS = {
    "candle_atr_regime_252",
    "candle_spread_regime_252",
    "candle_tick_volume_regime_252",
    "candle_macd_histogram_regime",
    "candle_rsi_regime",
    "candle_ema_20_slope_regime",
    "candle_momentum_3_regime",
    "candle_close_vs_ema_20",
    "candle_direction",
}
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


class CandidateMatrixError(RuntimeError):
    """Raised for invalid candidate-matrix inputs."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostics-dir", required=True)
    parser.add_argument("--candidate-config", default=str(DEFAULT_CANDIDATE_CONFIG))
    parser.add_argument(
        "--factor-attribution-dir",
        default=None,
        help="Optional factor-attribution packet to validate and link as hypothesis source.",
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--as-of-utc", default=None)
    args = parser.parse_args(argv)

    try:
        as_of = _parse_as_of(args.as_of_utc)
        output_root = Path(args.output_root)
        output_dir = output_root / as_of.strftime("%Y%m%d_%H%M%S")
        _ensure_output_dir_under_root(output_root=output_root, output_dir=output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        result = build_candidate_matrix(
            diagnostics_dir=Path(args.diagnostics_dir),
            candidate_config=Path(args.candidate_config),
            factor_attribution_dir=None if args.factor_attribution_dir is None else Path(args.factor_attribution_dir),
            output_dir=output_dir,
            as_of_utc=as_of,
        )
    except CandidateMatrixError as exc:
        parser.exit(2, f"error: {exc}\n")

    print(f"candidate_matrix_report={result['output_dir']}")
    print(f"candidate_decision_summary={result['candidate_decision_summary']}")
    print(f"candidate_guardrails={result['candidate_guardrails']}")
    print(f"summary={result['summary']}")
    print(f"manifest={result['manifest']}")
    print(f"manifest_sha256={result['manifest_sha256']}")
    return 0


def build_candidate_matrix(
    *,
    diagnostics_dir: Path,
    candidate_config: Path,
    factor_attribution_dir: Path | None,
    output_dir: Path,
    as_of_utc: datetime,
) -> dict[str, str]:
    diagnostics_dir = diagnostics_dir.resolve()
    candidate_config = candidate_config.resolve()
    output_dir = output_dir.resolve()
    source_manifest = _load_diagnostics_manifest(diagnostics_dir)
    for filename in REQUIRED_DIAGNOSTIC_FILES:
        _verify_manifest_file(diagnostics_dir, source_manifest, filename)
    factor_manifest = None
    if factor_attribution_dir is not None:
        factor_attribution_dir = factor_attribution_dir.resolve()
        factor_manifest = _load_factor_manifest(factor_attribution_dir)
        for filename in ("factor_attribution_matrix.csv", "cross_lane_factor_confluence.csv"):
            _verify_manifest_file(factor_attribution_dir, factor_manifest, filename)

    config_payload = _load_candidate_config(candidate_config)
    defaults = config_payload["candidate_defaults"]
    candidates = config_payload["candidates"]

    live_path = diagnostics_dir / "closed_trade_diagnostics.csv"
    backtest_path = diagnostics_dir / "backtest_diagnostics.csv"
    live_rows, live_columns = _read_csv_rows(live_path)
    backtest_rows, backtest_columns = _read_csv_rows(backtest_path)
    _require_columns("closed_trade_diagnostics.csv", live_columns, REQUIRED_LIVE_COLUMNS)
    _require_result_column(live_columns)
    _require_columns("backtest_diagnostics.csv", backtest_columns, REQUIRED_BACKTEST_COLUMNS)
    missing_recent_columns = sorted(set(RECENT_WINDOW_COLUMNS) - set(backtest_columns))
    if missing_recent_columns:
        raise CandidateMatrixError(
            "backtest_diagnostics.csv missing recent-window columns: " + ", ".join(missing_recent_columns)
        )

    usable_live_rows = [row for row in live_rows if not _truthy(row.get("excluded_from_strategy_analysis"))]
    if not usable_live_rows:
        raise CandidateMatrixError("no non-excluded live rows available for candidate matrix")
    if not backtest_rows:
        raise CandidateMatrixError("no backtest rows available for candidate matrix")

    complete_coverage_threshold = float(defaults["complete_coverage_threshold"])
    max_removal_share = float(defaults["max_removal_share"])
    min_live_trades = int(defaults["min_live_trades"])

    candidate_definitions = _candidate_definitions(candidates)
    filter_matrix = _filter_matrix_rows(
        candidates=candidates,
        backtest_rows=backtest_rows,
        complete_coverage_threshold=complete_coverage_threshold,
    )
    live_context = _live_context_rows(
        candidates=candidates,
        live_rows=usable_live_rows,
        complete_coverage_threshold=complete_coverage_threshold,
    )
    decision_summary, guardrails = _decision_and_guardrails(
        candidates=candidates,
        filter_matrix=filter_matrix,
        live_context=live_context,
        complete_coverage_threshold=complete_coverage_threshold,
        min_live_trades=min_live_trades,
        max_removal_share=max_removal_share,
    )
    overlap_matrix = _overlap_rows(candidates=candidates, live_rows=usable_live_rows, backtest_rows=backtest_rows)

    paths = {
        "candidate_definitions": output_dir / "candidate_definitions.csv",
        "candidate_filter_matrix": output_dir / "candidate_filter_matrix.csv",
        "candidate_live_context": output_dir / "candidate_live_context.csv",
        "candidate_decision_summary": output_dir / "candidate_decision_summary.csv",
        "candidate_guardrails": output_dir / "candidate_guardrails.csv",
        "candidate_overlap_matrix": output_dir / "candidate_overlap_matrix.csv",
        "summary": output_dir / "summary.md",
        "manifest": output_dir / "manifest.json",
    }
    _write_csv(paths["candidate_definitions"], candidate_definitions)
    _write_csv(paths["candidate_filter_matrix"], filter_matrix)
    _write_csv(paths["candidate_live_context"], live_context)
    _write_csv(paths["candidate_decision_summary"], decision_summary)
    _write_csv(paths["candidate_guardrails"], guardrails)
    _write_csv(paths["candidate_overlap_matrix"], overlap_matrix)
    paths["summary"].write_text(
        _render_summary(
            diagnostics_dir=diagnostics_dir,
            factor_attribution_dir=factor_attribution_dir,
            source_manifest=source_manifest,
            config_payload=config_payload,
            decision_summary=decision_summary,
        ),
        encoding="utf-8",
    )
    manifest = _manifest(
        diagnostics_dir=diagnostics_dir,
        source_manifest=source_manifest,
        factor_attribution_dir=factor_attribution_dir,
        factor_manifest=factor_manifest,
        candidate_config=candidate_config,
        config_payload=config_payload,
        as_of_utc=as_of_utc,
        live_path=live_path,
        backtest_path=backtest_path,
        outputs=[path for key, path in paths.items() if key != "manifest"],
        row_counts={
            "candidate_definitions": len(candidate_definitions),
            "candidate_filter_matrix": len(filter_matrix),
            "candidate_live_context": len(live_context),
            "candidate_decision_summary": len(decision_summary),
            "candidate_guardrails": len(guardrails),
            "candidate_overlap_matrix": len(overlap_matrix),
            "live_rows_current_safe": len(usable_live_rows),
            "backtest_rows": len(backtest_rows),
        },
    )
    paths["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_hash = _sha256_file(paths["manifest"])
    (output_dir / "manifest.sha256.txt").write_text(f"{manifest_hash}  manifest.json\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "candidate_decision_summary": str(paths["candidate_decision_summary"]),
        "candidate_guardrails": str(paths["candidate_guardrails"]),
        "summary": str(paths["summary"]),
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
        raise CandidateMatrixError(f"output path must stay under output root: {resolved}") from exc


def _load_diagnostics_manifest(diagnostics_dir: Path) -> dict[str, Any]:
    manifest = _load_json(diagnostics_dir / "manifest.json", label="diagnostics manifest")
    if manifest.get("scope") != "offline_read_only_strategy_attribution":
        raise CandidateMatrixError("diagnostics manifest scope is not offline_read_only_strategy_attribution")
    return manifest


def _load_factor_manifest(factor_attribution_dir: Path) -> dict[str, Any]:
    manifest = _load_json(factor_attribution_dir / "manifest.json", label="factor-attribution manifest")
    if manifest.get("scope") != "offline_read_only_factor_attribution":
        raise CandidateMatrixError("factor-attribution manifest scope is not offline_read_only_factor_attribution")
    return manifest


def _load_candidate_config(path: Path) -> dict[str, Any]:
    payload = _load_json(path, label="candidate config")
    if int(payload.get("schema_version", 0) or 0) != 1:
        raise CandidateMatrixError("candidate config schema_version must be 1")
    defaults = payload.get("candidate_defaults")
    candidates = payload.get("candidates")
    if not isinstance(defaults, dict):
        raise CandidateMatrixError("candidate config missing candidate_defaults")
    if not isinstance(candidates, list) or not candidates:
        raise CandidateMatrixError("candidate config must contain at least one candidate")
    for key in ("min_live_trades", "max_removal_share", "complete_coverage_threshold"):
        if key not in defaults:
            raise CandidateMatrixError(f"candidate_defaults missing {key}")
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise CandidateMatrixError(f"candidate {index} is not an object")
        for key in ("candidate_id", "candidate_label", "candidate_type", "source_factor_family", "filters", "rationale"):
            if key not in candidate:
                raise CandidateMatrixError(f"candidate {index} missing {key}")
        if candidate["candidate_id"] in seen:
            raise CandidateMatrixError(f"duplicate candidate_id: {candidate['candidate_id']}")
        seen.add(str(candidate["candidate_id"]))
        if not isinstance(candidate["filters"], dict) or not candidate["filters"]:
            raise CandidateMatrixError(f"candidate {candidate['candidate_id']} has no filters")
    return payload


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise CandidateMatrixError(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateMatrixError(f"malformed {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise CandidateMatrixError(f"{label} is not an object")
    return payload


def _verify_manifest_file(directory: Path, manifest: dict[str, Any], filename: str) -> None:
    path = directory / filename
    if not path.exists():
        raise CandidateMatrixError(f"missing required source file: {path}")
    output = None
    for candidate in manifest.get("outputs", []):
        if isinstance(candidate, dict) and Path(str(candidate.get("path", ""))).name == filename:
            output = candidate
            break
    if output is None:
        raise CandidateMatrixError(f"source manifest does not list {filename}")
    expected = str(output.get("sha256", "")).strip().lower()
    if not expected:
        raise CandidateMatrixError(f"source manifest lacks sha256 for {filename}")
    actual = _sha256_file(path)
    if actual != expected:
        raise CandidateMatrixError(f"source hash mismatch for {filename}: expected {expected}, got {actual}")


def _read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def _require_columns(label: str, columns: Sequence[str], required: Iterable[str]) -> None:
    missing = sorted(set(required) - set(columns))
    if missing:
        raise CandidateMatrixError(f"{label} missing required columns: {', '.join(missing)}")


def _require_result_column(columns: Sequence[str]) -> None:
    if "r_result" not in columns and "aggregate_r_result" not in columns:
        raise CandidateMatrixError("closed_trade_diagnostics.csv missing r_result or aggregate_r_result")


def _candidate_definitions(candidates: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for candidate in candidates:
        filters = _candidate_filters(candidate)
        rows.append(
            {
                "candidate_id": str(candidate["candidate_id"]),
                "candidate_label": str(candidate["candidate_label"]),
                "candidate_type": str(candidate["candidate_type"]),
                "filter_expression": _filter_text(filters),
                "filter_columns": ",".join(filters),
                "source_factor_family": str(candidate["source_factor_family"]),
                "requires_candle_provenance": str(any(key in CANDLE_FIELDS for key in filters)).lower(),
                "rationale": str(candidate["rationale"]),
                "status_before_run": "research_triggered",
                "decision_boundary": "offline_research_only_not_live_approval",
            }
        )
    return rows


def _filter_matrix_rows(
    *,
    candidates: Sequence[dict[str, Any]],
    backtest_rows: Sequence[dict[str, str]],
    complete_coverage_threshold: float,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        filters = _candidate_filters(candidate)
        for window, window_label, flag in WINDOWS:
            for lane in LANES:
                base = _filter_rows(backtest_rows, lane=lane, window_flag=flag)
                coverage_count = sum(1 for row in base if _has_all_filter_fields(row, filters))
                coverage_share = coverage_count / len(base) if base else 0.0
                candidate_subset = [row for row in base if _matches(row, filters)]
                after_exclusion = [row for row in base if not _matches(row, filters)]
                baseline_stats = _metrics(base)
                candidate_stats = _metrics(candidate_subset)
                after_stats = _metrics(after_exclusion)
                removal_share = candidate_stats["trades"] / baseline_stats["trades"] if baseline_stats["trades"] else ""
                delta_net = after_stats["net_r"] - baseline_stats["net_r"] if baseline_stats["trades"] else ""
                delta_avg = (
                    after_stats["avg_r"] - baseline_stats["avg_r"]
                    if baseline_stats["trades"] and after_stats["avg_r"] != "" and baseline_stats["avg_r"] != ""
                    else ""
                )
                coverage_status = "complete" if coverage_share >= complete_coverage_threshold else "incomplete"
                row = {
                    "candidate_id": str(candidate["candidate_id"]),
                    "candidate_label": str(candidate["candidate_label"]),
                    "candidate_type": str(candidate["candidate_type"]),
                    "filters": _filter_text(filters),
                    "comparison_window": window,
                    "window_label": window_label,
                    "lane": lane,
                    "filter_field_coverage_rows": _fmt(coverage_count),
                    "filter_field_coverage_share": _fmt(coverage_share),
                    "coverage_status": coverage_status,
                }
                row.update(_metric_fields("baseline", baseline_stats))
                row.update(_metric_fields("candidate_subset", candidate_stats))
                row.update(_metric_fields("after_exclusion", after_stats))
                row.update(
                    {
                        "candidate_removal_share": _fmt(removal_share),
                        "exclusion_delta_net_r": _fmt(delta_net),
                        "exclusion_delta_avg_r": _fmt(delta_avg),
                        "window_interpretation": _interpret_window(
                            candidate_stats, baseline_stats, after_stats, coverage_status=coverage_status
                        ),
                    }
                )
                rows.append(row)
    return rows


def _live_context_rows(
    *,
    candidates: Sequence[dict[str, Any]],
    live_rows: Sequence[dict[str, str]],
    complete_coverage_threshold: float,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        filters = _candidate_filters(candidate)
        for lane in LANES:
            base = _filter_rows(live_rows, lane=lane)
            coverage_count = sum(1 for row in base if _has_all_filter_fields(row, filters))
            coverage_share = coverage_count / len(base) if base else 0.0
            candidate_subset = [row for row in base if _matches(row, filters)]
            baseline_stats = _metrics(base)
            candidate_stats = _metrics(candidate_subset)
            row = {
                "candidate_id": str(candidate["candidate_id"]),
                "candidate_label": str(candidate["candidate_label"]),
                "candidate_type": str(candidate["candidate_type"]),
                "filters": _filter_text(filters),
                "live_scope": "current_safe_diagnostics_packet",
                "lane": lane,
                "filter_field_coverage_rows": _fmt(coverage_count),
                "filter_field_coverage_share": _fmt(coverage_share),
                "coverage_status": "complete" if coverage_share >= complete_coverage_threshold else "incomplete",
            }
            row.update(_metric_fields("baseline_live", baseline_stats))
            row.update(_metric_fields("candidate_live", candidate_stats))
            row["candidate_live_share"] = _fmt(
                candidate_stats["trades"] / baseline_stats["trades"] if baseline_stats["trades"] else ""
            )
            rows.append(row)
    return rows


def _decision_and_guardrails(
    *,
    candidates: Sequence[dict[str, Any]],
    filter_matrix: Sequence[dict[str, str]],
    live_context: Sequence[dict[str, str]],
    complete_coverage_threshold: float,
    min_live_trades: int,
    max_removal_share: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    del complete_coverage_threshold
    summary_rows: list[dict[str, str]] = []
    guardrail_rows: list[dict[str, str]] = []
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        filters = _candidate_filters(candidate)
        live_combined = _find(live_context, candidate_id=cid, live_scope="current_safe_diagnostics_packet", lane="COMBINED")
        live_ftmo = _find(live_context, candidate_id=cid, live_scope="current_safe_diagnostics_packet", lane="FTMO")
        live_ic = _find(live_context, candidate_id=cid, live_scope="current_safe_diagnostics_packet", lane="IC")
        window_rows = {window: _find(filter_matrix, candidate_id=cid, comparison_window=window, lane="COMBINED") for window, _, _ in WINDOWS}
        negative_windows: list[str] = []
        improving_windows: list[str] = []
        incomplete_windows: list[str] = []
        for window, row in window_rows.items():
            if row["coverage_status"] != "complete":
                incomplete_windows.append(window)
                continue
            if _float(row["candidate_subset_net_r"]) < 0:
                negative_windows.append(window)
            if _float(row["exclusion_delta_avg_r"]) > 0:
                improving_windows.append(window)
        live_both_negative = (
            _float(live_ftmo["candidate_live_net_r"]) < 0
            and _float(live_ic["candidate_live_net_r"]) < 0
            and _int(live_ftmo["candidate_live_trades"]) > 0
            and _int(live_ic["candidate_live_trades"]) > 0
        )
        combined_live_trades = _int(live_combined["candidate_live_trades"])
        removal_all = _float(window_rows["all"]["candidate_removal_share"])
        removal_12m = _float(window_rows["last_12m"]["candidate_removal_share"])
        recent_negative = sum(1 for window in ("last_3m", "last_6m", "last_12m") if window in negative_windows)
        recent_improves = sum(1 for window in ("last_3m", "last_6m", "last_12m") if window in improving_windows)
        guardrail_status = "complete" if not incomplete_windows else "incomplete_factor_coverage"
        if not live_both_negative:
            decision = "watch_or_reject_no_cross_lane_live_confluence"
            next_step = "keep as context only unless future eligible packets show cross-lane weakness"
        elif combined_live_trades < min_live_trades:
            decision = "watch_small_live_sample"
            next_step = "keep collecting; do not propose a filter"
        elif guardrail_status != "complete":
            decision = "data_gap_backtest_factor_coverage"
            next_step = "collect or derive sufficient backtest factor coverage before pass/fail; use as live diagnostic only"
        elif removal_all > max_removal_share:
            decision = "diagnostic_broad_not_filter_candidate"
            next_step = "use to find narrower intersections; simple exclusion too broad"
        elif (
            recent_negative >= 2
            and recent_improves >= 2
            and ("all" in negative_windows or _float(window_rows["all"]["exclusion_delta_avg_r"]) > 0)
            and removal_all <= max_removal_share
        ):
            decision = "active_research_candidate_backtest_supported"
            next_step = "run focused robustness and interaction review before proposal"
        elif recent_negative >= 1 and removal_all <= max_removal_share:
            decision = "investigate_live_vs_backtest_divergence"
            next_step = "compare live/backtest feature distribution and lane execution before filtering"
        else:
            decision = "reject_simple_exclusion_backtest_positive"
            next_step = "do not filter live; retain as diagnostic context"

        guardrail_rows.append(
            {
                "candidate_id": cid,
                "candidate_label": str(candidate["candidate_label"]),
                "live_cross_lane_confluence": str(live_both_negative).lower(),
                "live_sample_status": "candidate_sample" if combined_live_trades >= min_live_trades else "small_sample",
                "current_live_trades": _fmt(combined_live_trades),
                "required_filter_fields": ",".join(filters),
                "requires_candle_provenance": str(any(key in CANDLE_FIELDS for key in filters)).lower(),
                "backtest_guardrail_status": guardrail_status,
                "incomplete_guardrail_windows": ",".join(incomplete_windows),
                "backtest_all_field_coverage_share": window_rows["all"]["filter_field_coverage_share"],
                "backtest_12m_field_coverage_share": window_rows["last_12m"]["filter_field_coverage_share"],
                "backtest_6m_field_coverage_share": window_rows["last_6m"]["filter_field_coverage_share"],
                "backtest_3m_field_coverage_share": window_rows["last_3m"]["filter_field_coverage_share"],
                "removal_breadth_all": _fmt(removal_all),
                "removal_breadth_12m": _fmt(removal_12m),
                "removal_breadth_status": "too_broad" if removal_all > max_removal_share else "acceptable_or_contextual",
                "decision": decision,
                "decision_boundary": "research_only_not_live_approval",
            }
        )
        summary_rows.append(
            {
                "candidate_id": cid,
                "candidate_label": str(candidate["candidate_label"]),
                "candidate_type": str(candidate["candidate_type"]),
                "filters": _filter_text(filters),
                "live_ftmo_trades": live_ftmo["candidate_live_trades"],
                "live_ftmo_net_r": live_ftmo["candidate_live_net_r"],
                "live_ic_trades": live_ic["candidate_live_trades"],
                "live_ic_net_r": live_ic["candidate_live_net_r"],
                "current_live_trades": live_combined["candidate_live_trades"],
                "current_live_net_r": live_combined["candidate_live_net_r"],
                "backtest_last_3m_trades": window_rows["last_3m"]["candidate_subset_trades"],
                "backtest_last_3m_net_r": window_rows["last_3m"]["candidate_subset_net_r"],
                "backtest_last_6m_trades": window_rows["last_6m"]["candidate_subset_trades"],
                "backtest_last_6m_net_r": window_rows["last_6m"]["candidate_subset_net_r"],
                "backtest_last_12m_trades": window_rows["last_12m"]["candidate_subset_trades"],
                "backtest_last_12m_net_r": window_rows["last_12m"]["candidate_subset_net_r"],
                "backtest_all_trades": window_rows["all"]["candidate_subset_trades"],
                "backtest_all_net_r": window_rows["all"]["candidate_subset_net_r"],
                "backtest_guardrail_status": guardrail_status,
                "backtest_all_removal_share": window_rows["all"]["candidate_removal_share"],
                "backtest_12m_removal_share": window_rows["last_12m"]["candidate_removal_share"],
                "negative_windows": ",".join(negative_windows),
                "improving_exclusion_windows": ",".join(improving_windows),
                "decision": decision,
                "recommended_next_step": next_step,
                "decision_boundary": "research_only_not_live_approval",
            }
        )
    priority = {
        "active_research_candidate_backtest_supported": 0,
        "investigate_live_vs_backtest_divergence": 1,
        "data_gap_backtest_factor_coverage": 2,
        "diagnostic_broad_not_filter_candidate": 3,
        "watch_small_live_sample": 4,
        "reject_simple_exclusion_backtest_positive": 5,
        "watch_or_reject_no_cross_lane_live_confluence": 6,
    }
    summary_rows.sort(key=lambda row: (priority.get(row["decision"], 9), _float(row["current_live_net_r"])))
    guardrail_rows.sort(key=lambda row: (priority.get(row["decision"], 9), _int(row["current_live_trades"])))
    return summary_rows, guardrail_rows


def _overlap_rows(
    *,
    candidates: Sequence[dict[str, Any]],
    live_rows: Sequence[dict[str, str]],
    backtest_rows: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    sets = {
        "live_current_safe": live_rows,
        "backtest_all": backtest_rows,
        "backtest_last_12m": _filter_rows(backtest_rows, window_flag="recent_last_12m"),
        "backtest_last_6m": _filter_rows(backtest_rows, window_flag="recent_last_6m"),
        "backtest_last_3m": _filter_rows(backtest_rows, window_flag="recent_last_3m"),
    }
    rows: list[dict[str, str]] = []
    for evidence_set, source_rows in sets.items():
        for candidate_a, candidate_b in itertools.combinations(candidates, 2):
            filters_a = _candidate_filters(candidate_a)
            filters_b = _candidate_filters(candidate_b)
            a_rows = [row for row in source_rows if _matches(row, filters_a)]
            b_rows = [row for row in source_rows if _matches(row, filters_b)]
            overlap = [row for row in source_rows if _matches(row, filters_a) and _matches(row, filters_b)]
            overlap_stats = _metrics(overlap)
            if overlap_stats["trades"] == 0:
                continue
            a_stats = _metrics(a_rows)
            b_stats = _metrics(b_rows)
            rows.append(
                {
                    "evidence_set": evidence_set,
                    "candidate_a": str(candidate_a["candidate_id"]),
                    "candidate_b": str(candidate_b["candidate_id"]),
                    "a_label": str(candidate_a["candidate_label"]),
                    "b_label": str(candidate_b["candidate_label"]),
                    "a_trades": _fmt(a_stats["trades"]),
                    "a_net_r": _fmt(a_stats["net_r"]),
                    "b_trades": _fmt(b_stats["trades"]),
                    "b_net_r": _fmt(b_stats["net_r"]),
                    "overlap_trades": _fmt(overlap_stats["trades"]),
                    "overlap_net_r": _fmt(overlap_stats["net_r"]),
                    "overlap_avg_r": _fmt(overlap_stats["avg_r"]),
                    "overlap_share_of_a": _fmt(overlap_stats["trades"] / a_stats["trades"] if a_stats["trades"] else ""),
                    "overlap_share_of_b": _fmt(overlap_stats["trades"] / b_stats["trades"] if b_stats["trades"] else ""),
                }
            )
    return rows


def _candidate_filters(candidate: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    filters: dict[str, tuple[str, ...]] = {}
    for key, raw_value in dict(candidate["filters"]).items():
        if isinstance(raw_value, list):
            values = tuple(_norm(item) for item in raw_value if _norm(item))
        else:
            values = tuple(part.strip().lower() for part in str(raw_value).split("|") if part.strip())
        if not values:
            raise CandidateMatrixError(f"candidate {candidate['candidate_id']} has empty filter value for {key}")
        filters[str(key)] = values
    return filters


def _filter_text(filters: dict[str, tuple[str, ...]]) -> str:
    return ";".join(f"{key}={'|'.join(values)}" for key, values in filters.items())


def _filter_rows(
    rows: Sequence[dict[str, str]],
    *,
    lane: str = "COMBINED",
    window_flag: str | None = None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if lane != "COMBINED" and _norm(row.get("lane")) != _norm(lane):
            continue
        if window_flag and not _truthy(row.get(window_flag)):
            continue
        out.append(dict(row))
    return out


def _matches(row: dict[str, str], filters: dict[str, tuple[str, ...]]) -> bool:
    return all(_norm(row.get(key)) in values for key, values in filters.items())


def _has_all_filter_fields(row: dict[str, str], filters: dict[str, tuple[str, ...]]) -> bool:
    return all(_norm(row.get(key)) != "" for key in filters)


def _metrics(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    results = [_row_result(row) for row in rows]
    values = [value for value in results if value is not None]
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    net_r = sum(values)
    wins_r = sum(value for value in values if value > 0)
    losses_r = sum(value for value in values if value < 0)
    profit_factor: Any = ""
    if losses_r < 0:
        profit_factor = wins_r / abs(losses_r)
    elif wins_r > 0:
        profit_factor = "inf"
    pnl_values = [_row_pnl(row) for row in rows]
    return {
        "trades": len(values),
        "wins": wins,
        "losses": losses,
        "net_r": net_r,
        "avg_r": net_r / len(values) if values else "",
        "win_rate": wins / len(values) if values else "",
        "profit_factor": profit_factor,
        "broker_pnl": sum(value for value in pnl_values if value is not None) if any(value is not None for value in pnl_values) else "",
    }


def _metric_fields(prefix: str, stats: dict[str, Any]) -> dict[str, str]:
    return {
        f"{prefix}_trades": _fmt(stats["trades"]),
        f"{prefix}_wins": _fmt(stats["wins"]),
        f"{prefix}_losses": _fmt(stats["losses"]),
        f"{prefix}_net_r": _fmt(stats["net_r"]),
        f"{prefix}_avg_r": _fmt(stats["avg_r"]),
        f"{prefix}_win_rate": _fmt(stats["win_rate"]),
        f"{prefix}_profit_factor": _fmt(stats["profit_factor"]),
        f"{prefix}_broker_pnl": _fmt(stats["broker_pnl"]),
    }


def _interpret_window(
    candidate_stats: dict[str, Any],
    baseline_stats: dict[str, Any],
    after_stats: dict[str, Any],
    *,
    coverage_status: str,
) -> str:
    if coverage_status != "complete":
        return "coverage_incomplete_do_not_use_as_guardrail"
    if candidate_stats["trades"] == 0:
        return "candidate_absent"
    baseline_avg = baseline_stats["avg_r"] if baseline_stats["avg_r"] != "" else 0.0
    after_avg = after_stats["avg_r"] if after_stats["avg_r"] != "" else 0.0
    if candidate_stats["net_r"] < 0 and after_avg > baseline_avg:
        return "exclusion_improves_this_window"
    if candidate_stats["net_r"] < 0:
        return "candidate_negative_but_exclusion_not_improving_avg"
    return "exclusion_hurts_this_window"


def _row_result(row: dict[str, str]) -> float | None:
    for key in ("aggregate_r_result", "r_result", "net_r"):
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    return None


def _row_pnl(row: dict[str, str]) -> float | None:
    for key in ("aggregate_close_profit", "close_profit", "net_pnl"):
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    return None


def _find(rows: Sequence[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return dict(row)
    raise CandidateMatrixError(f"internal row lookup failed: {criteria}")


def _render_summary(
    *,
    diagnostics_dir: Path,
    factor_attribution_dir: Path | None,
    source_manifest: dict[str, Any],
    config_payload: dict[str, Any],
    decision_summary: Sequence[dict[str, str]],
) -> str:
    lines = [
        "# LPFS Candidate Backtest Matrix",
        "",
        "Scope: offline/read-only strategy research. No VPS, MT5, broker, config, runtime-state, journal, scheduler, risk, sizing, SL/TP, recovery, canary, reconciliation, or broker-send changes were made.",
        "",
        "## Inputs",
        "",
        f"- Trade diagnostics: `{diagnostics_dir}`",
    ]
    if factor_attribution_dir is not None:
        lines.append(f"- Factor attribution: `{factor_attribution_dir}`")
    lines.extend(
        [
            f"- Diagnostics manifest SHA-256: `{_sha256_file(diagnostics_dir / 'manifest.json')}`",
            "- Candidate config description: "
            + str(config_payload.get("description", "research-only candidate config")),
            "",
            "## Data Validity",
            "",
        ]
    )
    candle_sources = ((source_manifest.get("inputs") or {}).get("candle_sources") or [])
    if candle_sources:
        for source in candle_sources:
            lines.append(
                "- Candle source "
                + str(source.get("lane", "n/a"))
                + ": provenance `"
                + str(source.get("provenance", ""))
                + "`, safe `"
                + str(source.get("safe_for_strategy_analysis", ""))
                + "`."
            )
    else:
        lines.append("- No candle-source manifest entries were present.")
    lines.extend(
        [
            "- Rows with incomplete factor coverage are not proposal-grade guardrails.",
            "- Older workstation-candle packets remain quarantined for candle-derived strategy conclusions.",
            "",
            "## Decision Summary",
            "",
        ]
    )
    for row in decision_summary:
        lines.append(
            f"- `{row['candidate_id']}`: FTMO {row['live_ftmo_trades']} / {_fmt_signed(row['live_ftmo_net_r'])}R, "
            f"IC {row['live_ic_trades']} / {_fmt_signed(row['live_ic_net_r'])}R, "
            f"combined {row['current_live_trades']} / {_fmt_signed(row['current_live_net_r'])}R; "
            f"3M {row['backtest_last_3m_trades']} / {_fmt_signed(row['backtest_last_3m_net_r'])}R, "
            f"6M {row['backtest_last_6m_trades']} / {_fmt_signed(row['backtest_last_6m_net_r'])}R, "
            f"12M {row['backtest_last_12m_trades']} / {_fmt_signed(row['backtest_last_12m_net_r'])}R, "
            f"all {row['backtest_all_trades']} / {_fmt_signed(row['backtest_all_net_r'])}R; "
            f"guardrail `{row['backtest_guardrail_status']}`. Decision: `{row['decision']}`."
        )
    lines.extend(
        [
            "",
            "## Decision Boundary",
            "",
            "This matrix can trigger deeper offline research. It does not approve live strategy, risk, sizing, SL/TP, config, recovery, scheduler, VPS, or broker-send changes.",
            "",
        ]
    )
    return "\n".join(lines)


def _manifest(
    *,
    diagnostics_dir: Path,
    source_manifest: dict[str, Any],
    factor_attribution_dir: Path | None,
    factor_manifest: dict[str, Any] | None,
    candidate_config: Path,
    config_payload: dict[str, Any],
    as_of_utc: datetime,
    live_path: Path,
    backtest_path: Path,
    outputs: Sequence[Path],
    row_counts: dict[str, int],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "scope": "offline_read_only_strategy_research",
        "report": "lpfs_candidate_backtest_matrix",
        "generated_at_utc": as_of_utc.isoformat(),
        "source_diagnostics_dir": str(diagnostics_dir),
        "source_diagnostics_manifest_sha256": _sha256_file(diagnostics_dir / "manifest.json"),
        "source_diagnostics_manifest_scope": source_manifest.get("scope", ""),
        "candidate_config": _file_info(candidate_config),
        "candidate_config_description": config_payload.get("description", ""),
        "candidate_ids": [str(candidate["candidate_id"]) for candidate in config_payload["candidates"]],
        "inputs": [_file_info(live_path), _file_info(backtest_path)],
        "row_counts": row_counts,
        "data_validity": {
            "workstation_candle_packets_used": False,
            "older_workstation_candle_conclusions_quarantined": True,
            "long_history_candle_factor_guardrail_status": "not_claimed_when_filter_field_coverage_incomplete",
            "decision_boundary": "research_only_not_live_approval",
        },
        "non_actions": list(NON_ACTIONS),
        "outputs": [_file_info(path) for path in outputs],
    }
    if factor_attribution_dir is not None and factor_manifest is not None:
        payload["source_factor_attribution_dir"] = str(factor_attribution_dir)
        payload["source_factor_attribution_manifest_sha256"] = _sha256_file(factor_attribution_dir / "manifest.json")
        payload["source_factor_attribution_manifest_scope"] = factor_manifest.get("scope", "")
    return payload


def _file_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    exists = path.exists()
    info: dict[str, Any] = {"path": str(path), "exists": exists}
    if exists and path.is_file():
        info.update({"size_bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    return info


def _write_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truthy(value: Any) -> bool:
    return _norm(value) in {"1", "true", "yes", "y"}


def _norm(value: Any) -> str:
    return str(value if value is not None else "").strip().lower()


def _optional_float(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _float(value: Any) -> float:
    parsed = _optional_float(value)
    return 0.0 if parsed is None else parsed


def _int(value: Any) -> int:
    parsed = _optional_float(value)
    return 0 if parsed is None else int(parsed)


def _fmt(value: Any) -> str:
    if value == "" or value is None:
        return ""
    if value == "inf":
        return "inf"
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_signed(value: Any) -> str:
    parsed = _optional_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:+.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
