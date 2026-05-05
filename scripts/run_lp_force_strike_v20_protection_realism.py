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
from lp_force_strike_strategy_lab.protection_realism import (  # noqa: E402
    ProtectionRealismVariant,
    run_lp_force_strike_m30_protection_realism_on_frame,
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
    _run_bucket_sensitivity_by_variant,
    _selected_symbols,
    _selected_timeframes,
    _signal_row,
    _skipped_row,
    _tp_near_outcome_rows,
    _trade_key,
    _trade_row,
)
from run_lp_force_strike_v19_tp_near_robustness import (  # noqa: E402
    _breakdown_delta,
    _changed_trade_samples,
    _outcome_wide,
    _year_breakdown,
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


def _variants_from_config(config: dict[str, Any]) -> list[ProtectionRealismVariant]:
    variants = [
        ProtectionRealismVariant(
            variant_id=str(item["variant_id"]),
            mode=str(item["mode"]),  # type: ignore[arg-type]
            threshold_r=float(item.get("threshold_r", 0.9)),
            lock_r=float(item.get("lock_r", 0.5)),
            activation_delay_m30_bars=int(item.get("activation_delay_m30_bars", 0)),
            activation_model=str(item.get("activation_model", "next_m30_open")),  # type: ignore[arg-type]
            min_stop_distance_spread_mult=float(item.get("min_stop_distance_spread_mult", 0.0)),
            retry_rejected_modification=bool(item.get("retry_rejected_modification", False)),
        )
        for item in config.get("protection_variants", [])
    ]
    if not variants:
        raise ValueError("V20 config requires at least one protection_variants row.")
    if variants[0].variant_id != CONTROL_VARIANT_ID or variants[0].mode != "control":
        raise ValueError(f"First V20 variant must be {CONTROL_VARIANT_ID!r} control.")
    return variants


def _variant_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    if text == CONTROL_VARIANT_ID:
        return (0, text)
    if "same_assumed" in text:
        return (1, text)
    if "m30_next" in text:
        return (2, text)
    if "delay" in text:
        return (3, text)
    if "minstop" in text:
        return (4, text)
    if "retry" in text:
        return (5, text)
    return (9, text)


def _variant_family(variant_id: str) -> str:
    if variant_id == CONTROL_VARIANT_ID:
        return "m30_control"
    if "same_assumed" in variant_id:
        return "same_m30_assumed_upper_bound"
    if "retry" in variant_id:
        return "retry_after_rejection"
    if "minstop" in variant_id:
        return "broker_min_stop_stress"
    if "delay2" in variant_id:
        return "two_m30_bar_delay"
    if "delay1" in variant_id:
        return "one_m30_bar_delay"
    return "next_m30_bar_lock"


def _bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    values = frame[column]
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.lower().isin({"true", "1", "yes"})


def _protection_funnel(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for variant_id, group in trades.groupby("tp_near_variant_id"):
        triggered = _bool_column(group, "meta_tp_near_triggered")
        activated = _bool_column(group, "meta_protection_activated")
        status = group.get("meta_protection_activation_status", pd.Series("", index=group.index)).astype(str)
        rows.append(
            {
                "tp_near_variant_id": variant_id,
                "stress_family": _variant_family(str(variant_id)),
                "trades": int(len(group)),
                "triggered": int(triggered.sum()),
                "activated": int(activated.sum()),
                "trigger_rate": float(triggered.mean()) if len(group) else 0.0,
                "activation_rate_of_triggers": float(activated.sum() / triggered.sum()) if triggered.sum() else 0.0,
                "rejected_too_late": int(status.eq("rejected_too_late").sum()),
                "rejected_min_stop_distance": int(status.eq("rejected_min_stop_distance").sum()),
                "pending_end_of_data": int(status.eq("pending").sum()),
                "protected_stop_exits": int(group["exit_reason"].eq("tp_near_lock_stop").sum()),
                "target_exits": int(group["exit_reason"].eq("target").sum()),
                "stop_exits": int(group["exit_reason"].eq("stop").sum()),
                "same_bar_stop_exits": int(group["exit_reason"].eq("same_bar_stop_priority").sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("tp_near_variant_id", key=lambda series: series.map(_variant_sort_key))


def _decision_frame(
    summary: pd.DataFrame,
    delta: pd.DataFrame,
    outcomes: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    funnel: pd.DataFrame,
    criteria: dict[str, Any],
) -> pd.DataFrame:
    control_delta = delta[delta["comparison_baseline"].eq(CONTROL_VARIANT_ID)].copy()
    data = summary.merge(control_delta, on="tp_near_variant_id", how="left", suffixes=("", "_delta"))
    data = data.merge(_outcome_wide(outcomes), on="tp_near_variant_id", how="left")
    data = data.merge(bucket_summary, on="tp_near_variant_id", how="left")
    data = data.merge(funnel, on="tp_near_variant_id", how="left", suffixes=("", "_funnel"))
    for column in data.columns:
        if column.endswith("_trades") or column.endswith("_r_delta"):
            data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    control = data[data["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].iloc[0]
    control_efficiency = float(control.get("efficient_return_to_reserved_drawdown", 0.0) or 0.0)
    rows = []
    for _, row in data.iterrows():
        variant_id = str(row["tp_near_variant_id"])
        saved_r = float(row.get("saved_from_stop_r_delta", 0.0) or 0.0)
        sacrificed_r = abs(float(row.get("sacrificed_full_tp_r_delta", 0.0) or 0.0))
        saved_ratio = float("inf") if saved_r > 0 and sacrificed_r == 0 else (saved_r / sacrificed_r if sacrificed_r else 0.0)
        activation_rate = float(row.get("activation_rate_of_triggers", 0.0) or 0.0)
        pf_delta = float(row.get("profit_factor", 0.0) or 0.0) - float(control.get("profit_factor", 0.0) or 0.0)
        passes = (
            variant_id != CONTROL_VARIANT_ID
            and _variant_family(variant_id) != "same_m30_assumed_upper_bound"
            and float(row.get("total_net_r_delta", 0.0) or 0.0) >= float(criteria.get("min_r_delta", 150.0))
            and activation_rate >= float(criteria.get("min_protection_activation_rate", 0.5))
            and saved_ratio >= float(criteria.get("min_saved_to_sacrificed_r_ratio", 2.0))
            and pf_delta > 0
            and float(row.get("efficient_return_to_reserved_drawdown", 0.0) or 0.0) > control_efficiency
            and bool(row.get("efficient_passes_practical_filters", False))
        )
        payload = row.to_dict()
        payload.update(
            {
                "stress_family": _variant_family(variant_id),
                "profit_factor_delta_vs_control": pf_delta,
                "saved_to_sacrificed_r_ratio": saved_ratio,
                "live_design_candidate": passes,
            }
        )
        rows.append(payload)
    return pd.DataFrame(rows)


def _decision(decision: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = decision[decision["live_design_candidate"].astype(bool)].copy()
    ranked = decision[~decision["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    if candidates.empty:
        best = ranked.sort_values(["total_net_r_delta", "profit_factor_delta_vs_control"], ascending=[False, False]).iloc[0].to_dict()
        return (
            {
                "headline": "No V20 protection variant is strong enough for live design yet.",
                "detail": (
                    f"Best raw variant is {best['tp_near_variant_id']} at "
                    f"{_fmt_num(best['total_net_r_delta'], 1)}R versus M30 replay control, but it failed at least one gate or is only an upper-bound assumption."
                ),
                "follow_up": "Inspect activation misses and symbol/timeframe concentration before designing a live stop-modify rule.",
            },
            best,
        )
    best = candidates.sort_values(
        ["efficient_return_to_reserved_drawdown", "total_net_r_delta"],
        ascending=[False, False],
    ).iloc[0].to_dict()
    return (
        {
            "headline": f"{best['tp_near_variant_id']} is the strongest V20 live-design candidate.",
            "detail": (
                f"It improved M30 replay control by {_fmt_num(best['total_net_r_delta'], 1)}R, "
                f"activated protection on {_fmt_num(float(best['activation_rate_of_triggers']) * 100.0, 1)}% of trigger touches, "
                "and passed the practical bucket gates."
            ),
            "follow_up": "Next step is a live-design plan for stop modification: broker min-distance checks, journal states, Telegram wording, and VPS deployment safety.",
        },
        best,
    )


def _decision_table(decision: pd.DataFrame) -> str:
    data = decision[~decision["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    data = data.sort_values(
        ["live_design_candidate", "efficient_return_to_reserved_drawdown", "total_net_r_delta"],
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
                _fmt_num(float(row["activation_rate_of_triggers"]) * 100.0, 1) + "%",
                _fmt_int(row["rejected_too_late"]),
                _fmt_int(row["rejected_min_stop_distance"]),
                _fmt_num(row["saved_from_stop_r_delta"], 1),
                _fmt_num(row["sacrificed_full_tp_r_delta"], 1),
                _fmt_num(row["efficient_return_to_reserved_drawdown"], 2),
                "yes" if bool(row["live_design_candidate"]) else "no",
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
            "Activation",
            "Too Fast",
            "Min Stop",
            "Saved R",
            "Sacrificed R",
            "Return/DD",
            "Candidate",
        ],
        rows,
    )


def _simple_table(frame: pd.DataFrame, columns: list[str], headers: list[str], *, limit: int = 80) -> str:
    if frame.empty:
        return "<p>No rows.</p>"
    rows = []
    for _, row in frame.head(limit).iterrows():
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                cells.append(_fmt_num(value, 2))
            elif column.endswith("pct"):
                cells.append(_fmt_pct_value(value))
            else:
                cells.append(_escape(value))
        rows.append(cells)
    return _table(headers, rows)


def _html_report(
    run_dir: Path,
    decision_frame: pd.DataFrame,
    outcomes: pd.DataFrame,
    funnel: pd.DataFrame,
    symbol_timeframe: pd.DataFrame,
    years: pd.DataFrame,
    samples: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    page = dashboard_page("v20.html")
    decision = run_summary["decision"]
    best = run_summary["best_variant"]
    subtitle = (
        "Research-only V20 lower-timeframe protection report. H4/H8/H12/D1/W1 LPFS signals "
        "are replayed through M30 bid/ask candles so a 0.9R touch only locks 0.5R when a later "
        "M30 candle could plausibly accept the stop modification."
    )
    pass_fail = "PASS" if bool(best.get("live_design_candidate", False)) else "FAIL"
    symbol_table = _simple_table(
        symbol_timeframe.sort_values("total_net_r_delta_vs_control", ascending=False),
        ["tp_near_variant_id", "symbol", "timeframe", "trades", "total_net_r_delta_vs_control", "profit_factor"],
        ["Variant", "Symbol", "TF", "Trades", "R Delta", "PF"],
        limit=40,
    )
    year_table = _simple_table(
        years.sort_values(["tp_near_variant_id", "exit_year"]),
        ["tp_near_variant_id", "exit_year", "trades", "total_net_r_delta_vs_control", "total_net_r"],
        ["Variant", "Year", "Trades", "R Delta", "Total R"],
        limit=80,
    )
    funnel_table = _simple_table(
        funnel,
        [
            "tp_near_variant_id",
            "triggered",
            "activated",
            "activation_rate_of_triggers",
            "rejected_too_late",
            "rejected_min_stop_distance",
            "protected_stop_exits",
        ],
        ["Variant", "Triggered", "Activated", "Activation Rate", "Too Fast", "Min Stop", "Lock-Stop Exits"],
    )
    sample_table = _simple_table(
        samples,
        [
            "tp_near_variant_id",
            "outcome",
            "symbol",
            "timeframe",
            "side",
            "signal_index",
            "control_exit_reason",
            "control_net_r",
            "variant_exit_reason",
            "variant_net_r",
            "net_r_delta_vs_control",
        ],
        ["Variant", "Outcome", "Symbol", "TF", "Side", "Signal", "Control Exit", "Control R", "Variant Exit", "Variant R", "Delta"],
        limit=80,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V20 Protection Realism - by Cody</title>
  <style>
    {dashboard_base_css()}
    {experiment_summary_css()}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V20 Protection Realism - by Cody",
      subtitle_html=_escape(subtitle),
      current_page="v20.html",
      section_links=[
          ("#decision", "Decision"),
          ("#ranking", "Ranking"),
          ("#funnel", "Funnel"),
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
        <div class="kpi"><span>Best Raw Research Variant</span><strong>{_escape(best["tp_near_variant_id"])}</strong><small>{_escape(pass_fail)} V20 gate; not a live rule</small></div>
        <div class="kpi"><span>R Delta vs M30 Control</span><strong class="{_metric_class(best["total_net_r_delta"])}">{_fmt_num(best["total_net_r_delta"], 1)}</strong><small>same M30 replay path</small></div>
        <div class="kpi"><span>Activation Rate</span><strong>{_fmt_num(float(best["activation_rate_of_triggers"]) * 100.0, 1)}%</strong><small>activated / 0.9R trigger touches</small></div>
        <div class="kpi"><span>Reserved DD / Worst Month</span><strong>{_fmt_pct_value(best["efficient_reserved_max_drawdown_pct"])} / {_fmt_pct_value(best["efficient_worst_month_pct"])}</strong><small>V15 bucket sizing view</small></div>
      </div>
    </section>
    <section id="ranking">
      <h2>Variant Ranking</h2>
      <p>Rows compare each stop-protection variant against the M30 replay control. A fast 0.9R touch that retreats before a later M30 modification is counted as unprotected.</p>
      {_decision_table(decision_frame)}
    </section>
    <section id="funnel">
      <h2>Protection Funnel</h2>
      <p>This is the live-design realism check: trigger touches, successful stop activations, too-fast misses, and broker min-distance blocks.</p>
      {funnel_table}
    </section>
    <section id="robustness">
      <h2>Robustness</h2>
      <h3>Symbol / Timeframe Winners And Losers</h3>
      {symbol_table}
      <h3>Year-By-Year Stability</h3>
      {year_table}
    </section>
    <section id="samples">
      <h2>Changed-Trade Samples</h2>
      {sample_table}
    </section>
    <section id="follow-up">
      <h2>Follow-Up Recommendation</h2>
      <p class="callout">{_escape(decision["follow_up"])}</p>
    </section>
    <section id="rules">
      <h2>Rules Tested</h2>
      <ul>
        <li>Signal baseline stays V15/V13: LP3, H4/H8/H12/D1/W1, 0.5 signal-candle pullback, FS structure stop, 1R target, 6-bar entry window.</li>
        <li>M30 replay finds the first bid/ask entry touch inside the same 6-bar higher-timeframe entry window.</li>
        <li>The default stress variants never move the stop inside the same M30 candle; activation begins on a later M30 candle.</li>
        <li>The same-M30 assumed variant is an optimistic upper bound for the live 30-second loop. It can show whether the idea deserves M1/tick validation, but it is not direct live evidence.</li>
        <li>If price retreats too far before activation, the stop update is rejected as too late and the original bracket remains.</li>
        <li>Optional min-stop-distance variants require current price to be at least a spread multiple away from the proposed 0.5R stop.</li>
        <li>Same-bar stop/target conflict remains stop-first.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Generated from <code>{_escape(run_dir)}</code>. Research-only; no live execution imports.</footer>
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
    replay_timeframe = normalize_timeframe(str(config.get("replay_timeframe", "M30")))
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
        try:
            replay_frame = _load_backtest_frame(
                dataset_config.data_root,
                symbol,
                replay_timeframe,
                drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
            )
        except Exception as exc:
            for timeframe in timeframes:
                dataset_rows.append({"symbol": symbol, "timeframe": timeframe, "status": "failed", "error": f"{replay_timeframe} replay load failed: {exc}"})
            print(f"{symbol} {replay_timeframe}: failed={exc}")
            continue
        for timeframe in timeframes:
            try:
                frame = _load_backtest_frame(
                    dataset_config.data_root,
                    symbol,
                    timeframe,
                    drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
                )
                result = run_lp_force_strike_m30_protection_realism_on_frame(
                    frame,
                    replay_frame,
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
                        "replay_timeframe": replay_timeframe,
                        "pivot_strength": pivot_strength,
                        "status": "ok",
                        "rows": int(len(frame)),
                        "replay_rows": int(len(replay_frame)),
                        "signals": int(len(result.signals)),
                        "variant_trades": int(len(result.trades)),
                        "variant_skipped": int(len(result.skipped)),
                    }
                )
                print(f"{symbol} {timeframe}->M30 LP{pivot_strength}: rows={len(frame)} signals={len(result.signals)} variant_trades={len(result.trades)}")
            except Exception as exc:
                dataset_rows.append({"symbol": symbol, "timeframe": timeframe, "replay_timeframe": replay_timeframe, "status": "failed", "error": str(exc)})
                print(f"{symbol} {timeframe}: failed={exc}")

    trades = pd.DataFrame(all_trade_rows)
    if trades.empty:
        raise ValueError("V20 produced no trades.")
    control = trades[trades["tp_near_variant_id"].eq(CONTROL_VARIANT_ID)].copy()
    if control.empty:
        raise ValueError("V20 requires a control_bid_ask control variant.")

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
    funnel = _protection_funnel(trades)
    samples = _changed_trade_samples(trades)
    decision_frame = _decision_frame(
        summary,
        delta,
        outcome_breakdown,
        bucket_summary,
        funnel,
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
            "replay_timeframe": replay_timeframe,
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
    _write_csv(run_dir / "protection_outcome_breakdown.csv", outcome_breakdown)
    _write_csv(run_dir / "protection_funnel.csv", funnel)
    _write_csv(run_dir / "symbol_timeframe_breakdown.csv", symbol_timeframe)
    _write_csv(run_dir / "year_breakdown.csv", years)
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
        for line in _html_report(run_dir, decision_frame, outcome_breakdown, funnel, symbol_timeframe, years, samples, run_summary).splitlines()
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
    outcomes = _read_csv(run_dir / "protection_outcome_breakdown.csv")
    funnel = _read_csv(run_dir / "protection_funnel.csv")
    symbol_timeframe = _read_csv(run_dir / "symbol_timeframe_breakdown.csv")
    years = _read_csv(run_dir / "year_breakdown.csv")
    samples = _read_csv(run_dir / "changed_trade_samples.csv")
    run_summary = _read_json(run_dir / "run_summary.json")
    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, decision_frame, outcomes, funnel, symbol_timeframe, years, samples, run_summary).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V20 lower-timeframe protection realism study.")
    parser.add_argument("--config", help="Path to V20 protection realism config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. H4,D1.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v20.html.")
    parser.add_argument("--render-run-dir", help="Existing V20 run directory to render without rerunning.")
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
