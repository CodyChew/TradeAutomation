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


def _display_path(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


SRC_ROOTS = [
    REPO_ROOT / "shared" / "market_data_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
    REPO_ROOT / "scripts",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_dashboard_metadata import (  # noqa: E402
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    experiment_summary_css,
    experiment_summary_html,
    metric_glossary_html,
)
from lp_force_strike_strategy_lab.tp_near_exit import (  # noqa: E402
    TPNearExitVariant,
    classify_tp_near_outcome,
    run_lp_force_strike_tp_near_exit_on_frame,
)
from market_data_lab import load_dataset_config, normalize_timeframe  # noqa: E402
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
from run_lp_force_strike_v18_tp_near_exit import (  # noqa: E402
    CONTROL_VARIANT_ID,
    _aggregate_trade_metrics,
    _compare_frames,
    _cost_config,
    _load_backtest_frame,
    _make_candidate,
    _parse_csv_arg,
    _row_to_trade_record,
    _run_bucket_sensitivity_by_variant,
    _selected_symbols,
    _selected_timeframes,
    _signal_row,
    _skipped_row,
    _tp_near_outcome_rows,
    _trade_key,
    _trade_row,
    _variant_sort_key,
)


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
            full_target_priority=bool(item.get("full_target_priority", True)),
        )
        for item in config.get("tp_near_variants", [])
    ]
    if not variants:
        raise ValueError("V19 config requires at least one tp_near_variants row.")
    if variants[0].variant_id != CONTROL_VARIANT_ID or variants[0].mode != "control":
        raise ValueError(f"First V19 variant must be {CONTROL_VARIANT_ID!r} control.")
    return variants


def _variant_family(variant_id: str) -> str:
    value = str(variant_id)
    if value == CONTROL_VARIANT_ID:
        return "control"
    if "haircut" in value:
        return "haircut_close"
    if "delay" in value:
        return "delayed_close"
    if value.startswith("close"):
        return "clean_close"
    if value.startswith("breakeven"):
        return "breakeven_protect"
    if value.startswith("lock"):
        return "locked_profit_protect"
    return "other"


def _base_stress_variant(variant_id: str) -> str:
    value = str(variant_id)
    for suffix in [
        "_haircut_0p25x",
        "_haircut_0p5x",
        "_haircut_1x",
        "_delay_1bar",
    ]:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _profit_factor_delta(row: pd.Series, control_pf: float | None) -> float | None:
    current = row.get("profit_factor")
    if current is None or pd.isna(current) or control_pf is None or pd.isna(control_pf):
        return None
    return float(current) - float(control_pf)


def _outcome_wide(outcomes: pd.DataFrame) -> pd.DataFrame:
    if outcomes.empty:
        return pd.DataFrame()
    rows = []
    for variant_id, group in outcomes.groupby("tp_near_variant_id"):
        row: dict[str, Any] = {"tp_near_variant_id": variant_id}
        for _, item in group.iterrows():
            outcome = str(item["outcome"])
            row[f"{outcome}_trades"] = int(item["trades"])
            row[f"{outcome}_r_delta"] = float(item.get("net_r_delta_vs_control", 0.0))
        rows.append(row)
    data = pd.DataFrame(rows)
    for outcome in [
        "unchanged",
        "saved_from_stop",
        "sacrificed_full_tp",
        "improved_end_of_data",
        "worsened_end_of_data",
        "same_bar_conflict",
    ]:
        data[f"{outcome}_trades"] = data.get(f"{outcome}_trades", 0)
        data[f"{outcome}_r_delta"] = data.get(f"{outcome}_r_delta", 0.0)
    return data


