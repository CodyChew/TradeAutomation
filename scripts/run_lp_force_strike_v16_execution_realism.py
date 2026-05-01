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

from lp_force_strike_dashboard_metadata import (  # noqa: E402
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    experiment_summary_css,
    experiment_summary_html,
    metric_glossary_html,
)
from run_lp_force_strike_bucket_sensitivity_experiment import (  # noqa: E402
    _baseline_row,
    _efficiency_recommendation,
    _recommendation,
    run_bucket_sensitivity_analysis,
)
from run_lp_force_strike_experiment import (  # noqa: E402
    _candidate_rows,
    _cost_config,
    _load_backtest_frame,
    _parse_csv_arg,
    _selected_symbols,
    _selected_timeframes,
    _signal_row,
    _summary_rows_from_report_rows,
)
from run_lp_force_strike_risk_sizing_experiment import (  # noqa: E402
    _fmt_int,
    _fmt_num,
    _fmt_pct_value,
    _metric_class,
    _read_csv,
    _read_json,
    _table,
    _write_csv,
    _write_json,
    filter_baseline_trades,
)
from lp_force_strike_strategy_lab import (  # noqa: E402
    ExecutionRealismVariant,
    SkippedTrade,
    make_trade_model_candidates,
    run_lp_force_strike_execution_realism_on_frame,
    trade_report_row,
)
from market_data_lab import load_dataset_config, normalize_timeframe  # noqa: E402


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _pct_token(value: float) -> str:
    return f"{float(value):.2f}".replace(".", "p")


def _variant_label(variant_id: str) -> str:
    label = variant_id.replace("bid_ask_buffer_", "Buffer ").replace("x", "x spread")
    return "Bid/Ask " + label


def _variant_sort_key(value: str) -> float:
    token = value.replace("bid_ask_buffer_", "").replace("x", "").replace("p", ".")
    try:
        return float(token)
    except ValueError:
        return 999.0


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
        raise ValueError("V16 expects exactly one baseline trade-model candidate.")
    return candidates[0]


def _trade_row(trade, *, pivot_strength: int) -> dict[str, Any]:
    row = trade_report_row(trade)
    base_candidate_id = str(row.get("candidate_id", ""))
    variant_id = str(row.get("meta_execution_variant_id", ""))
    row["base_candidate_id"] = base_candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["execution_model"] = str(row.get("meta_execution_model", ""))
    row["execution_variant_id"] = variant_id
    row["stop_buffer_spread_mult"] = float(row.get("meta_stop_buffer_spread_mult", 0.0) or 0.0)
    row["trade_key"] = _trade_key(row)
    return row


def _skipped_row(skipped: SkippedTrade, candidate: Any, *, pivot_strength: int) -> dict[str, Any]:
    row = skipped.to_dict()
    detail = str(row.get("detail", ""))
    variant_id = ""
    for token in detail.split(";"):
        token = token.strip()
        if token.startswith("execution_variant_id="):
            variant_id = token.split("=", 1)[1]
            break
    row["base_candidate_id"] = candidate.candidate_id
    row["candidate_id"] = candidate.candidate_id
    row["pivot_strength"] = int(pivot_strength)
    row["execution_model"] = "bid_ask"
    row["execution_variant_id"] = variant_id
    return row


