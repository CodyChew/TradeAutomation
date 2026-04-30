from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
from itertools import product
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    experiment_summary_css,
    experiment_summary_html,
    metric_glossary_html,
)
from run_lp_force_strike_risk_sizing_experiment import (
    _fmt_int,
    _fmt_num,
    _fmt_pct_value,
    _metric_class,
    _read_csv,
    _read_json,
    _risk_label,
    _table,
    _write_csv,
    _write_json,
    analyze_schedule,
    filter_baseline_trades,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _pct_token(value: float) -> str:
    return f"{float(value):.2f}".replace(".", "p")


def expand_bucket_schedules(config: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = config["buckets"]
    schedules: list[dict[str, Any]] = []
    for values in product(*[bucket["risk_pct_values"] for bucket in buckets]):
        risk_by_timeframe: dict[str, float] = {}
        bucket_risks: dict[str, float] = {}
        label_parts = []
        id_parts = []
        for bucket, value in zip(buckets, values):
            risk_pct = float(value)
            bucket_id = str(bucket["bucket_id"])
            bucket_risks[bucket_id] = risk_pct
            id_parts.append(f"{bucket_id}{_pct_token(risk_pct)}")
            label_parts.append(f"{bucket['label']} {_fmt_pct_value(risk_pct)}")
            for timeframe in bucket["timeframes"]:
                risk_by_timeframe[str(timeframe)] = risk_pct

        schedule_id = "bucket_" + "_".join(id_parts)
        schedules.append(
            {
                "schedule_id": schedule_id,
                "label": " / ".join(label_parts),
                "kind": "timeframe",
                "risk_by_timeframe": risk_by_timeframe,
                "bucket_risks": bucket_risks,
            }
        )
    return schedules


def _bucket_columns(config: dict[str, Any]) -> dict[str, str]:
    columns: dict[str, str] = {}
    for bucket in config["buckets"]:
        bucket_id = str(bucket["bucket_id"])
        if bucket_id == "ltf":
            columns[bucket_id] = "lower_risk_pct"
        elif bucket_id == "h12_d1":
            columns[bucket_id] = "middle_risk_pct"
        elif bucket_id == "w1":
            columns[bucket_id] = "w1_risk_pct"
        else:
            columns[bucket_id] = f"{bucket_id}_risk_pct"
    return columns


def _passes_practical_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    max_reserved_dd = float(filters.get("max_reserved_drawdown_pct", float("inf")))
    max_open_risk = float(filters.get("max_reserved_open_risk_pct", float("inf")))
    min_worst_month = float(filters.get("min_worst_month_pct", float("-inf")))
    return (
        float(row["reserved_max_drawdown_pct"]) <= max_reserved_dd
        and float(row["max_reserved_open_risk_pct"]) <= max_open_risk
        and float(row["worst_month_pct"]) >= min_worst_month
    )


def run_bucket_sensitivity_analysis(
    trades: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline = filter_baseline_trades(trades, config)
    if baseline.empty:
        raise ValueError("No trades matched the configured V13 baseline filters.")

    schedules = expand_bucket_schedules(config)
    bucket_columns = _bucket_columns(config)
    filters = config.get("practical_filters", {})
    summary_rows = []
    timeframe_frames = []
    ticker_frames = []

    for schedule in schedules:
        row, timeframe, ticker = analyze_schedule(baseline, schedule)
        for bucket_id, risk_pct in schedule["bucket_risks"].items():
            row[bucket_columns[bucket_id]] = float(risk_pct)
        row["passes_practical_filters"] = _passes_practical_filters(row, filters)
        summary_rows.append(row)
        timeframe_frames.append(timeframe)
        ticker_frames.append(ticker)

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values(
        ["passes_practical_filters", "total_return_pct", "return_to_reserved_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    timeframe_rows = pd.concat(timeframe_frames, ignore_index=True) if timeframe_frames else pd.DataFrame()
    ticker_rows = pd.concat(ticker_frames, ignore_index=True) if ticker_frames else pd.DataFrame()
    return summary, timeframe_rows, ticker_rows


def _recommendation(summary: pd.DataFrame) -> pd.Series:
    practical = summary[summary["passes_practical_filters"].astype(bool)].copy()
    if practical.empty:
        return summary.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False).iloc[0]
    return practical.sort_values(["total_return_pct", "return_to_reserved_drawdown"], ascending=False).iloc[0]


def _efficiency_recommendation(summary: pd.DataFrame) -> pd.Series:
    practical = summary[summary["passes_practical_filters"].astype(bool)].copy()
    if practical.empty:
        practical = summary
    return practical.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False).iloc[0]


def _baseline_row(summary: pd.DataFrame, config: dict[str, Any]) -> pd.Series | None:
    baseline = config.get("baseline_schedule") or {}
    if not baseline:
        return None
    data = summary[
        summary["lower_risk_pct"].eq(float(baseline["lower_risk_pct"]))
        & summary["middle_risk_pct"].eq(float(baseline["middle_risk_pct"]))
        & summary["w1_risk_pct"].eq(float(baseline["w1_risk_pct"]))
    ]
    if data.empty:
        return None
    row = data.iloc[0].copy()
    row["schedule_label"] = baseline.get("label", row["schedule_label"])
    return row


def _summary_rows(frame: pd.DataFrame) -> list[list[Any]]:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            [
                _fmt_pct_value(row["lower_risk_pct"]),
                _fmt_pct_value(row["middle_risk_pct"]),
                _fmt_pct_value(row["w1_risk_pct"]),
                (_fmt_pct_value(row["total_return_pct"]), _metric_class(row["total_return_pct"])),
                _fmt_pct_value(row["realized_max_drawdown_pct"]),
                _fmt_pct_value(row["reserved_max_drawdown_pct"]),
                _fmt_pct_value(row["max_reserved_open_risk_pct"]),
                (_fmt_pct_value(row["worst_month_pct"]), _metric_class(row["worst_month_pct"])),
                _fmt_num(row["return_to_reserved_drawdown"], 2),
                "Yes" if bool(row["passes_practical_filters"]) else "No",
            ]
        )
    return rows


def _leaderboard_table(frame: pd.DataFrame, *, limit: int = 20) -> str:
    data = frame.head(limit)
    return _table(
        [
            "H4/H8",
            "H12/D1",
            "W1",
            "Total Return",
            "Realized DD",
            "Reserved DD",
            "Max Open Risk",
            "Worst Month",
            "Return/DD",
            "Practical",
        ],
        _summary_rows(data),
    )


def _comparison_table(rows: list[pd.Series]) -> str:
    table_rows = []
    for row in rows:
        if row is None:
            continue
        table_rows.append(
            [
                _escape(row["schedule_label"]),
                _fmt_pct_value(row["lower_risk_pct"]),
                _fmt_pct_value(row["middle_risk_pct"]),
                _fmt_pct_value(row["w1_risk_pct"]),
                (_fmt_pct_value(row["total_return_pct"]), _metric_class(row["total_return_pct"])),
                _fmt_pct_value(row["realized_max_drawdown_pct"]),
                _fmt_pct_value(row["reserved_max_drawdown_pct"]),
                _fmt_pct_value(row["max_reserved_open_risk_pct"]),
                (_fmt_pct_value(row["worst_month_pct"]), _metric_class(row["worst_month_pct"])),
                _fmt_num(row["return_to_reserved_drawdown"], 2),
            ]
        )
    return _table(
        [
            "Schedule",
            "H4/H8",
            "H12/D1",
            "W1",
            "Total Return",
            "Realized DD",
            "Reserved DD",
            "Max Open Risk",
            "Worst Month",
            "Return/DD",
        ],
        table_rows,
    )


def _bucket_effect_table(summary: pd.DataFrame, column: str, label: str) -> str:
    rows = []
    for risk_pct in sorted(summary[column].dropna().unique()):
        data = summary[summary[column].eq(risk_pct)].copy()
        practical = data[data["passes_practical_filters"].astype(bool)].copy()
        best = practical.sort_values(["total_return_pct", "return_to_reserved_drawdown"], ascending=False).head(1)
        if best.empty:
            best = data.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False).head(1)
        best_row = best.iloc[0]
        rows.append(
            [
                _fmt_pct_value(risk_pct),
                _fmt_int(len(data)),
                _fmt_int(len(practical)),
                (_fmt_pct_value(best_row["total_return_pct"]), _metric_class(best_row["total_return_pct"])),
                _fmt_pct_value(best_row["reserved_max_drawdown_pct"]),
                _fmt_pct_value(best_row["max_reserved_open_risk_pct"]),
                (_fmt_pct_value(best_row["worst_month_pct"]), _metric_class(best_row["worst_month_pct"])),
                _fmt_num(best_row["return_to_reserved_drawdown"], 2),
            ]
        )
    return f"<h3>{_escape(label)}</h3>" + _table(
        [
            "Bucket Risk",
            "Grid Rows",
            "Practical Rows",
            "Best Return",
            "Best Reserved DD",
            "Best Max Open Risk",
            "Best Worst Month",
            "Best Return/DD",
        ],
        rows,
    )


def _heatmap_table(summary: pd.DataFrame, w1_risk: float) -> str:
    data = summary[summary["w1_risk_pct"].eq(w1_risk)].copy()
    lower_values = sorted(data["lower_risk_pct"].dropna().unique())
    middle_values = sorted(data["middle_risk_pct"].dropna().unique())
    rows = []
    for lower in lower_values:
        row = [_fmt_pct_value(lower)]
        for middle in middle_values:
            cell = data[data["lower_risk_pct"].eq(lower) & data["middle_risk_pct"].eq(middle)].iloc[0]
            practical = "Y" if bool(cell["passes_practical_filters"]) else "N"
            display = (
                f"{_fmt_pct_value(cell['total_return_pct'])}<br>"
                f"DD {_fmt_pct_value(cell['reserved_max_drawdown_pct'])}<br>"
                f"{practical}"
            )
            cell_class = "positive" if bool(cell["passes_practical_filters"]) else "neutral"
            row.append((display, cell_class))
        rows.append(row)
    return f"<h3>W1 {_fmt_pct_value(w1_risk)}</h3>" + _table(
        ["H4/H8 \\ H12/D1", *[_fmt_pct_value(value) for value in middle_values]],
        rows,
        classes="heat-table",
    )


def _heatmap_section(summary: pd.DataFrame) -> str:
    return "".join(_heatmap_table(summary, value) for value in sorted(summary["w1_risk_pct"].dropna().unique()))


def _contribution_table(frame: pd.DataFrame, field: str, schedule_id: str) -> str:
    data = frame[frame["schedule_id"] == schedule_id].copy()
    if data.empty:
        return "<p>No contribution rows are available.</p>"
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(row[field]),
                _fmt_int(row["trades"]),
                (_fmt_pct_value(row["total_return_pct"]), _metric_class(row["total_return_pct"])),
                _fmt_pct_value(row["avg_return_pct"]),
                f"{float(row['win_rate']) * 100.0:.1f}%",
                _fmt_num(row["profit_factor"], 2),
                f"{float(row['share_of_total_return']) * 100.0:.1f}%",
            ]
        )
    return _table([field.title(), "Trades", "Total Return", "Avg Return", "Win Rate", "PF", "Return Share"], rows)


