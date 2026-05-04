from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "shared" / "market_data_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import CostConfig, drop_incomplete_last_bar  # noqa: E402
from lp_force_strike_dashboard_metadata import (  # noqa: E402
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    experiment_summary_css,
    experiment_summary_html,
    metric_glossary_html,
)
from lp_force_strike_strategy_lab.experiment import (  # noqa: E402
    SkippedTrade,
    make_trade_model_candidates,
    trade_report_row,
)
from lp_force_strike_strategy_lab.signals import LPForceStrikeSignal  # noqa: E402
from lp_force_strike_strategy_lab.tp_near_exit import (  # noqa: E402
    TPNearExitVariant,
    classify_tp_near_outcome,
    run_lp_force_strike_tp_near_exit_on_frame,
)
from market_data_lab import (  # noqa: E402
    load_dataset_config,
    load_rates_parquet,
    manifest_path,
    normalize_timeframe,
    read_json,
)
from run_lp_force_strike_bucket_sensitivity_experiment import (  # noqa: E402
    _baseline_row,
    _efficiency_recommendation,
    _recommendation,
    run_bucket_sensitivity_analysis,
)
from run_lp_force_strike_risk_sizing_experiment import (  # noqa: E402
    _fmt_int,
    _fmt_num,
    _fmt_pct_value,
    _metric_class,
    _read_csv,
    _read_json,
    _table,
    filter_baseline_trades,
)


CONTROL_VARIANT_ID = "control_bid_ask"


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: str | Path, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    payload.to_csv(target, index=False)


