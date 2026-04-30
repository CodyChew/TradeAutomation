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

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    experiment_summary_css,
    experiment_summary_html,
    metric_glossary_html,
)


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

from lp_force_strike_strategy_lab import (  # noqa: E402
    PortfolioRule,
    filter_trade_timeframes,
    run_portfolio_rule,
)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _write_csv(path: str | Path, frame: pd.DataFrame | list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    payload.to_csv(target, index=False)


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


def _fmt_int(value: Any) -> str:
    return f"{int(float(value)):,.0f}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{digits}f}"


def _fmt_r(value: Any) -> str:
    return f"{_fmt_num(value, 1)}R"


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100.0:,.1f}%"


def _metric_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _portfolio_rule(config: dict[str, Any]) -> PortfolioRule:
    payload = dict(config["portfolio_rule"])
    return PortfolioRule(
        portfolio_id=str(payload["portfolio_id"]),
        max_open_r=None if payload.get("max_open_r") is None else float(payload["max_open_r"]),
        enforce_one_per_symbol=bool(payload.get("enforce_one_per_symbol", False)),
        risk_r_per_trade=float(payload.get("risk_r_per_trade", 1.0)),
    )


def _timeframe_label(timeframes: list[str]) -> str:
    return "+".join(str(timeframe) for timeframe in timeframes)