def _trade_key(row: pd.Series | dict[str, Any]) -> str:
    get = row.get if isinstance(row, dict) else row.get
    return "|".join(
        [
            str(get("symbol")),
            str(get("timeframe")),
            str(get("side")),
            str(int(float(get("signal_index")))),
            str(int(float(get("pivot_strength")))),
            str(get("base_candidate_id")),
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
    for optional in ("meta_signal_spread_to_risk", "meta_signal_spread_points", "meta_signal_spread_price", "risk_distance"):
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
            }
        )
        if "stop_buffer_spread_mult" in group.columns:
            row["stop_buffer_spread_mult"] = float(pd.to_numeric(group["stop_buffer_spread_mult"], errors="coerce").median())
        if "meta_signal_spread_to_risk" in group.columns:
            row["avg_signal_spread_to_risk_pct"] = float(group["meta_signal_spread_to_risk"].mean() * 100.0)
        if "meta_signal_spread_points" in group.columns:
            row["avg_signal_spread_points"] = float(group["meta_signal_spread_points"].mean())
        if "meta_signal_spread_price" in group.columns:
            row["avg_signal_spread_price"] = float(group["meta_signal_spread_price"].mean())
        if "risk_distance" in group.columns:
            row["avg_risk_distance"] = float(group["risk_distance"].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _compare_variant_to_baseline(baseline: pd.DataFrame, variant: pd.DataFrame, variant_id: str) -> dict[str, Any]:
    base = baseline.copy()
    current = variant.copy()
    if base.empty:
        raise ValueError("Baseline trade frame is empty.")
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
        "execution_variant_id": variant_id,
        "baseline_trades": int(len(base)),
        "variant_trades": int(len(current)),
        "common_trades": int(len(common)),
        "missing_from_variant": int(len(missing)),
        "added_in_variant": int(len(added)),
        "exit_reason_changed": int(exit_changed),
        "win_loss_sign_changed": int(sign_changed),
        "baseline_total_net_r": float(pd.to_numeric(base["net_r"], errors="coerce").fillna(0.0).sum()),
        "variant_total_net_r": float(pd.to_numeric(current["net_r"], errors="coerce").fillna(0.0).sum()),
        "total_net_r_delta": float(pd.to_numeric(current["net_r"], errors="coerce").fillna(0.0).sum() - pd.to_numeric(base["net_r"], errors="coerce").fillna(0.0).sum()),
        "common_net_r_delta": float(common_delta),
    }