def _parse_csv_arg(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _selected_symbols(dataset_symbols: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    if override is not None:
        symbols = override
    elif config.get("symbols") is None:
        symbols = list(dataset_symbols)
    else:
        symbols = [str(symbol).upper() for symbol in config.get("symbols", [])]
    excluded = {str(symbol).upper() for symbol in config.get("excluded_symbols", [])}
    return [symbol for symbol in symbols if symbol not in excluded]


def _selected_timeframes(dataset_timeframes: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    raw = override if override is not None else config.get("timeframes", dataset_timeframes)
    return [normalize_timeframe(timeframe) for timeframe in raw]


def _cost_config(payload: dict[str, Any]) -> CostConfig:
    costs = payload.get("costs", {})
    return CostConfig(
        use_candle_spread=bool(costs.get("use_candle_spread", True)),
        fallback_spread_points=float(costs.get("fallback_spread_points", 0.0)),
        entry_slippage_points=float(costs.get("entry_slippage_points", 0.0)),
        exit_slippage_points=float(costs.get("exit_slippage_points", 0.0)),
        round_turn_commission_points=float(costs.get("round_turn_commission_points", 0.0)),
    )


def _manifest(root: str | Path, symbol: str, timeframe: str) -> dict[str, Any]:
    return read_json(manifest_path(root, symbol, timeframe))


def _load_backtest_frame(data_root: str | Path, symbol: str, timeframe: str, *, drop_latest: bool) -> pd.DataFrame:
    frame = load_rates_parquet(data_root, symbol=symbol, timeframe=timeframe)
    manifest = _manifest(data_root, symbol, timeframe)
    point = manifest.get("symbol_metadata", {}).get("point")
    if point is not None:
        frame["point"] = float(point)
    if drop_latest:
        requested_end = manifest.get("requested_end_utc")
        if requested_end:
            frame = drop_incomplete_last_bar(frame, timeframe, as_of_time_utc=requested_end)
    return frame


def _make_candidate(config: dict[str, Any]):
    candidates = make_trade_model_candidates(
        entry_models=[str(config.get("entry_model", "signal_zone_pullback"))],
        stop_models=[str(config.get("stop_model", "fs_structure"))],
        target_rs=[float(config.get("target_r", 1.0))],
        max_risk_atrs=[float(value) for value in config.get("max_risk_atrs", [])],
        entry_zones=[float(config.get("entry_zone", 0.5))],
        exit_models=[str(config.get("exit_model", "single_target"))],
    )
    if len(candidates) != 1:
        raise ValueError("V18 expects exactly one baseline trade-model candidate.")
    return candidates[0]


def _variants_from_config(config: dict[str, Any]) -> list[TPNearExitVariant]:
    variants = [
        TPNearExitVariant(
            variant_id=str(item["variant_id"]),
            mode=str(item["mode"]),  # type: ignore[arg-type]
            threshold_mode=str(item.get("threshold_mode", "percent_to_target")),  # type: ignore[arg-type]
            threshold_value=float(item.get("threshold_value", 1.0)),
            lock_r=float(item.get("lock_r", 0.0)),
            fill_haircut_spread_mult=float(item.get("fill_haircut_spread_mult", 0.0)),
            activation_delay_bars=int(item.get("activation_delay_bars", 0)),
        )
        for item in config.get("tp_near_variants", [])
    ]
    if not variants:
        raise ValueError("V18 config requires at least one tp_near_variants row.")
    if variants[0].variant_id != CONTROL_VARIANT_ID or variants[0].mode != "control":
        raise ValueError(f"First V18 variant must be {CONTROL_VARIANT_ID!r} control.")
    return variants


def _signal_row(symbol: str, timeframe: str, pivot_strength: int, signal: LPForceStrikeSignal) -> dict[str, Any]:
    row = asdict(signal)
    row["symbol"] = symbol
    row["timeframe"] = timeframe
    row["pivot_strength"] = pivot_strength
    return row


def _trade_row(trade, *, pivot_strength: int) -> dict[str, Any]:
    row = trade_report_row(trade)
    base_candidate_id = str(row.get("candidate_id", ""))
    row["base_candidate_id"] = base_candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["tp_near_variant_id"] = str(row.get("meta_tp_near_variant_id", ""))
    row["tp_near_mode"] = str(row.get("meta_tp_near_mode", ""))
    row["tp_near_threshold_mode"] = str(row.get("meta_tp_near_threshold_mode", ""))
    row["tp_near_threshold_value"] = float(row.get("meta_tp_near_threshold_value", 0.0) or 0.0)
    row["tp_near_lock_r"] = float(row.get("meta_tp_near_lock_r", 0.0) or 0.0)
    row["tp_near_fill_haircut_spread_mult"] = float(row.get("meta_tp_near_fill_haircut_spread_mult", 0.0) or 0.0)
    row["tp_near_activation_delay_bars"] = int(float(row.get("meta_tp_near_activation_delay_bars", 0.0) or 0.0))
    row["trade_key"] = _trade_key(row)
    return row


def _skipped_row(skipped: SkippedTrade, candidate: Any, *, pivot_strength: int) -> dict[str, Any]:
    row = skipped.to_dict()
    variant_id = ""
    for token in str(row.get("detail", "")).split(";"):
        token = token.strip()
        if token.startswith("tp_near_variant_id="):
            variant_id = token.split("=", 1)[1]
            break
    row["base_candidate_id"] = candidate.candidate_id
    row["candidate_id"] = candidate.candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["tp_near_variant_id"] = variant_id
    return row


def _trade_key(row: pd.Series | dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol")),
            str(row.get("timeframe")),
            str(row.get("side")),
            str(int(float(row.get("signal_index")))),
            str(int(float(row.get("pivot_strength")))),
            str(row.get("base_candidate_id")),
        ]
    )


def _profit_factor(values: pd.Series) -> float | None:
    gross_win = float(values[values > 0].sum())
    gross_loss = float(values[values < 0].sum())
    if gross_loss == 0:
        return None
    return gross_win / abs(gross_loss)


def _aggregate_trade_metrics(frame: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data["bars_held"] = pd.to_numeric(data["bars_held"], errors="coerce").fillna(0.0)
    for optional in ("risk_distance", "meta_signal_spread_to_risk", "meta_signal_spread_points"):
        if optional in data.columns:
            data[optional] = pd.to_numeric(data[optional], errors="coerce")

    rows = []
    for keys, group in data.groupby(group_fields, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = group["net_r"]
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": int(len(group)),
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).mean()) if len(group) else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if len(group) else 0.0,
                "profit_factor": _profit_factor(net_r),
                "avg_bars_held": float(group["bars_held"].mean()) if len(group) else 0.0,
                "target_exits": int((group["exit_reason"] == "target").sum()),
                "stop_exits": int((group["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((group["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((group["exit_reason"] == "end_of_data").sum()),
                "tp_near_close_exits": int((group["exit_reason"] == "tp_near_close").sum()),
                "tp_near_protect_exits": int(group["exit_reason"].isin(["tp_near_breakeven_stop", "tp_near_lock_stop"]).sum()),
            }
        )
        if "meta_signal_spread_to_risk" in group.columns:
            row["avg_signal_spread_to_risk_pct"] = float(group["meta_signal_spread_to_risk"].mean() * 100.0)
        if "meta_signal_spread_points" in group.columns:
            row["avg_signal_spread_points"] = float(group["meta_signal_spread_points"].mean())
        if "risk_distance" in group.columns:
            row["avg_risk_distance"] = float(group["risk_distance"].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _compare_frames(baseline: pd.DataFrame, variant: pd.DataFrame, variant_id: str, baseline_id: str) -> dict[str, Any]:
    base = baseline.copy()
    current = variant.copy()
    if base.empty:
        raise ValueError("Comparison baseline trade frame is empty.")
    base["trade_key"] = base.apply(_trade_key, axis=1)
    current["trade_key"] = current.apply(_trade_key, axis=1)
    base = base.drop_duplicates("trade_key").set_index("trade_key")
    current = current.drop_duplicates("trade_key").set_index("trade_key")
    common = sorted(set(base.index).intersection(current.index))
    missing = sorted(set(base.index).difference(current.index))
    added = sorted(set(current.index).difference(base.index))
    exit_changed = sum(str(base.loc[key, "exit_reason"]) != str(current.loc[key, "exit_reason"]) for key in common)
    sign_changed = sum(float(base.loc[key, "net_r"]) * float(current.loc[key, "net_r"]) < 0 for key in common)
    common_delta = sum(float(current.loc[key, "net_r"]) - float(base.loc[key, "net_r"]) for key in common)
    return {
        "comparison_baseline": baseline_id,
        "tp_near_variant_id": variant_id,
        "baseline_trades": int(len(base)),
        "variant_trades": int(len(current)),
        "common_trades": int(len(common)),
        "missing_from_variant": int(len(missing)),
        "added_in_variant": int(len(added)),
        "exit_reason_changed": int(exit_changed),
        "win_loss_sign_changed": int(sign_changed),
        "baseline_total_net_r": float(pd.to_numeric(base["net_r"], errors="coerce").fillna(0.0).sum()),
        "variant_total_net_r": float(pd.to_numeric(current["net_r"], errors="coerce").fillna(0.0).sum()),
        "total_net_r_delta": float(
            pd.to_numeric(current["net_r"], errors="coerce").fillna(0.0).sum()
            - pd.to_numeric(base["net_r"], errors="coerce").fillna(0.0).sum()
        ),
        "common_net_r_delta": float(common_delta),
    }


def _tp_near_outcome_rows(trades: pd.DataFrame, control_variant_id: str = CONTROL_VARIANT_ID) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    control = trades[trades["tp_near_variant_id"].eq(control_variant_id)].copy()
    control = control.drop_duplicates("trade_key").set_index("trade_key")
    rows = []
    for variant_id in sorted(trades["tp_near_variant_id"].dropna().unique(), key=_variant_sort_key):
        variant = trades[trades["tp_near_variant_id"].eq(variant_id)].copy()
        outcome_counts = {name: 0 for name in _outcome_order()}
        outcome_deltas = {name: 0.0 for name in _outcome_order()}
        for _, row in variant.iterrows():
            key = row["trade_key"]
            if key not in control.index:
                continue
            outcome = classify_tp_near_outcome(_row_to_trade_record(control.loc[key]), _row_to_trade_record(row))
            outcome_counts[outcome] += 1
            outcome_deltas[outcome] += float(row["net_r"]) - float(control.loc[key, "net_r"])
        for outcome, count in outcome_counts.items():
            rows.append(
                {
                    "tp_near_variant_id": variant_id,
                    "outcome": outcome,
                    "trades": int(count),
                    "net_r_delta_vs_control": float(outcome_deltas[outcome]),
                }
            )
    return rows


def _outcome_order() -> list[str]:
    return [
        "unchanged",
        "saved_from_stop",
        "sacrificed_full_tp",
        "improved_end_of_data",
        "worsened_end_of_data",
        "same_bar_conflict",
    ]


def _row_to_trade_record(row: pd.Series):
    from backtest_engine_lab import TradeRecord

    return TradeRecord(
        setup_id=str(row.get("setup_id", "")),
        symbol=str(row.get("symbol", "")),
        timeframe=str(row.get("timeframe", "")),
        side=str(row.get("side", "long")),  # type: ignore[arg-type]
        signal_index=int(float(row.get("signal_index", 0))),
        entry_index=int(float(row.get("entry_index", 0))),
        exit_index=int(float(row.get("exit_index", 0))),
        entry_time_utc=pd.Timestamp(row.get("entry_time_utc")),
        exit_time_utc=pd.Timestamp(row.get("exit_time_utc")),
        entry_reference_price=float(row.get("entry_reference_price", 0.0)),
        entry_fill_price=float(row.get("entry_fill_price", 0.0)),
        exit_reference_price=float(row.get("exit_reference_price", 0.0)),
        exit_fill_price=float(row.get("exit_fill_price", 0.0)),
        stop_price=float(row.get("stop_price", 0.0)),
        target_price=float(row.get("target_price", 0.0)),
        risk_distance=float(row.get("risk_distance", 1.0)),
        reference_r=float(row.get("reference_r", 0.0)),
        fill_r=float(row.get("fill_r", 0.0)),
        commission_r=float(row.get("commission_r", 0.0)),
        net_r=float(row.get("net_r", 0.0)),
        bars_held=int(float(row.get("bars_held", 0))),
        exit_reason=str(row.get("exit_reason", "end_of_data")),  # type: ignore[arg-type]
        metadata={},
    )


def _variant_sort_key(value: str) -> tuple[int, str]:
    value = str(value)
    if value == CONTROL_VARIANT_ID:
        return (0, value)
    if value.startswith("close"):
        return (1, value)
    if value.startswith("breakeven"):
        return (2, value)
    if value.startswith("lock"):
        return (3, value)
    return (9, value)


def _run_bucket_sensitivity_by_variant(
    trades: pd.DataFrame,
    v15_config: dict[str, Any],
    run_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    combined_summaries = []
    for variant_id in sorted(trades["tp_near_variant_id"].dropna().unique(), key=_variant_sort_key):
        variant_trades = trades[trades["tp_near_variant_id"].eq(variant_id)].copy()
        summary, timeframe_rows, ticker_rows = run_bucket_sensitivity_analysis(variant_trades, v15_config)
        recommended = _recommendation(summary)
        efficient = _efficiency_recommendation(summary)
        baseline = _baseline_row(summary, v15_config)
        summary = summary.copy()
        summary["tp_near_variant_id"] = variant_id
        combined_summaries.append(summary)
        _write_csv(run_dir / f"v15_bucket_summary__{variant_id}.csv", summary)
        _write_csv(run_dir / f"v15_timeframe_contribution__{variant_id}.csv", timeframe_rows)
        _write_csv(run_dir / f"v15_ticker_contribution__{variant_id}.csv", ticker_rows)
        rows.append(
            {
                "tp_near_variant_id": variant_id,
                "recommended_schedule_id": str(recommended["schedule_id"]),
                "recommended_total_return_pct": float(recommended["total_return_pct"]),
                "recommended_reserved_max_drawdown_pct": float(recommended["reserved_max_drawdown_pct"]),
                "recommended_max_reserved_open_risk_pct": float(recommended["max_reserved_open_risk_pct"]),
                "recommended_worst_month_pct": float(recommended["worst_month_pct"]),
                "recommended_return_to_reserved_drawdown": float(recommended["return_to_reserved_drawdown"]),
                "recommended_passes_practical_filters": bool(recommended["passes_practical_filters"]),
                "efficient_schedule_id": str(efficient["schedule_id"]),
                "efficient_total_return_pct": float(efficient["total_return_pct"]),
                "efficient_reserved_max_drawdown_pct": float(efficient["reserved_max_drawdown_pct"]),
                "efficient_max_reserved_open_risk_pct": float(efficient["max_reserved_open_risk_pct"]),
                "efficient_worst_month_pct": float(efficient["worst_month_pct"]),
                "efficient_return_to_reserved_drawdown": float(efficient["return_to_reserved_drawdown"]),
                "efficient_passes_practical_filters": bool(efficient["passes_practical_filters"]),
                "baseline_total_return_pct": None if baseline is None else float(baseline["total_return_pct"]),
                "baseline_reserved_max_drawdown_pct": None if baseline is None else float(baseline["reserved_max_drawdown_pct"]),
            }
        )
    bucket_summary = pd.DataFrame(rows)
    combined = pd.concat(combined_summaries, ignore_index=True) if combined_summaries else pd.DataFrame()
    _write_csv(run_dir / "v15_bucket_sensitivity_by_variant.csv", bucket_summary)
    _write_csv(run_dir / "v15_bucket_sensitivity_all_rows.csv", combined)
    return bucket_summary, combined


def _decision(control_delta: pd.DataFrame, bucket_summary: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    practical = bucket_summary[bucket_summary["efficient_passes_practical_filters"].astype(bool)].copy()
    if practical.empty:
        practical = bucket_summary.copy()
    best = practical.sort_values(
        ["efficient_return_to_reserved_drawdown", "efficient_total_return_pct"],
        ascending=[False, False],
    ).iloc[0].to_dict()
    control_row = bucket_summary[bucket_summary["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].iloc[0].to_dict()
    if str(best["tp_near_variant_id"]) == CONTROL_VARIANT_ID:
        headline = "Keep TP handling unchanged for now."
        detail = "No TP-near variant beat the no-buffer bid/ask control on efficient return-to-reserved-drawdown."
    else:
        delta_row = control_delta[control_delta["tp_near_variant_id"].eq(best["tp_near_variant_id"])].iloc[0].to_dict()
        if float(delta_row["total_net_r_delta"]) <= 0:
            headline = "Do not add TP-near exits yet."
            detail = f"{best['tp_near_variant_id']} ranked efficiently but did not improve raw R versus control."
        else:
            headline = "A TP-near rule has potential, but needs review before live changes."
            detail = (
                f"{best['tp_near_variant_id']} improved raw R by {_fmt_num(delta_row['total_net_r_delta'], 1)} "
                f"and efficient return/DD from {_fmt_num(control_row['efficient_return_to_reserved_drawdown'], 2)} "
                f"to {_fmt_num(best['efficient_return_to_reserved_drawdown'], 2)}."
            )
    return {"headline": headline, "detail": detail}, best


def _summary_table(summary: pd.DataFrame, delta: pd.DataFrame) -> str:
    control_delta = delta[delta["comparison_baseline"].eq(CONTROL_VARIANT_ID)]
    merged = summary.merge(control_delta, on="tp_near_variant_id", how="left", suffixes=("", "_delta"))
    rows = []
    for _, row in merged.sort_values("tp_near_variant_id", key=lambda s: s.map(_variant_sort_key)).iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                (_fmt_num(row["avg_net_r"], 3), _metric_class(row["avg_net_r"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_int(row["exit_reason_changed"]),
                (_fmt_num(row["total_net_r_delta"], 1), _metric_class(row["total_net_r_delta"])),
                _fmt_int(row["tp_near_close_exits"] + row["tp_near_protect_exits"]),
            ]
        )
    return _table(["Variant", "Trades", "Total R", "Avg R", "PF", "Exit Changes", "R Delta", "TP-Near Exits"], rows)


def _bucket_table(bucket_summary: pd.DataFrame) -> str:
    rows = []
    for _, row in bucket_summary.sort_values("tp_near_variant_id", key=lambda s: s.map(_variant_sort_key)).iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _escape(row["efficient_schedule_id"]),
                (_fmt_pct_value(row["efficient_total_return_pct"]), _metric_class(row["efficient_total_return_pct"])),
                _fmt_pct_value(row["efficient_reserved_max_drawdown_pct"]),
                _fmt_pct_value(row["efficient_max_reserved_open_risk_pct"]),
                _fmt_pct_value(row["efficient_worst_month_pct"]),
                _fmt_num(row["efficient_return_to_reserved_drawdown"], 2),
                "yes" if bool(row["efficient_passes_practical_filters"]) else "no",
            ]
        )
    return _table(["Variant", "Efficient Schedule", "Return", "Reserved DD", "Max Open Risk", "Worst Month", "Return/DD", "Practical"], rows)


def _outcome_table(outcomes: pd.DataFrame) -> str:
    rows = []
    for _, row in outcomes.iterrows():
        rows.append([_escape(row["tp_near_variant_id"]), _escape(row["outcome"]), _fmt_int(row["trades"])])
    return _table(["Variant", "Outcome", "Trades"], rows)


def _html_report(
    run_dir: Path,
    summary: pd.DataFrame,
    delta: pd.DataFrame,
    outcomes: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    page = dashboard_page("v18.html")
    decision = run_summary["decision"]
    subtitle = (
        "Research-only V18 report. It compares TP-near close/protect variants "
        "against the no-buffer bid/ask control; no MT5 live state or orders are touched."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V18 TP-Near Exit - by Cody</title>
  <style>
    {dashboard_base_css()}
    {experiment_summary_css()}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V18 TP-Near Exit - by Cody",
      subtitle_html=_escape(subtitle),
      current_page="v18.html",
      section_links=[
          ("#decision", "Decision"),
          ("#variants", "Variants"),
          ("#outcomes", "Outcomes"),
          ("#buckets", "Buckets"),
          ("#rules", "Rules"),
      ],
  )}
  <main>
    {experiment_summary_html(page)}
    <section id="decision">
      <h2>Decision Read</h2>
      <p class="callout"><strong>{_escape(decision["headline"])}</strong> {_escape(decision["detail"])}</p>
      <div class="kpi-grid">
        <div class="kpi"><span>Control trades</span><strong>{_fmt_int(run_summary["control_trade_count"])}</strong><small>no-buffer bid/ask</small></div>
        <div class="kpi"><span>Variant rows</span><strong>{_fmt_int(run_summary["variant_trade_rows"])}</strong><small>all TP-near variants</small></div>
        <div class="kpi"><span>Best efficient variant</span><strong>{_escape(run_summary["best_variant"]["tp_near_variant_id"])}</strong><small>by return/reserved-DD</small></div>
        <div class="kpi"><span>Signals</span><strong>{_fmt_int(run_summary["signals"])}</strong><small>detected across scope</small></div>
      </div>
    </section>
    <section id="variants">
      <h2>TP-Near Variant Leaderboard</h2>
      <p>Delta is measured against the no-buffer bid/ask control. Canonical V15 deltas are also written to <code>old_vs_new_trade_delta.csv</code>.</p>
      {_summary_table(summary, delta)}
    </section>
    <section id="outcomes">
      <h2>TP-Near Outcome Breakdown</h2>
      <p>Changed trades are classified against the control row, so near-TP then later full TP is counted as sacrificed full TP for immediate-close variants.</p>
      {_outcome_table(outcomes)}
    </section>
    <section id="buckets">
      <h2>V15 Bucket Sensitivity Rerun</h2>
      {_bucket_table(bucket_summary)}
    </section>
    <section id="rules">
      <h2>Rules Tested</h2>
      <ul>
        <li>Control uses V16 no-buffer bid/ask mechanics, not a live behavior change.</li>
        <li>Long TP-near uses Bid; short TP-near uses Ask.</li>
        <li>Immediate-close variants exit at the threshold price when reached.</li>
        <li>Protect variants activate breakeven or locked-R stop after the near-TP bar; full TP can still hit later.</li>
        <li>Same-bar stop/target conflict remains stop-first.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Generated from <code>{_escape(run_dir)}</code>. Research-only; no MT5 live calls.</footer>
</body>
</html>
"""


def _run(
    config_path: Path,
    *,
    symbol_override: list[str] | None,
    timeframe_override: list[str] | None,
    output_dir: Path | None,
    docs_output: Path | None,
) -> int:
    config = _read_json(config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    symbols = _selected_symbols(dataset_config.symbols, config, symbol_override)
    timeframes = _selected_timeframes(dataset_config.timeframes, config, timeframe_override)
    pivot_strength = int(config.get("pivot_strength", 3))
    candidate = _make_candidate(config)
    variants = _variants_from_config(config)
    costs = _cost_config(config)

    run_dir = output_dir or REPO_ROOT / str(config["report_root"]) / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    all_signal_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    all_skipped_rows: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                frame = _load_backtest_frame(
                    dataset_config.data_root,
                    symbol,
                    timeframe,
                    drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
                )
                result = run_lp_force_strike_tp_near_exit_on_frame(
                    frame,
                    symbol=symbol,
                    timeframe=normalize_timeframe(timeframe),
                    candidate=candidate,
                    variants=variants,
                    pivot_strength=pivot_strength,
                    max_bars_from_lp_break=int(config.get("max_bars_from_lp_break", 6)),
                    atr_period=int(config.get("atr_period", 14)),
                    max_entry_wait_bars=int(config.get("max_entry_wait_bars", 6)),
                    costs=costs,
                )
                all_signal_rows.extend(_signal_row(symbol, timeframe, pivot_strength, signal) for signal in result.signals)
                all_trade_rows.extend(_trade_row(trade, pivot_strength=pivot_strength) for trade in result.trades)
                all_skipped_rows.extend(_skipped_row(skipped, candidate, pivot_strength=pivot_strength) for skipped in result.skipped)
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "pivot_strength": pivot_strength,
                        "status": "ok",
                        "rows": int(len(frame)),
                        "signals": int(len(result.signals)),
                        "variant_trades": int(len(result.trades)),
                        "variant_skipped": int(len(result.skipped)),
                    }
                )
                print(f"{symbol} {timeframe} LP{pivot_strength}: rows={len(frame)} signals={len(result.signals)} variant_trades={len(result.trades)}")
            except Exception as exc:
                dataset_rows.append({"symbol": symbol, "timeframe": timeframe, "status": "failed", "error": str(exc)})
                print(f"{symbol} {timeframe}: failed={exc}")

    trades = pd.DataFrame(all_trade_rows)
    if trades.empty:
        raise ValueError("V18 produced no trades.")
    control = trades[trades["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    if control.empty:
        raise ValueError("V18 requires a control_bid_ask control variant.")

    v15_config = _read_json(REPO_ROOT / str(config["v15_bucket_config"]))
    baseline_path = REPO_ROOT / str(config.get("baseline_trades_path", v15_config["input_trades_path"]))
    canonical_v15 = filter_baseline_trades(_read_csv(baseline_path), v15_config)
    canonical_v15 = canonical_v15.copy()
    canonical_v15["trade_key"] = canonical_v15.apply(_trade_key, axis=1)

    summary = _aggregate_trade_metrics(trades, ["tp_near_variant_id"])
    summary_by_timeframe = _aggregate_trade_metrics(trades, ["tp_near_variant_id", "timeframe"])
    summary_by_symbol = _aggregate_trade_metrics(trades, ["tp_near_variant_id", "symbol"])
    delta_rows = []
    for variant_id in sorted(trades["tp_near_variant_id"].dropna().unique(), key=_variant_sort_key):
        variant = trades[trades["tp_near_variant_id"].eq(variant_id)]
        delta_rows.append(_compare_frames(control, variant, str(variant_id), CONTROL_VARIANT_ID))
        delta_rows.append(_compare_frames(canonical_v15, variant, str(variant_id), "canonical_v15_ohlc"))
    delta = pd.DataFrame(delta_rows)
    outcome_breakdown = pd.DataFrame(_tp_near_outcome_rows(trades))
    bucket_summary, _bucket_all = _run_bucket_sensitivity_by_variant(trades, v15_config, run_dir)
    control_delta = delta[delta["comparison_baseline"].eq(CONTROL_VARIANT_ID)].copy()
    decision, best = _decision(control_delta, bucket_summary)

    _write_json(
        run_dir / "run_config.json",
        {
            "config_path": str(config_path),
            "config": config,
            "symbols": symbols,
            "timeframes": timeframes,
            "pivot_strength": pivot_strength,
            "candidate": asdict(candidate),
            "variants": [asdict(variant) for variant in variants],
        },
    )
    _write_csv(run_dir / "datasets.csv", pd.DataFrame(dataset_rows))
    _write_csv(run_dir / "signals.csv", pd.DataFrame(all_signal_rows))
    _write_csv(run_dir / "trades.csv", trades)
    _write_csv(run_dir / "skipped.csv", pd.DataFrame(all_skipped_rows))
    _write_csv(run_dir / "summary_by_variant.csv", summary)
    _write_csv(run_dir / "summary_by_variant_timeframe.csv", summary_by_timeframe)
    _write_csv(run_dir / "summary_by_variant_symbol.csv", summary_by_symbol)
    _write_csv(run_dir / "old_vs_new_trade_delta.csv", delta)
    _write_csv(run_dir / "tp_near_outcome_breakdown.csv", outcome_breakdown)

    run_summary = {
        "run_dir": str(run_dir),
        "baseline_trades_path": str(baseline_path),
        "canonical_v15_trade_count": int(len(canonical_v15)),
        "control_trade_count": int(len(control)),
        "signals": int(len(all_signal_rows)),
        "variant_trade_rows": int(len(all_trade_rows)),
        "variant_skipped": int(len(all_skipped_rows)),
        "failed_datasets": int(sum(1 for row in dataset_rows if row.get("status") != "ok")),
        "decision": decision,
        "best_variant": best,
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, summary, delta, outcome_breakdown, bucket_summary, run_summary).splitlines()
    ) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 1 if run_summary["failed_datasets"] else 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    summary = _read_csv(run_dir / "summary_by_variant.csv")
    delta = _read_csv(run_dir / "old_vs_new_trade_delta.csv")
    outcomes = _read_csv(run_dir / "tp_near_outcome_breakdown.csv")
    bucket_summary = _read_csv(run_dir / "v15_bucket_sensitivity_by_variant.csv")
    run_summary = _read_json(run_dir / "run_summary.json")
    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, summary, delta, outcomes, bucket_summary, run_summary).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V18 TP-near exit study.")
    parser.add_argument("--config", help="Path to V18 TP-near config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. H4,D1.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v18.html.")
    parser.add_argument("--render-run-dir", help="Existing V18 run directory to render without rerunning.")
    args = parser.parse_args()
    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    if args.config is None:
        raise SystemExit("--config is required unless --render-run-dir is used")
    return _run(
        Path(args.config),
        symbol_override=_parse_csv_arg(args.symbols),
        timeframe_override=_parse_csv_arg(args.timeframes),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        docs_output=None if args.docs_output is None else Path(args.docs_output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