def _breakdown_delta(trades: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    summary = _aggregate_trade_metrics(trades, ["tp_near_variant_id", *group_fields])
    if summary.empty:
        return summary
    control = summary[summary["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    control = control.set_index(group_fields)
    rows = []
    for _, row in summary.iterrows():
        key = tuple(row[field] for field in group_fields)
        if len(key) == 1:
            key = key[0]
        control_row = control.loc[key] if key in control.index else None
        payload = row.to_dict()
        if control_row is None:
            payload["control_total_net_r"] = None
            payload["total_net_r_delta_vs_control"] = None
        else:
            payload["control_total_net_r"] = float(control_row["total_net_r"])
            payload["total_net_r_delta_vs_control"] = float(row["total_net_r"]) - float(control_row["total_net_r"])
        rows.append(payload)
    return pd.DataFrame(rows)


def _year_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    data = trades.copy()
    data["exit_year"] = pd.to_datetime(data["exit_time_utc"], errors="coerce", utc=True).dt.year
    return _breakdown_delta(data.dropna(subset=["exit_year"]), ["exit_year"])


def _stress_sensitivity(summary: pd.DataFrame, delta: pd.DataFrame) -> pd.DataFrame:
    control_delta = delta[delta["comparison_baseline"].eq(CONTROL_VARIANT_ID)].copy()
    merged = summary.merge(control_delta, on="tp_near_variant_id", how="left", suffixes=("", "_delta"))
    if merged.empty:
        return merged
    merged["stress_family"] = merged["tp_near_variant_id"].map(_variant_family)
    merged["base_stress_variant_id"] = merged["tp_near_variant_id"].map(_base_stress_variant)
    columns = [
        "base_stress_variant_id",
        "stress_family",
        "tp_near_variant_id",
        "trades",
        "total_net_r",
        "avg_net_r",
        "profit_factor",
        "total_net_r_delta",
        "exit_reason_changed",
        "tp_near_close_exits",
        "tp_near_protect_exits",
    ]
    return merged[[column for column in columns if column in merged.columns]].sort_values(
        ["base_stress_variant_id", "stress_family", "tp_near_variant_id"],
        key=lambda series: series.map(_variant_sort_key) if series.name == "tp_near_variant_id" else series,
    )


def _changed_trade_samples(trades: pd.DataFrame, *, max_per_variant_outcome: int = 8) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    control = trades[trades["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    control = control.drop_duplicates("trade_key").set_index("trade_key")
    rows = []
    wanted = {"saved_from_stop", "sacrificed_full_tp"}
    for variant_id in sorted(trades["tp_near_variant_id"].dropna().unique(), key=_variant_sort_key):
        if variant_id == CONTROL_VARIANT_ID:
            continue
        variant = trades[trades["tp_near_variant_id"].eq(variant_id)].copy()
        counts = {outcome: 0 for outcome in wanted}
        for _, row in variant.iterrows():
            key = row["trade_key"]
            if key not in control.index:
                continue
            outcome = classify_tp_near_outcome(_row_to_trade_record(control.loc[key]), _row_to_trade_record(row))
            if outcome not in wanted or counts[outcome] >= max_per_variant_outcome:
                continue
            control_row = control.loc[key]
            rows.append(
                {
                    "tp_near_variant_id": variant_id,
                    "outcome": outcome,
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "side": row["side"],
                    "signal_index": int(float(row["signal_index"])),
                    "entry_time_utc": row.get("entry_time_utc"),
                    "control_exit_reason": control_row["exit_reason"],
                    "control_net_r": float(control_row["net_r"]),
                    "variant_exit_reason": row["exit_reason"],
                    "variant_net_r": float(row["net_r"]),
                    "net_r_delta_vs_control": float(row["net_r"]) - float(control_row["net_r"]),
                    "tp_near_trigger_index": row.get("meta_tp_near_trigger_index"),
                    "tp_near_trigger_price": row.get("meta_tp_near_trigger_price"),
                }
            )
            counts[outcome] += 1
    return pd.DataFrame(rows)


def _variant_decision_frame(
    summary: pd.DataFrame,
    delta: pd.DataFrame,
    outcomes: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    symbol_timeframe: pd.DataFrame,
    years: pd.DataFrame,
    criteria: dict[str, Any],
) -> pd.DataFrame:
    control_delta = delta[delta["comparison_baseline"].eq(CONTROL_VARIANT_ID)].copy()
    merged = summary.merge(control_delta, on="tp_near_variant_id", how="left", suffixes=("", "_delta"))
    merged = merged.merge(_outcome_wide(outcomes), on="tp_near_variant_id", how="left")
    merged = merged.merge(bucket_summary, on="tp_near_variant_id", how="left")
    for column in merged.columns:
        if column.endswith("_trades") or column.endswith("_r_delta"):
            merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
    control = merged[merged["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].iloc[0]
    control_pf = None if pd.isna(control.get("profit_factor")) else float(control["profit_factor"])
    control_efficiency = float(control.get("efficient_return_to_reserved_drawdown", 0.0) or 0.0)
    rows = []
    for _, row in merged.iterrows():
        variant_id = str(row["tp_near_variant_id"])
        saved_r = float(row.get("saved_from_stop_r_delta", 0.0) or 0.0)
        sacrificed_r = abs(float(row.get("sacrificed_full_tp_r_delta", 0.0) or 0.0))
        saved_to_sacrificed = float("inf") if saved_r > 0 and sacrificed_r == 0 else (saved_r / sacrificed_r if sacrificed_r else 0.0)
        variant_symbol_rows = symbol_timeframe[symbol_timeframe["tp_near_variant_id"].eq(variant_id)].copy()
        positive_symbol_delta = pd.to_numeric(variant_symbol_rows.get("total_net_r_delta_vs_control"), errors="coerce").clip(lower=0)
        positive_total = float(positive_symbol_delta.sum()) if not positive_symbol_delta.empty else 0.0
        top_symbol_share = float(positive_symbol_delta.max() / positive_total) if positive_total > 0 else 1.0
        variant_years = years[years["tp_near_variant_id"].eq(variant_id)].copy()
        year_delta = pd.to_numeric(variant_years.get("total_net_r_delta_vs_control"), errors="coerce").dropna()
        positive_year_ratio = float((year_delta > 0).mean()) if len(year_delta) else 0.0
        pf_delta = _profit_factor_delta(row, control_pf)
        pass_raw_r = float(row.get("total_net_r_delta", 0.0) or 0.0) >= float(criteria.get("min_stressed_r_delta", 250.0))
        pass_pf = pf_delta is not None and pf_delta > 0
        pass_efficiency = float(row.get("efficient_return_to_reserved_drawdown", 0.0) or 0.0) > control_efficiency
        pass_bucket = bool(row.get("efficient_passes_practical_filters", False))
        pass_saved_ratio = saved_to_sacrificed >= float(criteria.get("min_saved_to_sacrificed_r_ratio", 2.0))
        pass_concentration = top_symbol_share <= 0.5
        pass_years = positive_year_ratio >= 0.6
        pass_same_bar = float(row.get("same_bar_conflict_trades", 0.0) or 0.0) <= max(1.0, float(row.get("saved_from_stop_trades", 0.0) or 0.0))
        live_candidate = (
            variant_id != CONTROL_VARIANT_ID
            and pass_raw_r
            and pass_pf
            and pass_efficiency
            and pass_bucket
            and pass_saved_ratio
            and pass_concentration
            and pass_years
            and pass_same_bar
        )
        payload = row.to_dict()
        payload.update(
            {
                "stress_family": _variant_family(variant_id),
                "base_stress_variant_id": _base_stress_variant(variant_id),
                "profit_factor_delta_vs_control": pf_delta,
                "saved_to_sacrificed_r_ratio": saved_to_sacrificed,
                "top_symbol_timeframe_positive_delta_share": top_symbol_share,
                "positive_year_delta_ratio": positive_year_ratio,
                "pass_min_r_delta": pass_raw_r,
                "pass_pf_delta": pass_pf,
                "pass_efficiency_delta": pass_efficiency,
                "pass_practical_bucket": pass_bucket,
                "pass_saved_to_sacrificed": pass_saved_ratio,
                "pass_symbol_timeframe_concentration": pass_concentration,
                "pass_year_stability": pass_years,
                "pass_same_bar_conflict": pass_same_bar,
                "live_candidate": live_candidate,
            }
        )
        rows.append(payload)
    return pd.DataFrame(rows)


def _decision(decision_frame: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = decision_frame[decision_frame["live_candidate"].astype(bool)].copy()
    if candidates.empty:
        ranked = decision_frame[~decision_frame["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
        best = ranked.sort_values(
            ["total_net_r_delta", "efficient_return_to_reserved_drawdown"],
            ascending=[False, False],
        ).iloc[0].to_dict()
        headline = "No V19 TP-near variant is a live candidate yet."
        detail = (
            f"Best raw variant is {best['tp_near_variant_id']} at "
            f"{_fmt_num(best['total_net_r_delta'], 1)}R versus control, but it failed at least one robustness gate."
        )
        follow_up = _follow_up_for_variant(best, live_candidate=False)
        return {"headline": headline, "detail": detail, "follow_up": follow_up}, best
    best = candidates.sort_values(
        ["efficient_return_to_reserved_drawdown", "total_net_r_delta"],
        ascending=[False, False],
    ).iloc[0].to_dict()
    headline = f"{best['tp_near_variant_id']} is the strongest V19 live-design candidate."
    detail = (
        f"It improved control by {_fmt_num(best['total_net_r_delta'], 1)}R, "
        f"PF by {_fmt_num(best['profit_factor_delta_vs_control'], 3)}, and passed the practical risk gates."
    )
    follow_up = _follow_up_for_variant(best, live_candidate=True)
    return {"headline": headline, "detail": detail, "follow_up": follow_up}, best


def _follow_up_for_variant(best: dict[str, Any], *, live_candidate: bool) -> str:
    family = str(best.get("stress_family", ""))
    variant_id = str(best.get("tp_near_variant_id", ""))
    if not live_candidate:
        if family == "clean_close":
            return f"Review why {variant_id} fails robustness, then test a live-friendly locked-profit version before any implementation."
        if family in {"haircut_close", "delayed_close"}:
            return f"Use {variant_id} as the conservative benchmark and inspect failed buckets before designing live exits."
        if "protect" in family:
            return f"Inspect {variant_id} changed trades; protect logic may be useful but needs simpler live mechanics."
        return "Reject TP-near for now unless manual trade review finds a narrower setup-quality condition."
    if family in {"clean_close", "haircut_close", "delayed_close"}:
        return f"Next experiment should design live mechanics for {variant_id}: market close checks, spread gate, order-send failure handling, and Telegram lifecycle wording."
    return f"Next experiment should design live protection mechanics for {variant_id}: stop modification timing, broker constraints, and same-bar conflict policy."


def _decision_table(decision_frame: pd.DataFrame) -> str:
    data = decision_frame.copy()
    data = data[~data["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)]
    data = data.sort_values(
        ["live_candidate", "efficient_return_to_reserved_drawdown", "total_net_r_delta"],
        ascending=[False, False, False],
    )
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _escape(row["stress_family"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r_delta"], 1), _metric_class(row["total_net_r_delta"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_num(row["profit_factor_delta_vs_control"], 3),
                _fmt_num(row["saved_from_stop_r_delta"], 1),
                _fmt_num(row["sacrificed_full_tp_r_delta"], 1),
                _fmt_num(row["saved_to_sacrificed_r_ratio"], 2),
                _fmt_int(row["same_bar_conflict_trades"]),
                _fmt_num(row["efficient_return_to_reserved_drawdown"], 2),
                "yes" if bool(row["live_candidate"]) else "no",
            ]
        )
    return _table(
        [
            "Variant",
            "Family",
            "Trades",
            "R Delta",
            "PF",
            "PF Delta",
            "Saved Stop R",
            "Sacrificed TP R",
            "Save/Sacrifice",
            "Same-Bar",
            "Return/DD",
            "Candidate",
        ],
        rows,
    )


def _symbol_timeframe_table(symbol_timeframe: pd.DataFrame) -> str:
    if symbol_timeframe.empty:
        return ""
    data = symbol_timeframe[~symbol_timeframe["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    data["abs_delta"] = pd.to_numeric(data["total_net_r_delta_vs_control"], errors="coerce").abs()
    data = data.sort_values("abs_delta", ascending=False).head(30)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r_delta_vs_control"], 1), _metric_class(row["total_net_r_delta_vs_control"])),
                _fmt_num(row["total_net_r"], 1),
                _fmt_num(row["profit_factor"], 3),
            ]
        )
    return _table(["Variant", "Symbol", "TF", "Trades", "R Delta", "Total R", "PF"], rows)


def _year_table(years: pd.DataFrame) -> str:
    if years.empty:
        return ""
    data = years[~years["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    data = data.sort_values(["tp_near_variant_id", "exit_year"], key=lambda s: s.map(_variant_sort_key) if s.name == "tp_near_variant_id" else s)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _fmt_int(row["exit_year"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r_delta_vs_control"], 1), _metric_class(row["total_net_r_delta_vs_control"])),
                _fmt_num(row["total_net_r"], 1),
            ]
        )
    return _table(["Variant", "Year", "Trades", "R Delta", "Total R"], rows[:80])


def _stress_table(stress: pd.DataFrame) -> str:
    rows = []
    for _, row in stress.iterrows():
        rows.append(
            [
                _escape(row["base_stress_variant_id"]),
                _escape(row["stress_family"]),
                _escape(row["tp_near_variant_id"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r_delta"], 1), _metric_class(row["total_net_r_delta"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_int(row["exit_reason_changed"]),
            ]
        )
    return _table(["Base", "Stress", "Variant", "Trades", "R Delta", "PF", "Exit Changes"], rows)


def _sample_table(samples: pd.DataFrame) -> str:
    if samples.empty:
        return "<p>No changed-trade samples were written.</p>"
    data = samples.copy().head(80)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["tp_near_variant_id"]),
                _escape(row["outcome"]),
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _escape(row["side"]),
                _fmt_int(row["signal_index"]),
                _escape(row["control_exit_reason"]),
                _fmt_num(row["control_net_r"], 2),
                _escape(row["variant_exit_reason"]),
                _fmt_num(row["variant_net_r"], 2),
                (_fmt_num(row["net_r_delta_vs_control"], 2), _metric_class(row["net_r_delta_vs_control"])),
            ]
        )
    return _table(
        ["Variant", "Outcome", "Symbol", "TF", "Side", "Signal", "Control Exit", "Control R", "Variant Exit", "Variant R", "Delta"],
        rows,
    )


def _html_report(
    run_dir: Path,
    decision_frame: pd.DataFrame,
    outcomes: pd.DataFrame,
    symbol_timeframe: pd.DataFrame,
    years: pd.DataFrame,
    stress: pd.DataFrame,
    samples: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    page = dashboard_page("v19.html")
    decision = run_summary["decision"]
    best = run_summary["best_variant"]
    subtitle = (
        "Research-only V19 robustness report. It keeps the V15 LPFS strategy baseline, "
        "uses the V16 no-buffer bid/ask control, and does not touch MT5 live state or orders."
    )
    pass_fail = "PASS" if bool(best.get("live_candidate", False)) else "FAIL"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V19 TP-Near Robustness - by Cody</title>
  <style>
    {dashboard_base_css()}
    {experiment_summary_css()}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V19 TP-Near Robustness - by Cody",
      subtitle_html=_escape(subtitle),
      current_page="v19.html",
      section_links=[
          ("#decision", "Decision"),
          ("#ranking", "Ranking"),
          ("#robustness", "Robustness"),
          ("#samples", "Samples"),
          ("#follow-up", "Follow-Up"),
          ("#rules", "Rules"),
      ],
  )}
  <main>
    {experiment_summary_html(page)}
    <section id="decision">
      <h2>Decision Card</h2>
      <p class="callout"><strong>{_escape(decision["headline"])}</strong> {_escape(decision["detail"])}</p>
      <div class="kpi-grid">
        <div class="kpi"><span>Recommendation</span><strong>{_escape(best["tp_near_variant_id"])}</strong><small>{_escape(pass_fail)} robustness gate</small></div>
        <div class="kpi"><span>R Delta vs V16</span><strong class="{_metric_class(best["total_net_r_delta"])}">{_fmt_num(best["total_net_r_delta"], 1)}</strong><small>no-buffer bid/ask control</small></div>
        <div class="kpi"><span>PF / Return-DD</span><strong>{_fmt_num(best["profit_factor"], 3)} / {_fmt_num(best["efficient_return_to_reserved_drawdown"], 2)}</strong><small>trade PF and V15 bucket efficiency</small></div>
        <div class="kpi"><span>Reserved DD / Worst Month</span><strong>{_fmt_pct_value(best["efficient_reserved_max_drawdown_pct"])} / {_fmt_pct_value(best["efficient_worst_month_pct"])}</strong><small>practical risk view</small></div>
      </div>
    </section>
    <section id="ranking">
      <h2>Variant Ranking And Gates</h2>
      <p>Rows are sorted by live-candidate status, efficient return/DD, then raw R delta. A candidate must improve raw R, PF, efficiency, practical risk, save/sacrifice ratio, concentration, year stability, and same-bar reliance.</p>
      {_decision_table(decision_frame)}
    </section>
    <section id="robustness">
      <h2>Robustness Sections</h2>
      <h3>Symbol / Timeframe Winners And Losers</h3>
      {_symbol_timeframe_table(symbol_timeframe)}
      <h3>Year-By-Year Stability</h3>
      {_year_table(years)}
      <h3>Stress Comparison</h3>
      {_stress_table(stress)}
    </section>
    <section id="samples">
      <h2>Changed-Trade Samples</h2>
      <p>Examples show both saved-from-stop and sacrificed-full-TP cases so the dashboard can be reviewed without opening the CSV first.</p>
      {_sample_table(samples)}
    </section>
    <section id="follow-up">
      <h2>Follow-Up Recommendation</h2>
      <p class="callout">{_escape(decision["follow_up"])}</p>
    </section>
    <section id="rules">
      <h2>Rules Tested</h2>
      <ul>
        <li>Strategy baseline remains V15/V13 mechanics: LP3, all H4/H8/H12/D1/W1, 0.5 pullback, FS structure stop, 1R target, fixed 6-bar windows.</li>
        <li>Execution control is V16 no-buffer bid/ask: OHLC is Bid and Ask is approximated from stored candle spread.</li>
        <li>Immediate-close variants behave as hard reduced effective TP, such as 0.9R target with 1R risk.</li>
        <li>Hard close variants do not get upgraded to the original full 1R target after the reduced TP threshold is touched.</li>
        <li>Haircut variants apply an adverse spread-multiple fill adjustment to immediate TP-near closes.</li>
        <li>Delayed variants wait one bar after near-TP before close/protect activation; stop checks still run first.</li>
        <li>Same-bar stop/target conflict remains stop-first.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Generated from <code>{_escape(_display_path(run_dir))}</code>. Research-only; no MT5 live calls.</footer>
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
        raise ValueError("V19 produced no trades.")
    control = trades[trades["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    if control.empty:
        raise ValueError("V19 requires a control_bid_ask control variant.")

    v15_config = _read_json(REPO_ROOT / str(config["v15_bucket_config"]))
    baseline_path = REPO_ROOT / str(config.get("baseline_trades_path", v15_config["input_trades_path"]))
    canonical_v15 = filter_baseline_trades(_read_csv(baseline_path), v15_config)
    canonical_v15 = canonical_v15.copy()
    canonical_v15["trade_key"] = canonical_v15.apply(_trade_key, axis=1)

    summary = _aggregate_trade_metrics(trades, ["tp_near_variant_id"])
    summary_by_timeframe = _aggregate_trade_metrics(trades, ["tp_near_variant_id", "timeframe"])
    summary_by_symbol = _aggregate_trade_metrics(trades, ["tp_near_variant_id", "symbol"])
    symbol_timeframe = _breakdown_delta(trades, ["symbol", "timeframe"])
    years = _year_breakdown(trades)
    delta_rows = []
    for variant_id in sorted(trades["tp_near_variant_id"].dropna().unique(), key=_variant_sort_key):
        variant = trades[trades["tp_near_variant_id"].eq(variant_id)]
        delta_rows.append(_compare_frames(control, variant, str(variant_id), CONTROL_VARIANT_ID))
        delta_rows.append(_compare_frames(canonical_v15, variant, str(variant_id), "canonical_v15_ohlc"))
    delta = pd.DataFrame(delta_rows)
    outcome_breakdown = pd.DataFrame(_tp_near_outcome_rows(trades))
    bucket_summary, _bucket_all = _run_bucket_sensitivity_by_variant(trades, v15_config, run_dir)
    stress = _stress_sensitivity(summary, delta)
    samples = _changed_trade_samples(trades)
    decision_frame = _variant_decision_frame(
        summary,
        delta,
        outcome_breakdown,
        bucket_summary,
        symbol_timeframe,
        years,
        config.get("decision_criteria", {}),
    )
    decision, best = _decision(decision_frame)

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
    _write_csv(run_dir / "symbol_timeframe_breakdown.csv", symbol_timeframe)
    _write_csv(run_dir / "year_breakdown.csv", years)
    _write_csv(run_dir / "stress_sensitivity.csv", stress)
    _write_csv(run_dir / "changed_trade_samples.csv", samples)
    _write_csv(run_dir / "variant_decision_matrix.csv", decision_frame)

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
        "decision_criteria": config.get("decision_criteria", {}),
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, decision_frame, outcome_breakdown, symbol_timeframe, years, stress, samples, run_summary).splitlines()
    ) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 1 if run_summary["failed_datasets"] else 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    decision_frame = _read_csv(run_dir / "variant_decision_matrix.csv")
    outcomes = _read_csv(run_dir / "tp_near_outcome_breakdown.csv")
    symbol_timeframe = _read_csv(run_dir / "symbol_timeframe_breakdown.csv")
    years = _read_csv(run_dir / "year_breakdown.csv")
    stress = _read_csv(run_dir / "stress_sensitivity.csv")
    samples = _read_csv(run_dir / "changed_trade_samples.csv")
    run_summary = _read_json(run_dir / "run_summary.json")
    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, decision_frame, outcomes, symbol_timeframe, years, stress, samples, run_summary).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V19 TP-near robustness study.")
    parser.add_argument("--config", help="Path to V19 TP-near robustness config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. H4,D1.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v19.html.")
    parser.add_argument("--render-run-dir", help="Existing V19 run directory to render without rerunning.")
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
