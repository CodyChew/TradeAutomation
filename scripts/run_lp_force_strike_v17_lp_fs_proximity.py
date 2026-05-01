from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
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
    PROXIMITY_VARIANTS,
    add_proximity_columns,
    proximity_variant_label,
    proximity_variant_mask,
)


QUALITY_BUCKET_ORDER = {
    "touched": 0,
    "within_0p25_atr": 1,
    "within_0p50_atr": 2,
    "within_1p00_atr": 3,
    "farther_than_1p00_atr": 4,
    "unknown": 5,
}


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _profit_factor(values: pd.Series) -> float | None:
    gross_win = float(values[values > 0].sum())
    gross_loss = float(values[values < 0].sum())
    if gross_loss == 0:
        return None
    return gross_win / abs(gross_loss)


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


def _aggregate_trade_metrics(frame: pd.DataFrame, group_fields: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    data = frame.copy()
    data["net_r"] = pd.to_numeric(data["net_r"], errors="coerce").fillna(0.0)
    data["bars_held"] = pd.to_numeric(data["bars_held"], errors="coerce").fillna(0.0)
    for optional in ("proximity_gap_price", "proximity_gap_atr"):
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
        if "proximity_gap_price" in group.columns:
            row["avg_gap_price"] = float(group["proximity_gap_price"].mean())
        if "proximity_gap_atr" in group.columns:
            row["avg_gap_atr"] = float(group["proximity_gap_atr"].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _compare_variant_to_baseline(baseline: pd.DataFrame, variant: pd.DataFrame, variant_id: str) -> dict[str, Any]:
    base = baseline.copy()
    current = variant.copy()
    base["trade_key"] = base.apply(_trade_key, axis=1)
    current["trade_key"] = current.apply(_trade_key, axis=1)
    base = base.drop_duplicates("trade_key").set_index("trade_key")
    current = current.drop_duplicates("trade_key").set_index("trade_key")
    common = sorted(set(base.index).intersection(current.index))
    missing = sorted(set(base.index).difference(current.index))
    added = sorted(set(current.index).difference(base.index))
    baseline_total = float(base["net_r"].sum())
    variant_total = float(current["net_r"].sum())
    return {
        "proximity_variant_id": variant_id,
        "proximity_variant_label": proximity_variant_label(variant_id),
        "baseline_trades": int(len(base)),
        "variant_trades": int(len(current)),
        "common_trades": int(len(common)),
        "excluded_from_variant": int(len(missing)),
        "added_in_variant": int(len(added)),
        "trade_count_cut_pct": 0.0 if len(base) == 0 else float((len(base) - len(current)) / len(base) * 100.0),
        "baseline_total_net_r": baseline_total,
        "variant_total_net_r": variant_total,
        "total_net_r_delta": variant_total - baseline_total,
        "excluded_net_r": float(base.loc[missing, "net_r"].sum()) if missing else 0.0,
        "common_net_r": float(current.loc[common, "net_r"].sum()) if common else 0.0,
    }


def _variant_frames(baseline: pd.DataFrame, variants: list[str]) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for variant_id in variants:
        accepted = baseline[proximity_variant_mask(baseline, variant_id)].copy()
        accepted["proximity_variant_id"] = variant_id
        accepted["proximity_variant_label"] = proximity_variant_label(variant_id)
        frames[variant_id] = accepted
    return frames


def _bucket_rows_by_variant(variant_frames: dict[str, pd.DataFrame], bucket_config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_rows = []
    summary_rows = []
    for variant_id, trades in variant_frames.items():
        if trades.empty:
            continue
        summary, _, _ = run_bucket_sensitivity_analysis(trades, bucket_config)
        summary = summary.copy()
        summary.insert(0, "proximity_variant_id", variant_id)
        summary.insert(1, "proximity_variant_label", proximity_variant_label(variant_id))
        all_rows.append(summary)

        highest = _recommendation(summary).to_dict()
        efficient = _efficiency_recommendation(summary).to_dict()
        baseline = _baseline_row(summary, bucket_config)
        row = {
            "proximity_variant_id": variant_id,
            "proximity_variant_label": proximity_variant_label(variant_id),
            "trades": int(len(trades)),
            "highest_schedule_id": highest["schedule_id"],
            "highest_total_return_pct": highest["total_return_pct"],
            "highest_reserved_max_drawdown_pct": highest["reserved_max_drawdown_pct"],
            "highest_max_reserved_open_risk_pct": highest["max_reserved_open_risk_pct"],
            "highest_worst_month_pct": highest["worst_month_pct"],
            "highest_return_to_reserved_drawdown": highest["return_to_reserved_drawdown"],
            "highest_passes_practical_filters": bool(highest["passes_practical_filters"]),
            "efficient_schedule_id": efficient["schedule_id"],
            "efficient_total_return_pct": efficient["total_return_pct"],
            "efficient_reserved_max_drawdown_pct": efficient["reserved_max_drawdown_pct"],
            "efficient_max_reserved_open_risk_pct": efficient["max_reserved_open_risk_pct"],
            "efficient_worst_month_pct": efficient["worst_month_pct"],
            "efficient_return_to_reserved_drawdown": efficient["return_to_reserved_drawdown"],
            "efficient_passes_practical_filters": bool(efficient["passes_practical_filters"]),
        }
        if baseline is not None:
            row.update(
                {
                    "legacy_baseline_schedule_id": baseline["schedule_id"],
                    "legacy_baseline_total_return_pct": baseline["total_return_pct"],
                    "legacy_baseline_reserved_max_drawdown_pct": baseline["reserved_max_drawdown_pct"],
                    "legacy_baseline_max_reserved_open_risk_pct": baseline["max_reserved_open_risk_pct"],
                    "legacy_baseline_worst_month_pct": baseline["worst_month_pct"],
                    "legacy_baseline_passes_practical_filters": bool(baseline["passes_practical_filters"]),
                }
            )
        summary_rows.append(row)

    return (
        pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(),
        pd.DataFrame(summary_rows),
    )


def _decision(delta: pd.DataFrame, bucket_summary: pd.DataFrame, rules: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    current = delta[delta["proximity_variant_id"] == "current_v15"].iloc[0].to_dict()
    current_bucket = bucket_summary[bucket_summary["proximity_variant_id"] == "current_v15"].iloc[0].to_dict()
    practical = bucket_summary[bucket_summary["efficient_passes_practical_filters"].astype(bool)].copy()
    if practical.empty:
        best = current_bucket
    else:
        best = practical.sort_values(["efficient_return_to_reserved_drawdown", "efficient_total_return_pct"], ascending=[False, False]).iloc[0].to_dict()
    best_delta = delta[delta["proximity_variant_id"] == best["proximity_variant_id"]].iloc[0].to_dict()
    max_trade_cut = float(rules.get("max_trade_count_cut_pct", 20.0))
    max_return_drop = float(rules.get("max_total_return_drop_pct", 10.0))
    current_return = float(current_bucket["efficient_total_return_pct"])
    best_return = float(best["efficient_total_return_pct"])
    return_drop_pct = 0.0 if current_return <= 0 else max(0.0, (current_return - best_return) / current_return * 100.0)
    trade_cut_pct = float(best_delta["trade_count_cut_pct"])

    if best["proximity_variant_id"] == "current_v15":
        headline = "Keep current V15 unchanged."
        detail = "No LP-FS proximity filter beat the current V15 row on efficient return-to-reserved-drawdown."
    elif trade_cut_pct > max_trade_cut or return_drop_pct > max_return_drop:
        headline = "Do not add a hard proximity filter yet."
        detail = (
            f"{proximity_variant_label(best['proximity_variant_id'])} ranked efficiently, "
            f"but cuts {trade_cut_pct:.1f}% of trades or gives up {return_drop_pct:.1f}% efficient return."
        )
    else:
        headline = "A proximity filter has potential, but needs review before live changes."
        detail = (
            f"{proximity_variant_label(best['proximity_variant_id'])} improved efficient return/reserved-DD "
            f"while cutting {trade_cut_pct:.1f}% of trades."
        )
    return {"headline": headline, "detail": detail}, best


def _variant_table(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _escape(row["proximity_variant_label"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                (_fmt_num(row["avg_net_r"], 3), _metric_class(row["avg_net_r"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_int(row["target_exits"]),
                _fmt_int(row["stop_exits"] + row["same_bar_stop_exits"]),
                _fmt_num(row.get("avg_gap_atr"), 2),
            ]
        )
    return _table(["Variant", "Trades", "Total R", "Avg R", "PF", "TP", "SL", "Avg Gap ATR"], rows)


def _bucket_table(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _escape(row["proximity_variant_label"]),
                _escape(row["efficient_schedule_id"]),
                (_fmt_pct_value(row["efficient_total_return_pct"]), _metric_class(row["efficient_total_return_pct"])),
                _fmt_pct_value(row["efficient_reserved_max_drawdown_pct"]),
                _fmt_pct_value(row["efficient_max_reserved_open_risk_pct"]),
                (_fmt_pct_value(row["efficient_worst_month_pct"]), _metric_class(row["efficient_worst_month_pct"])),
                _fmt_num(row["efficient_return_to_reserved_drawdown"], 2),
                "yes" if bool(row["efficient_passes_practical_filters"]) else "no",
            ]
        )
    return _table(["Variant", "Efficient Schedule", "Return", "Reserved DD", "Max Open Risk", "Worst Month", "Return/DD", "Practical"], rows)


def _quality_table(frame: pd.DataFrame) -> str:
    rows = []
    data = frame.sort_values("quality_sort")
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row["proximity_quality_bucket"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                (_fmt_num(row["avg_net_r"], 3), _metric_class(row["avg_net_r"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_num(row.get("avg_gap_atr"), 2),
            ]
        )
    return _table(["Quality Bucket", "Trades", "Total R", "Avg R", "PF", "Avg Gap ATR"], rows)


def _delta_table(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _escape(row["proximity_variant_label"]),
                _fmt_int(row["variant_trades"]),
                _fmt_pct_value(row["trade_count_cut_pct"]),
                (_fmt_num(row["total_net_r_delta"], 1), _metric_class(row["total_net_r_delta"])),
                (_fmt_num(row["excluded_net_r"], 1), _metric_class(row["excluded_net_r"])),
            ]
        )
    return _table(["Variant", "Trades Kept", "Trade Cut", "Total R Delta", "Excluded R"], rows)


def _symbol_timeframe_table(frame: pd.DataFrame) -> str:
    current = frame[frame["proximity_variant_id"] == "strict_touch"].copy()
    if current.empty:
        return "<p>No strict-touch symbol/timeframe rows are available.</p>"
    current = current.sort_values(["total_net_r", "trades"], ascending=[True, False]).head(25)
    rows = []
    for _, row in current.iterrows():
        rows.append(
            [
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _fmt_int(row["trades"]),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                (_fmt_num(row["avg_net_r"], 3), _metric_class(row["avg_net_r"])),
                _fmt_num(row["profit_factor"], 3),
                _fmt_num(row.get("avg_gap_atr"), 2),
            ]
        )
    return _table(["Symbol", "TF", "Trades", "Total R", "Avg R", "PF", "Avg Gap ATR"], rows)


def _html_report(
    run_dir: Path,
    aggregate: pd.DataFrame,
    delta: pd.DataFrame,
    quality: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    symbol_timeframe: pd.DataFrame,
    run_summary: dict[str, Any],
) -> str:
    page = dashboard_page("v17.html")
    decision = run_summary["decision"]
    best = run_summary["best_variant"]
    subtitle = (
        "Research-only V17 report generated from the existing V15 OHLC trade rows. "
        "It filters by how close the Force Strike structure is to the selected LP; no MT5 live state or orders are touched."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V17 LP-FS Proximity - by Cody</title>
  <style>
    {dashboard_base_css()}
    {experiment_summary_css()}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V17 LP-FS Proximity - by Cody",
      subtitle_html=_escape(subtitle),
      current_page="v17.html",
      section_links=[
          ("#decision", "Decision"),
          ("#variants", "Variants"),
          ("#buckets", "Buckets"),
          ("#quality", "Quality"),
          ("#symbols", "Symbol/TF"),
          ("#rules", "Rules"),
      ],
  )}
  <main>
    {experiment_summary_html(page)}
    <section id="decision">
      <h2>Decision Read</h2>
      <p class="callout"><strong>{_escape(decision["headline"])}</strong> {_escape(decision["detail"])}</p>
      <div class="kpi-grid">
        <div class="kpi"><span>Baseline trades</span><strong>{_fmt_int(run_summary["baseline_trade_count"])}</strong><small>current V15 OHLC</small></div>
        <div class="kpi"><span>Best efficient variant</span><strong>{_escape(proximity_variant_label(best["proximity_variant_id"]))}</strong><small>by return/reserved-DD</small></div>
        <div class="kpi"><span>Best efficient return</span><strong class="{_metric_class(best["efficient_total_return_pct"])}">{_fmt_pct_value(best["efficient_total_return_pct"])}</strong><small>reserved DD {_fmt_pct_value(best["efficient_reserved_max_drawdown_pct"])}</small></div>
        <div class="kpi"><span>Best trade count</span><strong>{_fmt_int(best["trades"])}</strong><small>after proximity filter</small></div>
      </div>
    </section>
    <section id="variants">
      <h2>Trade-Level Proximity Result</h2>
      <p class="callout">These are raw closed-trade R results before account-risk sizing. Current V15 is included as the control row.</p>
      {_variant_table(aggregate)}
      <h3>Old vs Filtered Delta</h3>
      {_delta_table(delta)}
    </section>
    <section id="buckets">
      <h2>V15 Bucket Sensitivity Rerun</h2>
      <p>Each proximity variant is passed through the same V15 practical filters: reserved DD <= 10%, max reserved open risk <= 6%, worst month >= -5%.</p>
      {_bucket_table(bucket_summary)}
    </section>
    <section id="quality">
      <h2>Quality Buckets Without Filtering</h2>
      <p>This reads the current V15 trades by proximity bucket so the far-away structures can be judged before making a hard rule.</p>
      {_quality_table(quality)}
    </section>
    <section id="symbols">
      <h2>Strict-Touch Weakest Symbol/Timeframe Rows</h2>
      <p>Strict-touch rows sorted by total R. Use this to spot concentration if the filter removes too much diversity.</p>
      {_symbol_timeframe_table(symbol_timeframe)}
    </section>
    <section id="rules">
      <h2>Rules Tested</h2>
      <ul>
        <li>Current V15 uses LP3, all H4/H8/H12/D1/W1, 0.5 signal-candle pullback, FS structure stop, 1R target, fixed 6-bar signal window, and fixed 6-bar pullback wait.</li>
        <li>Strict touch for longs requires FS structure low <= LP support.</li>
        <li>Strict touch for shorts requires FS structure high >= LP resistance.</li>
        <li>Gap variants allow the structure to miss the LP by up to 0.25, 0.50, or 1.00 ATR.</li>
        <li>Rows with missing or zero ATR are marked unknown and are not accepted by gap filters unless they strictly touch.</li>
      </ul>
    </section>
    {metric_glossary_html()}
  </main>
  <footer>Generated from <code>{_escape(run_dir)}</code>. Research-only; no MT5 live calls.</footer>
</body>
</html>
"""


def _run(config_path: Path, *, output_dir: Path | None, docs_output: Path | None) -> int:
    config = _read_json(config_path)
    bucket_config = _read_json(REPO_ROOT / str(config["v15_bucket_config"]))
    input_path = REPO_ROOT / str(config["input_trades_path"])
    variants = [str(value) for value in config.get("proximity_variants", PROXIMITY_VARIANTS)]
    unsupported = [variant for variant in variants if variant not in PROXIMITY_VARIANTS]
    if unsupported:
        raise ValueError(f"Unsupported proximity variants: {unsupported}")

    run_dir = output_dir or REPO_ROOT / str(config["report_root"]) / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_trades = _read_csv(input_path)
    baseline = filter_baseline_trades(raw_trades, bucket_config)
    baseline = add_proximity_columns(baseline)
    if baseline.empty:
        raise ValueError("V17 baseline trade frame is empty.")

    variant_frames = _variant_frames(baseline, variants)
    trades = pd.concat(variant_frames.values(), ignore_index=True)
    aggregate = _aggregate_trade_metrics(trades, ["proximity_variant_id", "proximity_variant_label"])
    aggregate["sort_order"] = aggregate["proximity_variant_id"].map(lambda value: variants.index(str(value)))
    aggregate = aggregate.sort_values("sort_order").drop(columns=["sort_order"]).reset_index(drop=True)

    quality = _aggregate_trade_metrics(baseline, ["proximity_quality_bucket"])
    quality["quality_sort"] = quality["proximity_quality_bucket"].map(lambda value: QUALITY_BUCKET_ORDER.get(str(value), 99))
    quality = quality.sort_values("quality_sort").reset_index(drop=True)

    symbol_timeframe = _aggregate_trade_metrics(trades, ["proximity_variant_id", "proximity_variant_label", "symbol", "timeframe"])
    delta = pd.DataFrame([_compare_variant_to_baseline(baseline, frame, variant_id) for variant_id, frame in variant_frames.items()])
    bucket_all, bucket_summary = _bucket_rows_by_variant(variant_frames, bucket_config)
    decision, best = _decision(delta, bucket_summary, config.get("decision_rules", {}))

    _write_csv(run_dir / "baseline_trades_with_proximity.csv", baseline)
    _write_csv(run_dir / "trades_by_variant.csv", trades)
    _write_csv(run_dir / "summary_by_variant.csv", aggregate)
    _write_csv(run_dir / "summary_by_quality_bucket.csv", quality)
    _write_csv(run_dir / "summary_by_variant_symbol_timeframe.csv", symbol_timeframe)
    _write_csv(run_dir / "old_vs_filtered_trade_delta.csv", delta)
    _write_csv(run_dir / "v15_bucket_sensitivity_all_rows.csv", bucket_all)
    _write_csv(run_dir / "v15_bucket_sensitivity_by_variant.csv", bucket_summary)

    run_summary = {
        "run_dir": str(run_dir),
        "config_path": str(config_path),
        "config": config,
        "input_trades_path": str(input_path),
        "baseline_trade_count": int(len(baseline)),
        "variant_trade_rows": int(len(trades)),
        "decision": decision,
        "best_variant": best,
    }
    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, aggregate, delta, quality, bucket_summary, symbol_timeframe, run_summary).splitlines()
    ) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True, default=str))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    aggregate = _read_csv(run_dir / "summary_by_variant.csv")
    delta = _read_csv(run_dir / "old_vs_filtered_trade_delta.csv")
    quality = _read_csv(run_dir / "summary_by_quality_bucket.csv")
    bucket_summary = _read_csv(run_dir / "v15_bucket_sensitivity_by_variant.csv")
    symbol_timeframe = _read_csv(run_dir / "summary_by_variant_symbol_timeframe.csv")
    run_summary = _read_json(run_dir / "run_summary.json")
    html_text = "\n".join(
        line.rstrip()
        for line in _html_report(run_dir, aggregate, delta, quality, bucket_summary, symbol_timeframe, run_summary).splitlines()
    ) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V17 LP-FS proximity study.")
    parser.add_argument("--config", help="Path to V17 proximity config JSON.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v17.html.")
    parser.add_argument("--render-run-dir", help="Existing V17 run directory to render without rerunning.")
    args = parser.parse_args()
    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    if args.config is None:
        raise SystemExit("--config is required unless --render-run-dir is used")
    return _run(
        Path(args.config),
        output_dir=None if args.output_dir is None else Path(args.output_dir),
        docs_output=None if args.docs_output is None else Path(args.docs_output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
