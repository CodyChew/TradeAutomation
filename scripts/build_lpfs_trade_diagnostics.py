"""Build LPFS closed-trade diagnostic reports from operator-supplied local rows.

The script is local/reporting-only. It accepts archived, synthetic, or safely
collected local journal copies with --journal. Never pass an active VPS runtime
journal path directly.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab.live_trade_summary import (  # noqa: E402
    closed_trade_diagnostic_rows,
    load_live_journal_events,
)


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_trade_diagnostics"
DEFAULT_FTMO_TRADES = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_account_commission_sensitivity"
    / "20260505_165121"
    / "ftmo_baseline_commission_adjusted_trades.csv"
)
DEFAULT_IC_TRADES = (
    REPO_ROOT
    / "reports"
    / "strategies"
    / "lp_force_strike_account_commission_sensitivity"
    / "20260505_165121"
    / "ic_markets_raw_spread_commission_adjusted_trades.csv"
)
SAFE_CANDLE_PROVENANCE = frozenset({"vps_lane_broker_feed", "backtest_reference", "synthetic_fixture"})
KNOWN_CANDLE_PROVENANCE = SAFE_CANDLE_PROVENANCE | {"local_unverified"}
LANE_BROKER_SERVER_EXPECTATIONS = {
    "FTMO": {"server": "FTMO-Server", "company_contains": "FTMO"},
    "IC": {"server": "ICMarketsSC-MT5-2", "company_contains": "Raw Trading"},
}


class CandleSource:
    def __init__(
        self,
        *,
        lane: str,
        path: Path,
        provenance: str,
        validation_status: str,
        validation_error: str = "",
    ) -> None:
        self.lane = lane
        self.path = path
        self.provenance = provenance
        self.validation_status = validation_status
        self.validation_error = validation_error

    @property
    def safe_for_strategy_analysis(self) -> bool:
        return self.provenance in SAFE_CANDLE_PROVENANCE and self.validation_status in {
            "validated",
            "not_required_for_synthetic_fixture",
            "not_required_for_backtest_reference",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal",
        action="append",
        default=[],
        help="Local journal path, or LANE=path. Repeat for multiple lanes.",
    )
    parser.add_argument(
        "--benchmark-trades",
        action="append",
        default=[],
        help="Optional backtest trades CSV, or LANE=path. Repeat for multiple lanes.",
    )
    parser.add_argument(
        "--candle-root",
        action="append",
        default=[],
        help=(
            "Optional explicit candle data root for offline indicator enrichment as LANE=path. "
            "Requires matching --candle-source-provenance LANE=..."
        ),
    )
    parser.add_argument(
        "--candle-source-provenance",
        action="append",
        default=[],
        help=(
            "Candle source provenance as LANE=vps_lane_broker_feed, "
            "LANE=backtest_reference, LANE=synthetic_fixture, or LANE=local_unverified. "
            "Unverified sources are recorded but blocked from strategy-analysis enrichment."
        ),
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument(
        "--exclude-window",
        action="append",
        default=[],
        help=(
            "Exclude live rows from strategy analysis for an operationally distorted UTC window. "
            "Use REASON=start,end or start,end. Rows are preserved with exclusion fields."
        ),
    )
    args = parser.parse_args()

    if not args.journal:
        parser.error("provide at least one --journal")

    as_of = pd.Timestamp(args.as_of_utc) if args.as_of_utc else pd.Timestamp.now(tz="UTC")
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    output_dir = Path(args.output_root) / as_of.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        candle_sources = _candle_sources(args.candle_root, args.candle_source_provenance)
    except ValueError as exc:
        parser.error(str(exc))
    exclusion_windows = _parse_exclusion_windows(args.exclude_window)

    live_rows: list[dict[str, Any]] = []
    journal_specs: list[tuple[str, Path]] = []
    for raw in args.journal:
        lane, path = _split_label(raw)
        journal_specs.append((lane or Path(path).stem, Path(path)))
        events = load_live_journal_events(path)
        live_rows.extend(closed_trade_diagnostic_rows(events, lane=lane or Path(path).stem))
    live_rows = _enrich_rows(live_rows, as_of_utc=as_of, candle_sources=candle_sources)
    _apply_exclusion_windows(live_rows, exclusion_windows)

    benchmark_specs = args.benchmark_trades or [
        f"FTMO={DEFAULT_FTMO_TRADES}",
        f"IC={DEFAULT_IC_TRADES}",
    ]
    benchmark_rows: list[dict[str, Any]] = []
    benchmark_file_specs: list[tuple[str, Path]] = []
    for raw in benchmark_specs:
        lane, path = _split_label(raw)
        path_obj = Path(path)
        benchmark_file_specs.append((lane or path_obj.stem, path_obj))
        if path_obj.exists():
            benchmark_rows.extend(_load_backtest_rows(path_obj, lane=lane or path_obj.stem))
    benchmark_rows = _enrich_rows(benchmark_rows, as_of_utc=as_of, candle_sources=candle_sources)

    diagnostic_csv = output_dir / "closed_trade_diagnostics.csv"
    benchmark_csv = output_dir / "backtest_diagnostics.csv"
    comparison_csv = output_dir / "backtest_comparison.csv"
    confluence_csv = output_dir / "timeframe_confluence.csv"
    candidates_csv = output_dir / "research_candidates.csv"
    summary_md = output_dir / "summary.md"
    manifest_json = output_dir / "manifest.json"
    _write_csv(diagnostic_csv, live_rows)
    _write_csv(benchmark_csv, benchmark_rows)
    comparison_rows = _comparison_rows(live_rows, benchmark_rows)
    _write_csv(comparison_csv, comparison_rows)
    confluence_rows = _timeframe_confluence_rows(live_rows, benchmark_rows)
    _write_csv(confluence_csv, confluence_rows)
    candidate_rows = _research_candidate_rows(live_rows, benchmark_rows)
    _write_csv(candidates_csv, candidate_rows)
    summary_md.write_text(_render_summary(live_rows, comparison_rows, confluence_rows, candidate_rows, as_of), encoding="utf-8")
    manifest_json.write_text(
        json.dumps(
            _manifest(
                as_of_utc=as_of,
                output_dir=output_dir,
                journal_specs=journal_specs,
                benchmark_specs=benchmark_file_specs,
                candle_sources=candle_sources,
                exclusion_windows=exclusion_windows,
                outputs=[diagnostic_csv, benchmark_csv, comparison_csv, confluence_csv, candidates_csv, summary_md],
                live_rows=live_rows,
                benchmark_rows=benchmark_rows,
                candidate_rows=candidate_rows,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"trade_diagnostics_report={output_dir}")
    print(f"closed_trade_diagnostics={diagnostic_csv}")
    print(f"backtest_diagnostics={benchmark_csv}")
    print(f"backtest_comparison={comparison_csv}")
    print(f"timeframe_confluence={confluence_csv}")
    print(f"research_candidates={candidates_csv}")
    print(f"summary={summary_md}")
    print(f"manifest={manifest_json}")
    return 0


def _split_label(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        return "", raw
    label, value = raw.split("=", 1)
    return label.strip(), value.strip()


def _parse_exclusion_windows(raw_windows: Sequence[str]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for raw in raw_windows:
        reason, value = _split_label(raw)
        if not value:
            value = reason
            reason = "operator_excluded_window"
        parts = [part.strip() for part in value.split(",", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid --exclude-window {raw!r}; expected REASON=start,end or start,end.")
        start = _required_utc_timestamp(parts[0], label="exclude window start")
        end = _required_utc_timestamp(parts[1], label="exclude window end")
        if end <= start:
            raise ValueError(f"Invalid --exclude-window {raw!r}; end must be after start.")
        windows.append(
            {
                "reason": reason or "operator_excluded_window",
                "start_utc": start,
                "end_utc": end,
            }
        )
    return windows


def _required_utc_timestamp(value: str, *, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except Exception as exc:
        raise ValueError(f"Invalid {label}: {value!r}.") from exc
    if pd.isna(timestamp):
        raise ValueError(f"Invalid {label}: {value!r}.")
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _apply_exclusion_windows(rows: Sequence[dict[str, Any]], windows: Sequence[dict[str, Any]]) -> None:
    for row in rows:
        row["excluded_from_strategy_analysis"] = False
        result_time = _result_timestamp(row)
        if result_time is None:
            continue
        for window in windows:
            start = window["start_utc"]
            end = window["end_utc"]
            if start <= result_time < end:
                row["excluded_from_strategy_analysis"] = True
                row["strategy_analysis_exclusion_reason"] = window["reason"]
                row["strategy_analysis_exclusion_start_utc"] = start.isoformat()
                row["strategy_analysis_exclusion_end_utc"] = end.isoformat()
                break


def _candle_sources(raw_roots: Sequence[str], raw_provenance: Sequence[str]) -> dict[str, CandleSource]:
    provenance_by_lane: dict[str, str] = {}
    for raw in raw_provenance:
        lane, provenance = _split_label(raw)
        if not lane or not provenance:
            raise ValueError("--candle-source-provenance must use LANE=provenance")
        lane_key = _lane_key(lane)
        normalized = provenance.strip().lower()
        if normalized not in KNOWN_CANDLE_PROVENANCE:
            allowed = ", ".join(sorted(KNOWN_CANDLE_PROVENANCE))
            raise ValueError(f"Unknown candle source provenance {provenance!r}; expected one of: {allowed}.")
        provenance_by_lane[lane_key] = normalized

    roots: dict[str, CandleSource] = {}
    for raw in raw_roots:
        lane, path = _split_label(raw)
        if not lane:
            raise ValueError("--candle-root must use LANE=path so candle provenance is lane-explicit")
        key = _lane_key(lane)
        provenance = provenance_by_lane.get(key)
        if provenance is None:
            raise ValueError(f"--candle-root {lane}=... requires --candle-source-provenance {lane}=...")
        path_obj = Path(path)
        validation_status, validation_error = _validate_candle_source_metadata(
            lane=key,
            path=path_obj,
            provenance=provenance,
        )
        roots[key] = CandleSource(
            lane=key,
            path=path_obj,
            provenance=provenance,
            validation_status=validation_status,
            validation_error=validation_error,
        )
    return roots


def _validate_candle_source_metadata(*, lane: str, path: Path, provenance: str) -> tuple[str, str]:
    if provenance == "synthetic_fixture":
        return "not_required_for_synthetic_fixture", ""
    if provenance == "backtest_reference":
        return "not_required_for_backtest_reference", ""
    if provenance != "vps_lane_broker_feed":
        return "unverified", "candle source provenance is not lane-authoritative"
    expectation = LANE_BROKER_SERVER_EXPECTATIONS.get(_lane_key(lane))
    if expectation is None:
        return "failed", f"no broker metadata expectation configured for lane {lane!r}"
    manifests = sorted(path.glob("*/*/manifest.json"))
    if not manifests:
        return "failed", "no candle manifest files found for broker-source validation"
    for manifest_path in manifests[:20]:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return "failed", f"could not parse candle manifest {manifest_path}: {exc}"
        account = payload.get("account_metadata") or {}
        terminal = payload.get("terminal_metadata") or {}
        server = str(account.get("server") or "")
        company_text = " ".join(str(value or "") for value in (account.get("company"), terminal.get("company"), terminal.get("name")))
        if server != expectation["server"]:
            return "failed", f"{manifest_path} server {server!r} does not match expected {expectation['server']!r}"
        if expectation["company_contains"] not in company_text:
            return "failed", f"{manifest_path} company metadata does not contain {expectation['company_contains']!r}"
    return "validated", ""


def _load_backtest_rows(path: Path, *, lane: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            signal_index = _first_float(raw.get("signal_index"))
            entry_index = _first_float(raw.get("entry_index"))
            rows.append(
                {
                    "lane": lane,
                    "setup_id": raw.get("setup_id"),
                    "symbol": str(raw.get("symbol") or "").upper(),
                    "timeframe": str(raw.get("timeframe") or "").upper(),
                    "side": str(raw.get("side") or "").upper(),
                    "signal_index": signal_index,
                    "entry_index": entry_index,
                    "exit_index": _first_float(raw.get("exit_index")),
                    "r_result": _first_float(
                        raw.get("commission_adjusted_net_r"),
                        raw.get("net_r"),
                        raw.get("fill_r"),
                        raw.get("reference_r"),
                    ),
                    "entry_time_utc": raw.get("entry_time_utc"),
                    "exit_time_utc": raw.get("exit_time_utc"),
                    "entry_price": _first_float(raw.get("entry_fill_price"), raw.get("entry_reference_price")),
                    "exit_price": _first_float(raw.get("exit_fill_price"), raw.get("exit_reference_price")),
                    "stop_price": _first_float(raw.get("stop_price")),
                    "target_price": _first_float(raw.get("target_price")),
                    "risk_distance": _first_float(raw.get("risk_distance")),
                    "bars_held": _first_float(raw.get("bars_held")),
                    "exit_reason": raw.get("exit_reason"),
                    "candidate_id": raw.get("candidate_id") or raw.get("meta_candidate_id"),
                    "entry_model": raw.get("meta_entry_model"),
                    "entry_wait_mode": raw.get("meta_entry_wait_mode"),
                    "entry_zone": _first_float(raw.get("meta_entry_zone")),
                    "stop_model": raw.get("meta_stop_model"),
                    "exit_model": raw.get("meta_exit_model"),
                    "target_r": _first_float(raw.get("meta_target_r")),
                    "lp_price": _first_float(raw.get("meta_lp_price")),
                    "lp_break_index": _first_float(raw.get("meta_lp_break_index")),
                    "lp_break_time_utc": raw.get("meta_lp_break_time_utc"),
                    "fs_mother_index": _first_float(raw.get("meta_fs_mother_index")),
                    "fs_signal_index": _first_float(raw.get("meta_fs_signal_index")),
                    "fs_signal_time_utc": raw.get("meta_fs_signal_time_utc"),
                    "fs_total_bars": _first_float(raw.get("meta_fs_total_bars")),
                    "bars_from_lp_break": _first_float(raw.get("meta_bars_from_lp_break"), raw.get("bars_from_lp_break")),
                    "structure_low": _first_float(raw.get("meta_structure_low")),
                    "structure_high": _first_float(raw.get("meta_structure_high")),
                    "atr": _first_float(raw.get("meta_atr")),
                    "risk_atr": _first_float(raw.get("meta_risk_atr"), raw.get("risk_atr")),
                    "pivot_strength": _first_float(raw.get("pivot_strength")),
                    "trade_key": raw.get("trade_key"),
                    "signal_join_key": raw.get("signal_join_key"),
                    "setup_age_bars": _delta_number(entry_index, signal_index),
                }
            )
    return rows


def _enrich_rows(
    rows: Sequence[dict[str, Any]],
    *,
    as_of_utc: pd.Timestamp,
    candle_sources: dict[str, CandleSource],
) -> list[dict[str, Any]]:
    cache = _CandleFeatureCache(candle_sources)
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        _add_time_features(enriched, as_of_utc=as_of_utc)
        _add_setup_buckets(enriched)
        _add_execution_buckets(enriched)
        features = cache.lookup(
            lane=str(enriched.get("lane") or ""),
            symbol=str(enriched.get("symbol") or ""),
            timeframe=str(enriched.get("timeframe") or ""),
            timestamp=_analysis_timestamp(enriched),
        )
        enriched.update(features)
        enriched_rows.append(enriched)
    return enriched_rows


def _add_time_features(row: dict[str, Any], *, as_of_utc: pd.Timestamp) -> None:
    analysis_time = _analysis_timestamp(row)
    result_time = _result_timestamp(row)
    if analysis_time is not None:
        row["analysis_time_utc"] = analysis_time.isoformat()
        row["analysis_hour_utc"] = int(analysis_time.hour)
        row["analysis_weekday_utc"] = analysis_time.day_name()
        row["analysis_session_utc"] = _session_utc(analysis_time.hour)
    if result_time is not None:
        row["result_time_utc"] = result_time.isoformat()
        row["result_weekday_utc"] = result_time.day_name()
        for label, days in (("last_3m", 90), ("last_6m", 180), ("last_12m", 365)):
            row[f"recent_{label}"] = result_time >= as_of_utc - pd.Timedelta(days=days)
        row["recent_window_bucket"] = _recent_window_bucket(result_time, as_of_utc=as_of_utc)
    row["timeframe_frequency_class"] = _timeframe_frequency_class(str(row.get("timeframe") or ""))


def _analysis_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    return _first_timestamp(
        row.get("diagnostic_backtest_join_signal_time_utc"),
        row.get("diagnostic_setup_fs_signal_time_utc"),
        row.get("fs_signal_time_utc"),
        row.get("entry_time_utc"),
        row.get("opened_utc"),
        row.get("closed_utc"),
    )


def _result_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    return _first_timestamp(row.get("closed_utc"), row.get("exit_time_utc"), row.get("opened_utc"), row.get("entry_time_utc"))


def _session_utc(hour: int) -> str:
    if 0 <= hour < 7:
        return "asia_utc"
    if 7 <= hour < 12:
        return "london_utc"
    if 12 <= hour < 21:
        return "new_york_utc"
    return "rollover_utc"


def _recent_window_bucket(result_time: pd.Timestamp, *, as_of_utc: pd.Timestamp) -> str:
    age_days = (as_of_utc - result_time) / pd.Timedelta(days=1)
    if age_days <= 90:
        return "last_3m"
    if age_days <= 180:
        return "last_6m"
    if age_days <= 365:
        return "last_12m"
    return "older"


def _add_setup_buckets(row: dict[str, Any]) -> None:
    risk_atr = _first_float(row.get("diagnostic_setup_risk_atr"), row.get("risk_atr"))
    bars_from_lp_break = _first_float(row.get("diagnostic_setup_bars_from_lp_break"), row.get("bars_from_lp_break"))
    setup_age = _first_float(
        row.get("setup_age_bars"),
        _delta_number(row.get("diagnostic_setup_entry_index"), row.get("diagnostic_setup_signal_index")),
        _delta_number(row.get("entry_index"), row.get("signal_index")),
    )
    fs_total_bars = _first_float(row.get("diagnostic_setup_fs_total_bars"), row.get("fs_total_bars"))
    row["risk_atr_bucket"] = _risk_atr_bucket(risk_atr)
    row["bars_from_lp_break_bucket"] = _small_count_bucket(bars_from_lp_break, single_until=3, mid_label="4_to_6")
    row["setup_age_bars"] = setup_age
    row["setup_age_bars_bucket"] = _small_count_bucket(setup_age, single_until=1, mid_label="2_to_6")
    row["fs_total_bars_bucket"] = _small_count_bucket(fs_total_bars, single_until=2, mid_label="3_to_4")


def _add_execution_buckets(row: dict[str, Any]) -> None:
    spread_risk = _first_float(row.get("diagnostic_spread_gate_spread_risk_fraction"))
    row["spread_risk_bucket"] = _spread_risk_bucket(spread_risk)
    row["execution_path"] = _first_text(
        row.get("diagnostic_execution_execution_path"),
        row.get("diagnostic_execution_recovery_path"),
        row.get("diagnostic_execution_stage"),
    )
    row["exit_or_close_reason"] = _first_text(row.get("exit_reason"), row.get("diagnostic_execution_close_reason"), row.get("close_kind"))


def _comparison_rows(live_rows: Sequence[dict[str, Any]], benchmark_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_sets = [
        ("lane",),
        ("lane", "timeframe"),
        ("lane", "symbol"),
        ("lane", "side"),
        ("lane", "symbol", "timeframe"),
        ("lane", "timeframe", "side"),
        ("lane", "analysis_session_utc"),
        ("lane", "analysis_weekday_utc"),
        ("lane", "timeframe", "analysis_session_utc"),
        ("lane", "timeframe", "risk_atr_bucket"),
        ("lane", "timeframe", "bars_from_lp_break_bucket"),
        ("lane", "timeframe", "setup_age_bars_bucket"),
        ("lane", "timeframe", "fs_total_bars_bucket"),
        ("lane", "timeframe", "candle_atr_regime_252"),
        ("lane", "timeframe", "candle_rsi_regime"),
        ("lane", "timeframe", "candle_momentum_3_regime"),
        ("lane", "timeframe", "candle_macd_histogram_regime"),
        ("lane", "timeframe", "candle_close_vs_ema_20"),
        ("lane", "timeframe", "candle_ema_20_slope_regime"),
        ("lane", "timeframe", "candle_tick_volume_regime_252"),
        ("lane", "timeframe", "candle_spread_regime_252"),
        ("lane", "timeframe", "spread_risk_bucket"),
        ("lane", "timeframe", "execution_path"),
    ]
    for window in ("all", "last_3m", "last_6m", "last_12m"):
        live_window = _filter_recent_window(live_rows, window)
        benchmark_window = _filter_recent_window(benchmark_rows, window)
        for group_by in group_sets:
            live_groups = _group_result_stats(live_window, group_by)
            benchmark_groups = _group_result_stats(benchmark_window, group_by)
            keys = sorted(set(live_groups) | set(benchmark_groups))
            for key in keys:
                live = live_groups.get(key, {})
                benchmark = benchmark_groups.get(key, {})
                row = {"comparison_window": window, "group_by": "|".join(group_by)}
                row.update({column: value for column, value in zip(group_by, key)})
                row.update(_prefix("live", live))
                row.update(_prefix("backtest", benchmark))
                row["avg_r_delta_live_minus_backtest"] = _delta(live.get("avg_r"), benchmark.get("avg_r"))
                rows.append(row)
    return rows


def _research_candidate_rows(live_rows: Sequence[dict[str, Any]], benchmark_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group_sets = [
        ("timeframe",),
        ("symbol",),
        ("side",),
        ("symbol", "timeframe"),
        ("timeframe", "side"),
        ("symbol", "side"),
        ("symbol", "timeframe", "side"),
        ("timeframe", "analysis_session_utc"),
        ("timeframe", "analysis_weekday_utc"),
        ("timeframe", "risk_atr_bucket"),
        ("timeframe", "bars_from_lp_break_bucket"),
        ("timeframe", "setup_age_bars_bucket"),
        ("timeframe", "candle_rsi_regime"),
        ("timeframe", "candle_momentum_3_regime"),
        ("timeframe", "candle_macd_histogram_regime"),
        ("timeframe", "candle_close_vs_ema_20"),
        ("timeframe", "candle_ema_20_slope_regime"),
        ("timeframe", "candle_atr_regime_252"),
        ("timeframe", "candle_tick_volume_regime_252"),
        ("timeframe", "candle_spread_regime_252"),
    ]
    for window in ("all", "last_3m", "last_6m", "last_12m"):
        live_window = _filter_recent_window(live_rows, window)
        benchmark_window = _filter_recent_window(benchmark_rows, window)
        for group_by in group_sets:
            keys = sorted({_group_key(row, group_by) for row in live_window if _complete_group_key(row, group_by)})
            for key in keys:
                ftmo_live = _stats_for_key(live_window, group_by, key, lane="FTMO")
                ic_live = _stats_for_key(live_window, group_by, key, lane="IC")
                combined_live = _stats_for_key(live_window, group_by, key, lane=None)
                benchmark = _stats_for_key(benchmark_window, group_by, key, lane=None)
                if not combined_live:
                    continue
                row: dict[str, Any] = {
                    "comparison_window": window,
                    "group_by": "|".join(group_by),
                }
                row.update({column: value for column, value in zip(group_by, key)})
                row.update(_prefix("ftmo_live", ftmo_live))
                row.update(_prefix("ic_live", ic_live))
                row.update(_prefix("combined_live", combined_live))
                row.update(_prefix("backtest", benchmark))
                row["ftmo_avg_r_delta_live_minus_backtest"] = _delta(ftmo_live.get("avg_r"), benchmark.get("avg_r"))
                row["ic_avg_r_delta_live_minus_backtest"] = _delta(ic_live.get("avg_r"), benchmark.get("avg_r"))
                row["combined_avg_r_delta_live_minus_backtest"] = _delta(combined_live.get("avg_r"), benchmark.get("avg_r"))
                row["evidence_min_investigate_trades"] = _min_investigate_trades(str(row.get("timeframe") or ""))
                row["evidence_min_candidate_trades"] = _min_candidate_trades(str(row.get("timeframe") or ""))
                row["lane_confluence_status"] = _lane_confluence_status(ftmo_live, ic_live)
                row["research_priority"] = _candidate_research_priority(row)
                row["candidate_direction"] = _candidate_direction(row)
                rows.append(row)
    return sorted(rows, key=_candidate_sort_key)


def _group_result_stats(rows: Sequence[dict[str, Any]], group_by: Sequence[str]) -> dict[tuple[Any, ...], dict[str, Any]]:
    values_by_key: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = _first_float(row.get("r_result"))
        if value is None:
            continue
        key = tuple(str(row.get(column) or "").upper() for column in group_by)
        if any(part == "" for part in key):
            continue
        values_by_key[key].append(value)
    stats: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, values in values_by_key.items():
        wins = sum(1 for value in values if value > 0)
        losses = sum(1 for value in values if value < 0)
        gross_win = sum(value for value in values if value > 0)
        gross_loss = abs(sum(value for value in values if value < 0))
        stats[key] = {
            "trades": len(values),
            "net_r": sum(values),
            "avg_r": sum(values) / len(values),
            "median_r": _percentile(values, 0.50),
            "p25_r": _percentile(values, 0.25),
            "p75_r": _percentile(values, 0.75),
            "win_rate": wins / len(values) if values else None,
            "losses": losses,
            "profit_factor": None if gross_loss <= 0 else gross_win / gross_loss,
        }
    return stats


def _filter_recent_window(rows: Sequence[dict[str, Any]], window: str) -> list[dict[str, Any]]:
    rows = [row for row in rows if row.get("excluded_from_strategy_analysis") is not True]
    if window == "all":
        return list(rows)
    return [row for row in rows if row.get(f"recent_{window}") is True]


def _timeframe_confluence_rows(
    live_rows: Sequence[dict[str, Any]],
    benchmark_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    timeframes = sorted(
        {str(row.get("timeframe") or "").upper() for row in [*live_rows, *benchmark_rows] if row.get("timeframe")},
        key=_timeframe_sort_key,
    )
    lanes = ("FTMO", "IC")
    for window in ("all", "last_3m", "last_6m", "last_12m"):
        live_window = _filter_recent_window(live_rows, window)
        benchmark_window = _filter_recent_window(benchmark_rows, window)
        for timeframe in timeframes:
            row: dict[str, Any] = {
                "comparison_window": window,
                "timeframe": timeframe,
                "timeframe_frequency_class": _timeframe_frequency_class(timeframe),
            }
            deltas: list[float] = []
            populated_lanes = 0
            for lane in lanes:
                live_stats = _single_group_stats(
                    live_window,
                    lambda item, lane=lane, timeframe=timeframe: _lane_key(item.get("lane")) == lane
                    and str(item.get("timeframe") or "").upper() == timeframe,
                )
                backtest_stats = _single_group_stats(
                    benchmark_window,
                    lambda item, lane=lane, timeframe=timeframe: _lane_key(item.get("lane")) == lane
                    and str(item.get("timeframe") or "").upper() == timeframe,
                )
                prefix = lane.lower()
                row.update(_prefix(f"{prefix}_live", live_stats))
                row.update(_prefix(f"{prefix}_backtest", backtest_stats))
                delta = _delta(live_stats.get("avg_r"), backtest_stats.get("avg_r"))
                row[f"{prefix}_avg_r_delta_live_minus_backtest"] = delta
                if live_stats.get("trades"):
                    populated_lanes += 1
                if delta is not None:
                    deltas.append(delta)
            row["combined_live_trades"] = _sum_int(row.get("ftmo_live_trades"), row.get("ic_live_trades"))
            row["combined_backtest_trades"] = _sum_int(row.get("ftmo_backtest_trades"), row.get("ic_backtest_trades"))
            row["evidence_min_investigate_trades"] = _min_investigate_trades(timeframe)
            row["evidence_min_candidate_trades"] = _min_candidate_trades(timeframe)
            row["confluence_status"] = _confluence_status(deltas, populated_lanes)
            row["research_action"] = _research_action(row)
            rows.append(row)
    return rows


def _single_group_stats(rows: Sequence[dict[str, Any]], predicate: Any) -> dict[str, Any]:
    values = [_first_float(row.get("r_result")) for row in rows if predicate(row)]
    return _stats([value for value in values if value is not None])


def _stats_for_key(
    rows: Sequence[dict[str, Any]],
    group_by: Sequence[str],
    key: tuple[Any, ...],
    *,
    lane: str | None,
) -> dict[str, Any]:
    return _single_group_stats(
        rows,
        lambda item, group_by=group_by, key=key, lane=lane: _group_key(item, group_by) == key
        and (lane is None or _lane_key(item.get("lane")) == lane),
    )


def _group_key(row: dict[str, Any], group_by: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "").upper() for column in group_by)


def _complete_group_key(row: dict[str, Any], group_by: Sequence[str]) -> bool:
    key = _group_key(row, group_by)
    return bool(key) and all(part != "" for part in key)


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {}
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    gross_win = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    return {
        "trades": len(values),
        "net_r": sum(values),
        "avg_r": sum(values) / len(values),
        "median_r": _percentile(values, 0.50),
        "win_rate": wins / len(values),
        "losses": losses,
        "profit_factor": None if gross_loss <= 0 else gross_win / gross_loss,
    }


def _lane_confluence_status(ftmo: dict[str, Any], ic: dict[str, Any]) -> str:
    ftmo_trades = int(_first_float(ftmo.get("trades")) or 0)
    ic_trades = int(_first_float(ic.get("trades")) or 0)
    if ftmo_trades <= 0 or ic_trades <= 0:
        return "single_lane_or_missing_live_data"
    ftmo_avg = _first_float(ftmo.get("avg_r"))
    ic_avg = _first_float(ic.get("avg_r"))
    if ftmo_avg is None or ic_avg is None:
        return "insufficient_live_result_data"
    if ftmo_avg < 0 and ic_avg < 0:
        return "both_lanes_weak"
    if ftmo_avg > 0 and ic_avg > 0:
        return "both_lanes_strong"
    return "mixed_lanes"


def _candidate_research_priority(row: dict[str, Any]) -> str:
    live_trades = int(_first_float(row.get("combined_live_trades")) or 0)
    min_investigate = int(_first_float(row.get("evidence_min_investigate_trades")) or 0)
    min_candidate = int(_first_float(row.get("evidence_min_candidate_trades")) or 0)
    confluence = str(row.get("lane_confluence_status") or "")
    combined_avg = _first_float(row.get("combined_live_avg_r"))
    if live_trades <= 0 or combined_avg is None:
        return "no_live_evidence"
    if confluence == "both_lanes_weak":
        if live_trades >= min_candidate:
            return "candidate_backtest_required"
        if live_trades >= min_investigate:
            return "investigate_not_deployable"
        return "watch_sample_too_small"
    if combined_avg < 0 and confluence in {"single_lane_or_missing_live_data", "mixed_lanes"}:
        return "broker_lane_attribution"
    if confluence == "both_lanes_strong":
        return "protect_or_constructive_reference"
    return "monitor"


def _candidate_direction(row: dict[str, Any]) -> str:
    combined_avg = _first_float(row.get("combined_live_avg_r"))
    if combined_avg is None:
        return ""
    if combined_avg < 0:
        return "defensive_filter_candidate"
    if combined_avg > 0:
        return "protect_or_scale_reference"
    return "neutral"


def _candidate_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
    priority_order = {
        "candidate_backtest_required": 0,
        "investigate_not_deployable": 1,
        "broker_lane_attribution": 2,
        "watch_sample_too_small": 3,
        "monitor": 4,
        "protect_or_constructive_reference": 5,
    }
    priority = priority_order.get(str(row.get("research_priority") or ""), 9)
    net_r = _first_float(row.get("combined_live_net_r")) or 0.0
    trades = int(_first_float(row.get("combined_live_trades")) or 0)
    label = "|".join(str(row.get(column) or "") for column in str(row.get("group_by") or "").split("|"))
    return (priority, net_r, -trades, label)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _manifest(
    *,
    as_of_utc: pd.Timestamp,
    output_dir: Path,
    journal_specs: Sequence[tuple[str, Path]],
    benchmark_specs: Sequence[tuple[str, Path]],
    candle_sources: dict[str, CandleSource],
    exclusion_windows: Sequence[dict[str, Any]],
    outputs: Sequence[Path],
    live_rows: Sequence[dict[str, Any]],
    benchmark_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "report": "lpfs_trade_diagnostics",
        "generated_at_utc": as_of_utc.isoformat(),
        "output_dir": str(output_dir),
        "scope": "offline_read_only_strategy_attribution",
        "non_actions": [
            "no_live_runner_change",
            "no_vps_access",
            "no_mt5_access",
            "no_broker_mutation",
            "no_strategy_logic_change",
            "no_risk_sizing_sl_tp_change",
            "no_config_change",
        ],
        "inputs": {
            "journals": [_labeled_fingerprint(label, path) for label, path in journal_specs],
            "benchmark_trades": [_labeled_fingerprint(label, path) for label, path in benchmark_specs],
            "candle_sources": [
                {
                    "lane": lane,
                    "path": str(source.path),
                    "exists": source.path.exists(),
                    "type": "directory",
                    "provenance": source.provenance,
                    "validation_status": source.validation_status,
                    "validation_error": source.validation_error,
                    "safe_for_strategy_analysis": source.safe_for_strategy_analysis,
                }
                for lane, source in sorted(candle_sources.items())
            ],
        },
        "exclusion_windows": [
            {
                "reason": str(window["reason"]),
                "start_utc": window["start_utc"].isoformat(),
                "end_utc": window["end_utc"].isoformat(),
            }
            for window in exclusion_windows
        ],
        "row_counts": {
            "closed_trade_diagnostics": len(live_rows),
            "closed_trade_diagnostics_excluded_from_strategy_analysis": sum(
                1 for row in live_rows if row.get("excluded_from_strategy_analysis") is True
            ),
            "closed_trade_diagnostics_with_candle_enrichment": sum(1 for row in live_rows if row.get("candle_time_utc")),
            "closed_trade_diagnostics_with_blocked_candle_enrichment": sum(
                1
                for row in live_rows
                if row.get("candle_enrichment_status")
                in {"blocked_unverified_candle_source", "blocked_candle_source_validation_failed"}
            ),
            "backtest_diagnostics": len(benchmark_rows),
            "research_candidates": len(candidate_rows),
        },
        "outputs": [_file_fingerprint(path) for path in outputs],
    }


def _labeled_fingerprint(label: str, path: Path) -> dict[str, Any]:
    payload = _file_fingerprint(path)
    payload["lane"] = label
    return payload


def _file_fingerprint(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists() or not path.is_file():
        return payload
    stat = path.stat()
    payload["size_bytes"] = stat.st_size
    payload["mtime_utc"] = pd.Timestamp(stat.st_mtime, unit="s", tz="UTC").isoformat()
    payload["sha256"] = _sha256_file(path)
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_summary(
    live_rows: Sequence[dict[str, Any]],
    comparison_rows: Sequence[dict[str, Any]],
    confluence_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
    as_of_utc: pd.Timestamp,
) -> str:
    enriched = sum(1 for row in live_rows if row.get("diagnostic_schema_version"))
    candle_enriched = sum(1 for row in live_rows if row.get("candle_time_utc"))
    candle_blocked = sum(
        1
        for row in live_rows
        if row.get("candle_enrichment_status")
        in {"blocked_unverified_candle_source", "blocked_candle_source_validation_failed"}
    )
    excluded = sum(1 for row in live_rows if row.get("excluded_from_strategy_analysis") is True)
    lines = [
        "# LPFS Trade Diagnostics",
        "",
        f"Generated UTC: `{as_of_utc.isoformat()}`",
        f"Closed trades: `{len(live_rows)}`",
        f"Closed trades excluded from strategy analysis: `{excluded}`",
        f"Rows with diagnostic payloads: `{enriched}`",
        f"Rows with offline candle enrichment: `{candle_enriched}`",
        f"Rows with blocked/unverified candle enrichment: `{candle_blocked}`",
        "",
        "This report is additive/offline and does not change live trading behavior.",
        "",
        "Candle source policy: live lane indicator attribution requires an explicit "
        "lane-authoritative candle source. Local workstation candle roots are not "
        "used by default and unverified sources are blocked from RSI/MACD/EMA/"
        "volume/structure enrichment.",
        "",
        "Evidence policy: H8 or any other timeframe is not a selected change "
        "candidate until FTMO and IC diagnostics plus recent/full backtests support it.",
    ]
    notable = [
        row
        for row in comparison_rows
        if row.get("comparison_window") == "all"
        and row.get("group_by") == "lane|timeframe"
        and _first_float(row.get("live_trades")) not in (None, 0)
    ]
    if notable:
        lines.extend(["", "## Timeframe Comparison", ""])
        for row in notable:
            lines.append(
                "- "
                + f"{row.get('lane')} {row.get('timeframe')}: "
                + f"live {row.get('live_trades')} trades, avg {float(row.get('live_avg_r') or 0):+.3f}R; "
                + f"backtest avg {float(row.get('backtest_avg_r') or 0):+.3f}R"
            )
    weak = [row for row in confluence_rows if row.get("comparison_window") == "all" and row.get("confluence_status") == "both_lanes_weak"]
    if weak:
        lines.extend(["", "## Cross-Lane Weakness", ""])
        for row in weak:
            lines.append(
                "- "
                + f"{row.get('timeframe')}: {row.get('combined_live_trades')} live trades, "
                + f"action `{row.get('research_action')}`"
            )
    candidates = [
        row
        for row in candidate_rows
        if row.get("comparison_window") == "all"
        and row.get("research_priority") in {"candidate_backtest_required", "investigate_not_deployable"}
    ][:10]
    if candidates:
        lines.extend(["", "## Research Candidates", ""])
        for row in candidates:
            group_values = " ".join(
                f"{key}={row.get(key)}" for key in str(row.get("group_by") or "").split("|") if row.get(key)
            )
            lines.append(
                "- "
                + f"{group_values}: {row.get('lane_confluence_status')}, "
                + f"combined {row.get('combined_live_trades')} trades, "
                + f"{float(row.get('combined_live_net_r') or 0):+.2f}R; "
                + f"priority `{row.get('research_priority')}`"
            )
    return "\n".join(lines) + "\n"


def _prefix(prefix: str, values: dict[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in values.items()}


def _delta(left: Any, right: Any) -> float | None:
    left_value = _first_float(left)
    right_value = _first_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _delta_number(left: Any, right: Any) -> float | None:
    left_value = _first_float(left)
    right_value = _first_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _first_float(*values: Any) -> float | None:
    for value in values:
        try:
            if _is_missing(value):
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if not _is_missing(value):
            return str(value)
    return ""


def _first_timestamp(*values: Any) -> pd.Timestamp | None:
    for value in values:
        try:
            if _is_missing(value):
                continue
            timestamp = pd.Timestamp(value)
            if pd.isna(timestamp):
                continue
            return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        except Exception:
            continue
    return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        result = pd.isna(value)
        if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
            return False
        return bool(result)
    except Exception:
        return False


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * quantile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _risk_atr_bucket(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed < 0.5:
        return "lt_0p5"
    if parsed < 1.0:
        return "0p5_to_1"
    if parsed < 1.5:
        return "1_to_1p5"
    return "gte_1p5"


def _small_count_bucket(value: Any, *, single_until: int, mid_label: str) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    rounded = int(parsed)
    if rounded <= single_until:
        return str(rounded)
    if rounded <= 6:
        return mid_label
    return "gte_7"


def _spread_risk_bucket(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed <= 0.05:
        return "lte_5pct"
    if parsed <= 0.10:
        return "5_to_10pct"
    if parsed <= 0.20:
        return "10_to_20pct"
    return "gt_20pct"


def _lane_key(value: Any) -> str:
    text = str(value or "").upper()
    if "IC" in text:
        return "IC"
    if "FTMO" in text:
        return "FTMO"
    return text


def _source_for_lane(sources: dict[str, CandleSource], lane: str) -> CandleSource | None:
    lane_key = _lane_key(lane)
    return sources.get(lane_key)


def _timeframe_frequency_class(timeframe: str) -> str:
    label = timeframe.upper()
    if label in {"M30", "H1", "H2", "H3", "H4"}:
        return "higher_frequency"
    if label in {"H8", "H12", "D1"}:
        return "mid_frequency"
    if label in {"W1", "MN1"}:
        return "sparse"
    return "unknown"


def _min_investigate_trades(timeframe: str) -> int:
    return {"higher_frequency": 20, "mid_frequency": 10, "sparse": 5}.get(_timeframe_frequency_class(timeframe), 10)


def _min_candidate_trades(timeframe: str) -> int:
    return {"higher_frequency": 40, "mid_frequency": 20, "sparse": 10}.get(_timeframe_frequency_class(timeframe), 20)


def _confluence_status(deltas: Sequence[float], populated_lanes: int) -> str:
    if populated_lanes < 2:
        return "single_lane_or_missing_live_data"
    if len(deltas) < 2:
        return "insufficient_backtest_comparison"
    if all(value < 0 for value in deltas):
        return "both_lanes_weak"
    if all(value > 0 for value in deltas):
        return "both_lanes_strong"
    return "mixed_lanes"


def _research_action(row: dict[str, Any]) -> str:
    live_trades = int(_first_float(row.get("combined_live_trades")) or 0)
    if row.get("confluence_status") != "both_lanes_weak":
        return "monitor_or_broker_execution_review"
    if live_trades >= int(row.get("evidence_min_candidate_trades") or 0):
        return "research_candidate_with_recent_and_full_backtests"
    if live_trades >= int(row.get("evidence_min_investigate_trades") or 0):
        return "investigate_not_deployable"
    return "watch_sample_too_small"


def _sum_int(*values: Any) -> int:
    return int(sum(_first_float(value) or 0 for value in values))


def _timeframe_sort_key(value: str) -> tuple[int, str]:
    order = {"M30": 0, "H1": 1, "H4": 2, "H8": 3, "H12": 4, "D1": 5, "W1": 6}
    return (order.get(str(value).upper(), 99), str(value).upper())


class _CandleFeatureCache:
    def __init__(self, sources: dict[str, CandleSource]) -> None:
        self._sources = sources
        self._cache: dict[tuple[Path, str, str], pd.DataFrame] = {}

    def lookup(self, *, lane: str, symbol: str, timeframe: str, timestamp: pd.Timestamp | None) -> dict[str, Any]:
        if timestamp is None or not symbol or not timeframe:
            return {"candle_enrichment_status": "missing_lookup_key"}
        source = _source_for_lane(self._sources, lane)
        if source is None:
            return {"candle_enrichment_status": "no_candle_source"}
        base_payload = {
            "candle_source_root": str(source.path),
            "candle_source_provenance": source.provenance,
            "candle_source_validation_status": source.validation_status,
            "candle_source_validation_error": source.validation_error,
            "candle_source_safe_for_strategy_analysis": source.safe_for_strategy_analysis,
        }
        if not source.safe_for_strategy_analysis:
            status = (
                "blocked_candle_source_validation_failed"
                if source.provenance == "vps_lane_broker_feed"
                else "blocked_unverified_candle_source"
            )
            return {**base_payload, "candle_enrichment_status": status}
        frame = self._frame(source.path, symbol.upper(), timeframe.upper())
        if frame.empty:
            return {**base_payload, "candle_enrichment_status": "missing_candle_frame"}
        times = pd.to_datetime(frame["time_utc"], utc=True)
        index = int(times.searchsorted(timestamp, side="right") - 1)
        if index < 0 or index >= len(frame):
            return {**base_payload, "candle_enrichment_status": "no_candle_before_analysis_time"}
        row = frame.iloc[index]
        return {
            **base_payload,
            "candle_enrichment_status": "enriched",
            "candle_time_utc": _timestamp_text(row.get("time_utc")),
            "candle_rsi_14": _first_float(row.get("rsi_14")),
            "candle_rsi_regime": row.get("rsi_regime") or "",
            "candle_momentum_3": _first_float(row.get("momentum_3")),
            "candle_momentum_3_regime": row.get("momentum_3_regime") or "",
            "candle_ema_20": _first_float(row.get("ema_20")),
            "candle_ema_50": _first_float(row.get("ema_50")),
            "candle_close_ema_20_distance_pct": _first_float(row.get("close_ema_20_distance_pct")),
            "candle_close_vs_ema_20": row.get("close_vs_ema_20") or "",
            "candle_ema_20_slope_5": _first_float(row.get("ema_20_slope_5")),
            "candle_ema_20_slope_regime": row.get("ema_20_slope_regime") or "",
            "candle_macd_12_26": _first_float(row.get("macd_12_26")),
            "candle_macd_signal_9": _first_float(row.get("macd_signal_9")),
            "candle_macd_histogram": _first_float(row.get("macd_histogram")),
            "candle_macd_histogram_regime": row.get("macd_histogram_regime") or "",
            "candle_atr_14": _first_float(row.get("atr_14")),
            "candle_atr_regime_252": row.get("atr_regime_252") or "",
            "candle_tick_volume_regime_252": row.get("tick_volume_regime_252") or "",
            "candle_spread_regime_252": row.get("spread_regime_252") or "",
            "candle_body_fraction": _first_float(row.get("body_fraction")),
            "candle_close_location": _first_float(row.get("close_location")),
            "candle_direction": row.get("candle_direction") or "",
        }

    def _frame(self, root: Path, symbol: str, timeframe: str) -> pd.DataFrame:
        key = (root, symbol, timeframe)
        if key not in self._cache:
            self._cache[key] = _load_candle_feature_frame(root, symbol=symbol, timeframe=timeframe)
        return self._cache[key]


def _load_candle_feature_frame(root: Path, *, symbol: str, timeframe: str) -> pd.DataFrame:
    base = root / symbol.upper() / timeframe.upper() / f"{symbol.upper()}_{timeframe.upper()}"
    parquet_path = base.with_suffix(".parquet")
    csv_path = base.with_suffix(".csv")
    try:
        if parquet_path.exists():
            raw = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            raw = pd.read_csv(csv_path)
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()
    required = {"time_utc", "open", "high", "low", "close"}
    if not required.issubset(raw.columns):
        return pd.DataFrame()
    data = raw.copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True)
    for column in ("open", "high", "low", "close", "tick_volume", "spread_points"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.sort_values("time_utc").drop_duplicates("time_utc", keep="last").reset_index(drop=True)
    return _add_candle_features(data)


def _add_candle_features(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    open_ = frame["open"].astype(float)
    close = frame["close"].astype(float)
    candle_range = (high - low).replace(0, pd.NA)
    frame["body_fraction"] = (close - open_).abs() / candle_range
    frame["close_location"] = (close - low) / candle_range
    frame["candle_direction"] = ["up" if value > 0 else "down" if value < 0 else "flat" for value in close - open_]
    frame["momentum_3"] = close.pct_change(3)
    frame["momentum_3_regime"] = [_momentum_regime(value) for value in frame["momentum_3"]]
    frame["ema_20"] = close.ewm(span=20, adjust=False, min_periods=5).mean()
    frame["ema_50"] = close.ewm(span=50, adjust=False, min_periods=10).mean()
    frame["close_ema_20_distance_pct"] = (close - frame["ema_20"]) / frame["ema_20"].replace(0, pd.NA)
    frame["close_vs_ema_20"] = [_ema_relation(value) for value in frame["close_ema_20_distance_pct"]]
    frame["ema_20_slope_5"] = (frame["ema_20"] - frame["ema_20"].shift(5)) / frame["ema_20"].shift(5).replace(0, pd.NA)
    frame["ema_20_slope_regime"] = [_slope_regime(value) for value in frame["ema_20_slope_5"]]
    ema_12 = close.ewm(span=12, adjust=False, min_periods=6).mean()
    ema_26 = close.ewm(span=26, adjust=False, min_periods=13).mean()
    frame["macd_12_26"] = ema_12 - ema_26
    frame["macd_signal_9"] = frame["macd_12_26"].ewm(span=9, adjust=False, min_periods=5).mean()
    frame["macd_histogram"] = frame["macd_12_26"] - frame["macd_signal_9"]
    frame["macd_histogram_regime"] = [_macd_histogram_regime(value) for value in frame["macd_histogram"]]
    frame["rsi_14"] = _rsi(close, period=14)
    frame["rsi_regime"] = [_rsi_regime(value) for value in frame["rsi_14"]]
    previous_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    frame["atr_14"] = true_range.rolling(14, min_periods=14).mean()
    frame["atr_regime_252"] = _rolling_regime(frame["atr_14"])
    if "tick_volume" in frame.columns:
        frame["tick_volume_regime_252"] = _rolling_regime(frame["tick_volume"])
    else:
        frame["tick_volume_regime_252"] = ""
    if "spread_points" in frame.columns:
        frame["spread_regime_252"] = _rolling_regime(frame["spread_points"])
    else:
        frame["spread_regime_252"] = ""
    return frame


def _rsi(close: pd.Series, *, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.rolling(period, min_periods=period).mean()
    average_loss = loss.rolling(period, min_periods=period).mean()
    rs = average_gain / average_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _rolling_regime(values: pd.Series, *, window: int = 252) -> list[str]:
    numeric = pd.to_numeric(values, errors="coerce")
    low = numeric.rolling(window, min_periods=5).quantile(0.33)
    high = numeric.rolling(window, min_periods=5).quantile(0.67)
    regimes: list[str] = []
    for value, low_value, high_value in zip(numeric, low, high):
        if pd.isna(value) or pd.isna(low_value) or pd.isna(high_value):
            regimes.append("")
        elif value <= low_value:
            regimes.append("low")
        elif value >= high_value:
            regimes.append("high")
        else:
            regimes.append("normal")
    return regimes


def _momentum_regime(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed > 0.001:
        return "up"
    if parsed < -0.001:
        return "down"
    return "flat"


def _rsi_regime(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed < 35:
        return "oversold"
    if parsed > 65:
        return "overbought"
    return "neutral"


def _ema_relation(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed > 0.001:
        return "above"
    if parsed < -0.001:
        return "below"
    return "near"


def _slope_regime(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed > 0.001:
        return "rising"
    if parsed < -0.001:
        return "falling"
    return "flat"


def _macd_histogram_regime(value: Any) -> str:
    parsed = _first_float(value)
    if parsed is None:
        return ""
    if parsed > 0:
        return "positive"
    if parsed < 0:
        return "negative"
    return "zero"


def _timestamp_text(value: Any) -> str:
    timestamp = _first_timestamp(value)
    return timestamp.isoformat() if timestamp is not None else ""


if __name__ == "__main__":
    raise SystemExit(main())