def _timeframe_sets(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in config["timeframe_sets"]:
        timeframes = [str(value) for value in row["timeframes"]]
        rows.append(
            {
                "timeframe_set_id": str(row["timeframe_set_id"]),
                "timeframe_set_label": str(row.get("timeframe_set_label") or _timeframe_label(timeframes)),
                "timeframes": timeframes,
            }
        )
    return rows


def run_timeframe_mix_analysis(trades: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the configured V11 timeframe mix rows from an existing trade log."""

    main_pivot = int(config["main_pivot_strength"])
    diagnostic_pivots = [int(value) for value in config.get("diagnostic_pivot_strengths", [])]
    diagnostic_set_ids = {str(value) for value in config.get("diagnostic_timeframe_set_ids", [])}
    rule = _portfolio_rule(config)
    max_drawdown = float(config["max_drawdown_guardrail_r"])
    max_underwater = float(config["max_underwater_guardrail_days"])

    summary_rows: list[dict[str, Any]] = []
    accepted_frames: list[pd.DataFrame] = []
    for timeframe_set in _timeframe_sets(config):
        set_id = timeframe_set["timeframe_set_id"]
        timeframe_trades = filter_trade_timeframes(trades, timeframe_set["timeframes"])
        pivots = [main_pivot]
        if set_id in diagnostic_set_ids:
            pivots.extend(diagnostic_pivots)

        for pivot_strength in pivots:
            row_role = "main" if pivot_strength == main_pivot else "diagnostic"
            pivot_trades = timeframe_trades[timeframe_trades["pivot_strength"].astype(int) == pivot_strength].copy()
            result, selected = run_portfolio_rule(
                pivot_trades,
                rule=rule,
                pivot_strength=pivot_strength,
                max_drawdown_guardrail_r=max_drawdown,
                max_underwater_guardrail_days=max_underwater,
            )
            row = asdict(result)
            row.update(
                {
                    "row_role": row_role,
                    "timeframe_set_id": set_id,
                    "timeframe_set_label": timeframe_set["timeframe_set_label"],
                    "timeframes": _timeframe_label(timeframe_set["timeframes"]),
                }
            )
            summary_rows.append(row)
            if not selected.empty:
                selected = selected.copy()
                selected["row_role"] = row_role
                selected["timeframe_set_id"] = set_id
                selected["timeframe_set_label"] = timeframe_set["timeframe_set_label"]
                selected["timeframes"] = _timeframe_label(timeframe_set["timeframes"])
                accepted_frames.append(selected)

    summary = pd.DataFrame(summary_rows)
    accepted = pd.concat(accepted_frames, ignore_index=True) if accepted_frames else pd.DataFrame()
    return summary, accepted


def _table(headers: list[str], rows: list[list[Any]], *, classes: str = "") -> str:
    thead = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = []
        for value in row:
            if isinstance(value, tuple):
                display, cell_class = value
                cells.append(f'<td class="{cell_class}">{display}</td>')
            else:
                cells.append(f"<td>{value}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    class_attr = "data-table" + (f" {classes}" if classes else "")
    return f'<div class="table-scroll"><table class="{class_attr}"><thead><tr>{thead}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _summary_table(frame: pd.DataFrame, *, limit: int | None = None) -> str:
    data = frame.copy()
    if limit is not None:
        data = data.head(limit)
    if data.empty:
        return "<p>No rows are available for this section.</p>"

    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(str(row["timeframe_set_label"])),
                _escape(str(row["timeframes"])),
                _escape(f"LP{int(row['pivot_strength'])}"),
                _escape(str(row["row_role"])),
                _fmt_int(row["trades_accepted"]),
                _fmt_int(row["trades_available"]),
                (_fmt_r(row["total_net_r"]), _metric_class(row["total_net_r"])),
                _fmt_pct(row["win_rate"]),
                _fmt_num(row["profit_factor"], 2),
                (_fmt_r(row["max_drawdown_r"]), "negative" if float(row["max_drawdown_r"]) > 0 else "neutral"),
                _fmt_num(row["longest_underwater_days"], 0),
                _fmt_num(row["return_to_drawdown"], 2),
                "Yes" if bool(row["passed_guardrails"]) else "No",
            ]
        )
    return _table(
        [
            "Timeframe Set",
            "Timeframes",
            "LP",
            "Role",
            "Accepted",
            "Available",
            "Total R",
            "Win Rate",
            "PF",
            "Max DD",
            "Underwater Days",
            "Return/DD",
            "Pass",
        ],
        rows,
    )


def _kpi(label: str, value: str, note: str = "") -> str:
    return f"""
    <div class="kpi">
      <div class="kpi-label">{_escape(label)}</div>
      <div class="kpi-value">{_escape(value)}</div>
      <div class="kpi-note">{_escape(note)}</div>
    </div>
    """


def _main_rows(summary: pd.DataFrame) -> pd.DataFrame:
    return summary[summary["row_role"].astype(str) == "main"].copy()


def _diagnostic_rows(summary: pd.DataFrame) -> pd.DataFrame:
    return summary[summary["row_role"].astype(str) == "diagnostic"].copy()


def _best_passing_main(summary: pd.DataFrame) -> pd.DataFrame:
    main = _main_rows(summary)
    passed = main[main["passed_guardrails"].astype(bool)].copy()
    return passed.sort_values(["total_net_r", "return_to_drawdown"], ascending=False)


def _baseline_row(summary: pd.DataFrame) -> pd.DataFrame:
    main = _main_rows(summary)
    return main[main["timeframe_set_id"].astype(str) == "all"].copy()


def _delta(value: float) -> str:
    prefix = "+" if value >= 0 else ""
    return f"{prefix}{value:,.1f}"


def _baseline_comparison(summary: pd.DataFrame) -> str:
    baseline = _baseline_row(summary)
    best = _best_passing_main(summary).head(1)
    if baseline.empty or best.empty:
        return "<p>Baseline or best passing row is unavailable.</p>"

    base = baseline.iloc[0]
    winner = best.iloc[0]
    rows = [
        [
            "V10 baseline all TF",
            _escape(str(base["timeframe_set_label"])),
            _fmt_int(base["trades_accepted"]),
            (_fmt_r(base["total_net_r"]), _metric_class(base["total_net_r"])),
            _fmt_r(base["max_drawdown_r"]),
            _fmt_num(base["longest_underwater_days"], 0),
            "Yes" if bool(base["passed_guardrails"]) else "No",
        ],
        [
            "Best V11 mix",
            _escape(str(winner["timeframe_set_label"])),
            _fmt_int(winner["trades_accepted"]),
            (_fmt_r(winner["total_net_r"]), _metric_class(winner["total_net_r"])),
            _fmt_r(winner["max_drawdown_r"]),
            _fmt_num(winner["longest_underwater_days"], 0),
            "Yes" if bool(winner["passed_guardrails"]) else "No",
        ],
        [
            "Delta",
            "",
            _delta(float(winner["trades_accepted"]) - float(base["trades_accepted"])),
            (_delta(float(winner["total_net_r"]) - float(base["total_net_r"])) + "R", _metric_class(float(winner["total_net_r"]) - float(base["total_net_r"]))),
            _delta(float(winner["max_drawdown_r"]) - float(base["max_drawdown_r"])) + "R",
            _delta(float(winner["longest_underwater_days"]) - float(base["longest_underwater_days"])),
            "",
        ],
    ]
    return _table(["Row", "Set", "Trades", "Total R", "Max DD", "Underwater Days", "Pass"], rows)


def _decision_table(summary: pd.DataFrame) -> str:
    wanted = ["all", "no_h4", "no_h8", "no_h4_h8"]
    data = _main_rows(summary)
    data = data[data["timeframe_set_id"].astype(str).isin(wanted)].copy()
    data["_order"] = data["timeframe_set_id"].map({value: index for index, value in enumerate(wanted)})
    data = data.sort_values("_order").drop(columns=["_order"])
    return _summary_table(data)


def _underwater_reduction(summary: pd.DataFrame) -> str:
    data = _main_rows(summary).sort_values(
        ["longest_underwater_days", "max_drawdown_r", "total_net_r"],
        ascending=[True, True, False],
    )
    return _summary_table(data, limit=12)


def _rejected_interesting(summary: pd.DataFrame) -> str:
    data = _main_rows(summary)
    rejected = data[~data["passed_guardrails"].astype(bool)].copy()
    rejected = rejected.sort_values(["total_net_r", "return_to_drawdown"], ascending=False)
    return _summary_table(rejected, limit=8)


def _html_report(run_dir: Path, config: dict[str, Any], summary: pd.DataFrame, *, current_page: str) -> str:
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Timeframe Mix Dashboard",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "Which timeframe mix performed best in this generated run?",
            "setup": "This is a run-local timeframe mix dashboard generated from existing trade logs.",
            "how_to_read": "Read Best Timeframe Mix first, then compare H4/H8 removal and underwater behavior.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    best = _best_passing_main(summary).head(1)
    baseline = _baseline_row(summary).head(1)
    best_label = "No pass" if best.empty else str(best.iloc[0]["timeframe_set_label"])
    best_total = "n/a" if best.empty else _fmt_r(best.iloc[0]["total_net_r"])
    best_dd = "n/a" if best.empty else _fmt_r(best.iloc[0]["max_drawdown_r"])
    best_underwater = "n/a" if best.empty else f"{_fmt_num(best.iloc[0]['longest_underwater_days'], 0)}D"
    baseline_total = "n/a" if baseline.empty else _fmt_r(baseline.iloc[0]["total_net_r"])
    guardrail_note = (
        f"Pass requires max closed-trade drawdown <= {config['max_drawdown_guardrail_r']}R "
        f"and longest underwater period <= {config['max_underwater_guardrail_days']} days."
    )
    passed_main = _best_passing_main(summary)
    best_section = _summary_table(passed_main, limit=10) if not passed_main.empty else _summary_table(_main_rows(summary).sort_values("total_net_r", ascending=False), limit=10)
    diagnostics = _diagnostic_rows(summary).sort_values(["timeframe_set_id", "pivot_strength"])

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V11 Timeframe Mix - by Cody</title>
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
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 12px; margin-bottom: 18px; }}
    .kpi {{ background: #f9fbfc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .kpi-note {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    .note {{ background: #f6f8f2; border-left: 4px solid #8aa936; padding: 12px 14px; color: #34412d; margin-bottom: 14px; }}
    .warning {{ background: #fff8e8; border-left-color: var(--warn); color: #4d3b13; }}
    {experiment_summary_css()}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; vertical-align: top; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #455464; background: #f7f9fb; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    {dashboard_base_css(table_min_width="980px")}
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
      title="LP + Force Strike V11 Timeframe Mix - by Cody",
      subtitle_html=f"Static V11 report generated from <code>{_escape(run_dir)}</code>. This page keeps V10 LP3 cap 4R mechanics fixed and only changes timeframe inclusion.",
      current_page=current_page,
      section_links=[
          ("#experiment-summary", "Snapshot"),
          ("#overview", "Overview"),
          ("#metric-glossary", "Glossary"),
          ("#best-timeframe-mix", "Best Mix"),
          ("#baseline-comparison", "Baseline"),
          ("#h4-h8-decision", "H4/H8"),
          ("#underwater-reduction", "Underwater"),
          ("#lp-diagnostics", "Diagnostics"),
      ],
  )}
  <main>
    {experiment_summary_html(page_metadata)}
    {metric_glossary_html()}
    <section id="overview">
      <h2>Recommended / Rejected Conclusion</h2>
      <div class="kpis">
        {_kpi("Best Timeframe Mix", best_label, "highest Total R inside guardrails")}
        {_kpi("Best Total R", best_total, "V11 passing main rows")}
        {_kpi("Best Max DD", best_dd, "closed-trade drawdown")}
        {_kpi("Best Underwater", best_underwater, "longest period below equity high")}
        {_kpi("V10 Baseline Total R", baseline_total, "all H4/H8/H12/D1/W1")}
      </div>
      <div class="note">What changed from V10: exposure mechanics are fixed at LP3 cap 4R. V11 changes only the timeframe basket to test whether removing H4 and/or H8 improves the portfolio curve.</div>
    </section>
    <section id="best-timeframe-mix">
      <h2>Best Timeframe Mix</h2>
      <div class="note">{_escape(guardrail_note)} Rank is by Total R after those guardrails pass.</div>
      {best_section}
    </section>
    <section id="baseline-comparison">
      <h2>Baseline Comparison</h2>
      <div class="note">This compares the V10 all-timeframe baseline against the best passing V11 timeframe mix.</div>
      {_baseline_comparison(summary)}
    </section>
    <section id="h4-h8-decision">
      <h2>H4/H8 Decision</h2>
      <div class="note">This isolates the practical decision: keep all, remove H4, remove H8, or remove both lower intraday buckets.</div>
      {_decision_table(summary)}
    </section>
    <section id="underwater-reduction">
      <h2>Underwater Reduction</h2>
      <div class="note">Sorted by shortest underwater period first. Use this to judge smoother execution, not just total return.</div>
      {_underwater_reduction(summary)}
    </section>
    <section id="rejected-interesting">
      <h2>Rejected But Interesting</h2>
      <div class="note warning">These main rows failed the V11 guardrails. They can be research leads, but they should not replace the baseline yet.</div>
      {_rejected_interesting(summary)}
    </section>
    <section id="lp-diagnostics">
      <h2>LP4/LP5 Diagnostics</h2>
      <div class="note">Diagnostics only run on all timeframes, remove H4, and remove H4+H8. V12 can retest LP pivot defaults after V11 selects a timeframe set.</div>
      {_summary_table(diagnostics)}
    </section>
  </main>
  <footer>Generated from existing V9 trade logs. No signal rerun was performed.</footer>
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

    summary, accepted = run_timeframe_mix_analysis(trades, config)
    for row in summary.sort_values(["row_role", "pivot_strength", "timeframe_set_id"]).itertuples():
        print(
            f"{row.row_role} LP{row.pivot_strength} {row.timeframe_set_id}: "
            f"trades={row.trades_accepted} total_r={row.total_net_r:.1f} "
            f"dd={row.max_drawdown_r:.1f} underwater={row.longest_underwater_days:.0f}d "
            f"pass={row.passed_guardrails}"
        )

    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_csv(run_dir / "timeframe_mix_summary.csv", summary)
    _write_csv(run_dir / "accepted_trades.csv", accepted)
    run_summary = {
        "run_dir": str(run_dir),
        "input_trades_path": str(input_path),
        "summary_rows": int(len(summary)),
        "accepted_trade_rows": int(len(accepted)),
        "passed_main_rows": int(_main_rows(summary)["passed_guardrails"].sum()) if not summary.empty else 0,
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = _html_report(run_dir, config, summary, current_page="v11.html" if docs_output else "dashboard.html")
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    run_config = _read_json(run_dir / "run_config.json")
    config = dict(run_config["config"])
    summary = _read_csv(run_dir / "timeframe_mix_summary.csv")
    html_text = _html_report(run_dir, config, summary, current_page=docs_output.name)
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines()) + "\n"
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_text, encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V11 practical timeframe mix study.")
    parser.add_argument("--config", help="Path to timeframe mix experiment config JSON.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v11.html.")
    parser.add_argument("--render-run-dir", help="Existing timeframe mix run directory to render without rerunning.")
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