def _run_bucket_sensitivity_by_variant(
    trades: pd.DataFrame,
    v15_config: dict[str, Any],
    run_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    combined_summaries = []
    for variant_id in sorted(trades["execution_variant_id"].dropna().unique(), key=_variant_sort_key):
        variant_trades = trades[trades["execution_variant_id"].eq(variant_id)].copy()
        summary, timeframe_rows, ticker_rows = run_bucket_sensitivity_analysis(variant_trades, v15_config)
        recommended = _recommendation(summary)
        efficient = _efficiency_recommendation(summary)
        baseline = _baseline_row(summary, v15_config)
        summary = summary.copy()
        summary["execution_variant_id"] = variant_id
        combined_summaries.append(summary)
        _write_csv(run_dir / f"v15_bucket_summary__{variant_id}.csv", summary)
        _write_csv(run_dir / f"v15_timeframe_contribution__{variant_id}.csv", timeframe_rows)
        _write_csv(run_dir / f"v15_ticker_contribution__{variant_id}.csv", ticker_rows)
        rows.append(
            {
                "execution_variant_id": variant_id,
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


def _fmt_pf(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return _fmt_num(value)


def _aggregate_rows(summary: pd.DataFrame, delta: pd.DataFrame) -> list[list[Any]]:
    merged = summary.merge(delta, on="execution_variant_id", how="left")
    rows = []
    for _, row in merged.sort_values("stop_buffer_spread_mult").iterrows():
        rows.append(
            [
                _escape(_variant_label(str(row["execution_variant_id"]))),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"]), _metric_class(row["total_net_r"])),
                (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                _fmt_pf(row["profit_factor"]),
                _fmt_int(row["missing_from_variant"]),
                (_fmt_num(row["total_net_r_delta"]), _metric_class(row["total_net_r_delta"])),
                f"{float(row.get('avg_signal_spread_to_risk_pct', 0.0)):.2f}%",
            ]
        )
    return rows


def _bucket_rows(bucket_summary: pd.DataFrame) -> list[list[Any]]:
    rows = []
    for _, row in bucket_summary.sort_values("execution_variant_id", key=lambda s: s.map(_variant_sort_key)).iterrows():
        rows.append(
            [
                _escape(_variant_label(str(row["execution_variant_id"]))),
                _escape(row["efficient_schedule_id"]),
                (_fmt_pct_value(row["efficient_total_return_pct"]), _metric_class(row["efficient_total_return_pct"])),
                _fmt_pct_value(row["efficient_reserved_max_drawdown_pct"]),
                _fmt_pct_value(row["efficient_max_reserved_open_risk_pct"]),
                _fmt_pct_value(row["efficient_worst_month_pct"]),
                _fmt_num(row["efficient_return_to_reserved_drawdown"]),
                "yes" if bool(row["efficient_passes_practical_filters"]) else "no",
            ]
        )
    return rows


def _spread_rows(spread_summary: pd.DataFrame) -> list[list[Any]]:
    if spread_summary.empty:
        return []
    data = spread_summary.copy()
    data["spread_pressure"] = pd.to_numeric(data.get("avg_signal_spread_to_risk_pct"), errors="coerce").fillna(0.0)
    data = data[data["execution_variant_id"].eq("bid_ask_buffer_0x")]
    data = data.sort_values(["spread_pressure", "trades"], ascending=[False, False]).head(25)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"]), _metric_class(row["total_net_r"])),
                _fmt_num(row["avg_net_r"]),
                f"{float(row['spread_pressure']):.2f}%",
                _fmt_num(row.get("avg_signal_spread_points")),
            ]
        )
    return rows


def _html_report(
    run_dir: Path,
    aggregate: pd.DataFrame,
    delta: pd.DataFrame,
    spread_summary: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    page = dashboard_page("v16.html")
    no_buffer = run_summary["no_buffer"]
    best = run_summary["best_buffer"]
    conclusion = run_summary["decision"]
    subtitle = (
        "Research-only V16 report generated from local historical candle data. "
        "OHLC is treated as Bid, Ask is approximated as Bid plus each candle's stored spread, "
        "and no MT5 live state or orders are touched."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V16 Execution Realism - by Cody</title>
  <style>
    {dashboard_base_css()}
    {experiment_summary_css()}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V16 Execution Realism - by Cody",
      subtitle_html=_escape(subtitle),
      current_page="v16.html",
      section_links=[
          ("#decision", "Decision"),
          ("#trade-r", "Trade R"),
          ("#buckets", "Buckets"),
          ("#spread", "Spread Impact"),
          ("#rules", "Rules"),
      ],
  )}
  <main>
    {experiment_summary_html(page)}
    <section id="decision">
      <h2>Decision Read</h2>
      <p class="callout"><strong>{_escape(conclusion["headline"])}</strong> {_escape(conclusion["detail"])}</p>
      <div class="kpi-grid">
        <div class="kpi"><span>No-buffer total R delta</span><strong class="{_metric_class(no_buffer["total_net_r_delta"])}">{_fmt_num(no_buffer["total_net_r_delta"])}</strong><small>vs V15 OHLC baseline</small></div>
        <div class="kpi"><span>No-buffer trade count</span><strong>{_fmt_int(no_buffer["variant_trades"])}</strong><small>{_fmt_int(no_buffer["missing_from_variant"])} missed vs OHLC</small></div>
        <div class="kpi"><span>Best practical buffer</span><strong>{_escape(_variant_label(best["execution_variant_id"]))}</strong><small>by return/reserved-DD</small></div>
        <div class="kpi"><span>Best efficient return</span><strong class="{_metric_class(best["efficient_total_return_pct"])}">{_fmt_pct_value(best["efficient_total_return_pct"])}</strong><small>reserved DD {_fmt_pct_value(best["efficient_reserved_max_drawdown_pct"])}</small></div>
      </div>
    </section>
    <section id="trade-r">
      <h2>Trade-Level Bid/Ask Result</h2>
      <p>This compares closed-trade R before position sizing. A negative delta means bid/ask mechanics or stop buffers reduced raw R versus the current V15 OHLC trade file.</p>
      {_table(
          ["Variant", "Trades", "Total R", "Avg R", "PF", "Missed", "R Delta", "Avg Spread/R"],
          _aggregate_rows(aggregate, delta),
      )}
    </section>
    <section id="buckets">
      <h2>V15 Bucket Sensitivity Rerun</h2>
      <p>Each variant is fed through the existing V15 risk-bucket pipeline, using the same practical filters: reserved DD <= 10%, max reserved open risk <= 6%, worst month >= -5%.</p>
      {_table(
          ["Variant", "Efficient Schedule", "Return", "Reserved DD", "Max Open Risk", "Worst Month", "Return/DD", "Practical"],
          _bucket_rows(bucket_summary),
      )}
    </section>
    <section id="spread">
      <h2>Highest Spread Pressure Pockets</h2>
      <p>No-buffer bid/ask rows sorted by average signal-candle spread as a share of trade risk. This is where spread realism matters most.</p>
      {_table(
          ["Symbol", "TF", "Trades", "Total R", "Avg R", "Avg Spread/R", "Avg Spread Pts"],
          _spread_rows(spread_summary),
      )}
    </section>
    <section id="rules">
      <h2>Execution Rules Tested</h2>
      <ul>
        <li>OHLC is interpreted as Bid; Ask OHLC is Bid OHLC plus that bar's stored <code>spread_points * point</code>.</li>
        <li>Long entry requires Ask low <= BUY LIMIT entry. Long stop/target uses Bid touches.</li>
        <li>Short entry requires Bid high >= SELL LIMIT entry. Short stop/target uses Ask touches.</li>
        <li>Same-bar TP/SL conflict remains stop-first.</li>
        <li>Stop buffers test 0.0x, 0.5x, 1.0x, 1.5x, and 2.0x signal-candle spread, with target recalculated to 1R.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Generated from <code>{_escape(run_dir)}</code>. Research-only; no MT5 live calls.</footer>
</body>
</html>
"""


def _decision(no_buffer: dict[str, Any], bucket_summary: pd.DataFrame, baseline_trade_count: int) -> tuple[dict[str, Any], dict[str, Any]]:
    practical = bucket_summary[bucket_summary["efficient_passes_practical_filters"].astype(bool)].copy()
    if practical.empty:
        practical = bucket_summary.copy()
    best = practical.sort_values(
        ["efficient_return_to_reserved_drawdown", "efficient_total_return_pct"],
        ascending=[False, False],
    ).iloc[0].to_dict()
    total_r_drop_pct = 0.0
    if float(no_buffer["baseline_total_net_r"]) > 0:
        total_r_drop_pct = -float(no_buffer["total_net_r_delta"]) / float(no_buffer["baseline_total_net_r"]) * 100.0
    trade_cut_pct = (
        (baseline_trade_count - int(no_buffer["variant_trades"])) / baseline_trade_count * 100.0
        if baseline_trade_count
        else 0.0
    )
    if total_r_drop_pct > 10.0:
        headline = "Bid/ask realism is a material raw-R regression."
        detail = f"No-buffer V16 reduced total R by {total_r_drop_pct:.1f}% versus the OHLC baseline."
    elif trade_cut_pct > 10.0:
        headline = "Bid/ask realism materially reduces fills."
        detail = f"No-buffer V16 cut trade count by {trade_cut_pct:.1f}% versus the OHLC baseline."
    elif str(best["execution_variant_id"]) == "bid_ask_buffer_0x":
        headline = "No stop buffer is currently favored."
        detail = "No-buffer bid/ask remains practical and is the best or most efficient practical variant in this run."
    else:
        headline = "A stop buffer has potential, but needs review before live changes."
        detail = f"{_variant_label(str(best['execution_variant_id']))} ranked best on efficient bucket return/reserved-DD."
    return {"headline": headline, "detail": detail}, best


def _run(config_path: Path, *, symbol_override: list[str] | None, timeframe_override: list[str] | None, output_dir: Path | None, docs_output: Path | None) -> int:
    config = _read_json(config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    symbols = _selected_symbols(dataset_config.symbols, config, symbol_override)
    timeframes = _selected_timeframes(dataset_config.timeframes, config, timeframe_override)
    pivot_strength = int(config.get("pivot_strength", 3))
    candidate = _make_candidate(config)
    variants = [
        ExecutionRealismVariant("bid_ask", float(value))
        for value in config.get("stop_buffer_spread_multipliers", [0.0, 0.5, 1.0, 1.5, 2.0])
    ]
    costs = _cost_config(config)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir or (REPO_ROOT / str(config["report_root"]) / timestamp)
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
                result = run_lp_force_strike_execution_realism_on_frame(
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
                print(
                    f"{symbol} {timeframe} LP{pivot_strength}: rows={len(frame)} signals={len(result.signals)} "
                    f"variant_trades={len(result.trades)} skipped={len(result.skipped)}"
                )
            except Exception as exc:
                dataset_rows.append({"symbol": symbol, "timeframe": timeframe, "status": "failed", "error": str(exc)})
                print(f"{symbol} {timeframe}: failed={exc}")

    trades = pd.DataFrame(all_trade_rows)
    if trades.empty:
        raise ValueError("V16 produced no trades.")

    v15_config = _read_json(REPO_ROOT / str(config["v15_bucket_config"]))
    baseline_path = REPO_ROOT / str(config.get("baseline_trades_path", v15_config["input_trades_path"]))
    baseline_trades = filter_baseline_trades(_read_csv(baseline_path), v15_config)
    baseline_trade_count = int(len(baseline_trades))

    aggregate = _aggregate_trade_metrics(trades, ["execution_variant_id"])
    spread_summary = _aggregate_trade_metrics(trades, ["execution_variant_id", "symbol", "timeframe"])
    delta_rows = []
    for variant_id in sorted(trades["execution_variant_id"].dropna().unique(), key=_variant_sort_key):
        delta_rows.append(_compare_variant_to_baseline(baseline_trades, trades[trades["execution_variant_id"].eq(variant_id)], str(variant_id)))
    delta = pd.DataFrame(delta_rows)
    bucket_summary, _bucket_all = _run_bucket_sensitivity_by_variant(trades, v15_config, run_dir)
    no_buffer_rows = delta[delta["execution_variant_id"].eq("bid_ask_buffer_0x")]
    if no_buffer_rows.empty:
        raise ValueError("V16 requires a 0.0x no-buffer variant for baseline comparison.")
    no_buffer = no_buffer_rows.iloc[0].to_dict()
    decision, best = _decision(no_buffer, bucket_summary, baseline_trade_count)

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
    _write_csv(
        run_dir / "candidates.csv",
        _candidate_rows([candidate], [pivot_strength], include_pivot_in_candidate_id=False),
    )
    _write_csv(run_dir / "summary_by_variant.csv", aggregate)
    _write_csv(run_dir / "spread_impact_by_variant_symbol_timeframe.csv", spread_summary)
    _write_csv(run_dir / "old_vs_new_trade_delta.csv", delta)
    _write_csv(run_dir / "summary_by_variant_timeframe.csv", _aggregate_trade_metrics(trades, ["execution_variant_id", "timeframe"]))
    _write_csv(run_dir / "summary_by_variant_symbol.csv", _aggregate_trade_metrics(trades, ["execution_variant_id", "symbol"]))
    _write_csv(run_dir / "summary_by_variant_from_standard_fields.csv", _summary_rows_from_report_rows(all_trade_rows, group_fields=["execution_variant_id"]))

    run_summary = {
        "run_dir": str(run_dir),
        "baseline_trades_path": str(baseline_path),
        "baseline_trade_count": baseline_trade_count,
        "signals": int(len(all_signal_rows)),
        "variant_trades": int(len(all_trade_rows)),
        "variant_skipped": int(len(all_skipped_rows)),
        "failed_datasets": int(sum(1 for row in dataset_rows if row.get("status") != "ok")),
        "no_buffer": no_buffer,
        "best_buffer": best,
        "decision": decision,
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = "\n".join(
        line.rstrip() for line in _html_report(run_dir, aggregate, delta, spread_summary, bucket_summary, run_summary).splitlines()
    ) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 1 if run_summary["failed_datasets"] else 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    aggregate = _read_csv(run_dir / "summary_by_variant.csv")
    delta = _read_csv(run_dir / "old_vs_new_trade_delta.csv")
    spread_summary = _read_csv(run_dir / "spread_impact_by_variant_symbol_timeframe.csv")
    bucket_summary = _read_csv(run_dir / "v15_bucket_sensitivity_by_variant.csv")
    run_summary = _read_json(run_dir / "run_summary.json")
    html_text = "\n".join(
        line.rstrip() for line in _html_report(run_dir, aggregate, delta, spread_summary, bucket_summary, run_summary).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V16 bid/ask execution-realism study.")
    parser.add_argument("--config", help="Path to V16 execution-realism config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. H4,D1.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v16.html.")
    parser.add_argument("--render-run-dir", help="Existing V16 run directory to render without rerunning.")
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