def _kpi(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="kpi">
      <div class="kpi-label">{_escape(label)}</div>
      <div class="kpi-value">{_escape(value)}</div>
      <div class="kpi-note">{_escape(note)}</div>
    </div>
    """


def _run_config(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_config.json"
    if not path.exists():
        return {}
    payload = _read_json(path)
    return payload.get("config", payload)


def _html_report(
    run_dir: Path,
    summary: pd.DataFrame,
    timeframe_rows: pd.DataFrame,
    ticker_rows: pd.DataFrame,
    *,
    current_page: str,
) -> str:
    config = _run_config(run_dir)
    recommended = _recommendation(summary)
    efficient = _efficiency_recommendation(summary)
    baseline = _baseline_row(summary, config)
    practical = summary[summary["passes_practical_filters"].astype(bool)].copy()
    efficiency = summary.sort_values(["return_to_reserved_drawdown", "total_return_pct"], ascending=False)
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Bucket Sensitivity",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "Which 3-bucket risk ladder is strongest?",
            "setup": "Run-local bucket sensitivity dashboard.",
            "how_to_read": "Compare the practical shortlist, bucket effects, and heatmaps.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    filters = config.get("practical_filters", {})
    filter_note = (
        f"Practical rows require risk-reserved DD <= {_fmt_pct_value(filters.get('max_reserved_drawdown_pct'))}, "
        f"max open risk <= {_fmt_pct_value(filters.get('max_reserved_open_risk_pct'))}, and worst month >= "
        f"{_fmt_pct_value(filters.get('min_worst_month_pct'))}."
    )
    growth_row = recommended.copy()
    growth_row["schedule_label"] = "Highest-return practical row"
    efficient_row = efficient.copy()
    efficient_row["schedule_label"] = "Most-efficient practical row"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V15 Bucket Sensitivity - by Cody</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #627181;
      --line: #d8e0e8;
      --accent: #22577a;
      --good: #2e7d50;
      --bad: #a23b3b;
      --warn: #9b5f00;
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 Inter, Segoe UI, Roboto, Arial, sans-serif; min-width: 0; overflow-x: hidden; }}
    header {{ background: #17202a; color: white; padding: 28px max(18px, 5vw); border-bottom: 4px solid #57a773; }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(22px, 4vw, 28px); }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; overflow-wrap: anywhere; }}
    code {{ overflow-wrap: anywhere; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    nav a {{ color: white; text-decoration: none; border: 1px solid rgba(255,255,255,.25); padding: 7px 10px; border-radius: 6px; background: rgba(255,255,255,.08); min-height: 34px; }}
    nav a.active {{ background: #57a773; border-color: #57a773; color: #17202a; font-weight: 700; }}
    main {{ padding: 24px max(18px, 5vw) 48px; }}
    section {{ margin: 0 0 22px; padding: 20px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(23,32,42,.05); max-width: 100%; overflow-x: auto; }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    h3 {{ margin: 18px 0 8px; font-size: 15px; color: #34495e; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 12px; margin-bottom: 18px; }}
    .kpi {{ background: #f9fbfc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .kpi-note {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    .note {{ background: #f6f8f2; border-left: 4px solid #8aa936; padding: 12px 14px; color: #34412d; margin-bottom: 14px; }}
    .warning {{ background: #fff8e8; border-left-color: var(--warn); color: #4d3b13; }}
    {experiment_summary_css()}
    table {{ width: 100%; min-width: 960px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; vertical-align: top; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #455464; background: #f7f9fb; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .heat-table {{ min-width: 680px; }}
    .heat-table td {{ text-align: center; line-height: 1.35; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    {dashboard_base_css(table_min_width="960px")}
    footer {{ color: var(--muted); padding: 0 max(18px, 5vw) 28px; }}
    @media (max-width: 760px) {{
      header {{ padding: 22px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 16px 12px 34px; }}
      section {{ padding: 14px; margin-bottom: 16px; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .kpi {{ padding: 10px; }}
      .kpi-value {{ font-size: 20px; }}
      th, td {{ padding: 6px 7px; font-size: 12px; }}
    }}
    @media (max-width: 480px) {{
      .kpis {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V15 Bucket Sensitivity - by Cody",
      subtitle_html=f"Static V15 report generated from <code>{_escape(run_dir)}</code>. This page tests 64 risk ladders across H4/H8, H12/D1, and W1 buckets.",
      current_page=current_page,
      section_links=[
          ("#experiment-summary", "Snapshot"),
          ("#recommendation", "Recommendation"),
          ("#metric-glossary", "Glossary"),
          ("#practical", "Practical Rows"),
          ("#efficiency", "Efficiency"),
          ("#bucket-effects", "Buckets"),
          ("#heatmap", "Heatmap"),
          ("#all-grid", "All Rows"),
          ("#timeframes", "Timeframes"),
      ],
  )}
  <main>
    {experiment_summary_html(page_metadata)}
    {metric_glossary_html()}
    <section id="recommendation">
      <h2>Recommendation Card</h2>
      <div class="kpis">
        {_kpi("Top-Return H4/H8", _fmt_pct_value(recommended["lower_risk_pct"]), "lower-timeframe bucket")}
        {_kpi("Top-Return H12/D1", _fmt_pct_value(recommended["middle_risk_pct"]), "middle bucket")}
        {_kpi("Top-Return W1", _fmt_pct_value(recommended["w1_risk_pct"]), "weekly bucket")}
        {_kpi("Top Return", _fmt_pct_value(recommended["total_return_pct"]), "account percent")}
        {_kpi("Risk-Reserved DD", _fmt_pct_value(recommended["reserved_max_drawdown_pct"]), "full open risk reserved")}
        {_kpi("Practical Rows", f"{len(practical)}/{len(summary)}", "grid rows passing filters")}
      </div>
      <div class="note">{_escape(filter_note)}</div>
      {_comparison_table([growth_row, efficient_row, baseline])}
    </section>
    <section id="practical">
      <h2>Practical Return Leaderboard</h2>
      <div class="note">Rows are sorted by total return after applying the practical filters. Use this section to choose the next default ladder.</div>
      {_leaderboard_table(practical, limit=20) if not practical.empty else "<p>No rows passed the configured practical filters.</p>"}
    </section>
    <section id="efficiency">
      <h2>Efficiency Leaderboard</h2>
      <div class="note">Rows are sorted by return per point of risk-reserved drawdown. This highlights shape efficiency, not absolute growth.</div>
      {_leaderboard_table(efficiency, limit=20)}
    </section>
    <section id="bucket-effects">
      <h2>Bucket Effect Read</h2>
      <div class="note">Each bucket table shows, for that bucket risk level, the best row that passes practical filters. If none pass, it shows the most efficient row for that level.</div>
      {_bucket_effect_table(summary, "lower_risk_pct", "H4/H8 Bucket")}
      {_bucket_effect_table(summary, "middle_risk_pct", "H12/D1 Bucket")}
      {_bucket_effect_table(summary, "w1_risk_pct", "W1 Bucket")}
    </section>
    <section id="heatmap">
      <h2>Grid Heatmap By W1 Risk</h2>
      <div class="note">Each cell shows total return, risk-reserved DD, and whether the row passed practical filters.</div>
      {_heatmap_section(summary)}
    </section>
    <section id="all-grid">
      <h2>Full Grid Leaderboard</h2>
      {_leaderboard_table(summary, limit=64)}
    </section>
    <section id="timeframes">
      <h2>Recommended Ladder Timeframe Contribution</h2>
      {_contribution_table(timeframe_rows, "timeframe", str(recommended["schedule_id"]))}
    </section>
    <section id="tickers">
      <h2>Recommended Ladder Ticker Contribution</h2>
      {_contribution_table(ticker_rows, "symbol", str(recommended["schedule_id"]))}
    </section>
  </main>
  <footer>Generated from existing LP3 take-all trade rows. No MT5 data pull or signal rerun was performed.</footer>
</body>
</html>
"""


def _run(config_path: Path, *, docs_output: Path | None = None) -> int:
    config = _read_json(config_path)
    input_path = REPO_ROOT / str(config["input_trades_path"])
    trades = _read_csv(input_path)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / str(config["report_root"]) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary, timeframe_rows, ticker_rows = run_bucket_sensitivity_analysis(trades, config)
    recommended = _recommendation(summary)
    efficient = _efficiency_recommendation(summary)
    baseline = _baseline_row(summary, config)

    for row in summary.head(10).itertuples():
        print(
            f"{row.schedule_id}: total={row.total_return_pct:.2f}% "
            f"reserved_dd={row.reserved_max_drawdown_pct:.2f}% "
            f"max_open={row.max_reserved_open_risk_pct:.2f}% "
            f"practical={bool(row.passes_practical_filters)}"
        )

    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_csv(run_dir / "bucket_sensitivity_summary.csv", summary)
    _write_csv(run_dir / "timeframe_contribution.csv", timeframe_rows)
    _write_csv(run_dir / "ticker_contribution.csv", ticker_rows)
    run_summary = {
        "run_dir": str(run_dir),
        "input_trades_path": str(input_path),
        "summary_rows": int(len(summary)),
        "practical_rows": int(summary["passes_practical_filters"].sum()),
        "recommended_schedule_id": str(recommended["schedule_id"]),
        "recommended_lower_risk_pct": float(recommended["lower_risk_pct"]),
        "recommended_middle_risk_pct": float(recommended["middle_risk_pct"]),
        "recommended_w1_risk_pct": float(recommended["w1_risk_pct"]),
        "recommended_total_return_pct": float(recommended["total_return_pct"]),
        "recommended_reserved_max_drawdown_pct": float(recommended["reserved_max_drawdown_pct"]),
        "efficient_schedule_id": str(efficient["schedule_id"]),
        "efficient_lower_risk_pct": float(efficient["lower_risk_pct"]),
        "efficient_middle_risk_pct": float(efficient["middle_risk_pct"]),
        "efficient_w1_risk_pct": float(efficient["w1_risk_pct"]),
        "efficient_total_return_pct": float(efficient["total_return_pct"]),
        "efficient_reserved_max_drawdown_pct": float(efficient["reserved_max_drawdown_pct"]),
        "baseline_total_return_pct": None if baseline is None else float(baseline["total_return_pct"]),
        "baseline_reserved_max_drawdown_pct": None if baseline is None else float(baseline["reserved_max_drawdown_pct"]),
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = _html_report(
        run_dir,
        summary,
        timeframe_rows,
        ticker_rows,
        current_page="v15.html" if docs_output else "dashboard.html",
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    summary = _read_csv(run_dir / "bucket_sensitivity_summary.csv")
    timeframe_rows = _read_csv(run_dir / "timeframe_contribution.csv")
    ticker_rows = _read_csv(run_dir / "ticker_contribution.csv")
    html_text = _html_report(
        run_dir,
        summary,
        timeframe_rows,
        ticker_rows,
        current_page=docs_output.name,
    )
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V15 3-bucket risk sensitivity study.")
    parser.add_argument("--config", help="Path to bucket sensitivity config JSON.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v15.html.")
    parser.add_argument("--render-run-dir", help="Existing V15 run directory to render without rerunning.")
    args = parser.parse_args()

    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    if args.config is None:
        raise SystemExit("--config is required unless --render-run-dir is used")
    return _run(Path(args.config), docs_output=None if args.docs_output is None else Path(args.docs_output))


if __name__ == "__main__":
    raise SystemExit(main())
