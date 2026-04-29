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
    dashboard_page,
    dashboard_page_links,
    experiment_summary_css,
    experiment_summary_html,
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

from lp_force_strike_strategy_lab import PortfolioRule, run_portfolio_rule  # noqa: E402


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


def _rules(config: dict[str, Any]) -> list[PortfolioRule]:
    configured = config.get("portfolio_rules")
    if configured:
        return [
            PortfolioRule(
                portfolio_id=str(row["portfolio_id"]),
                max_open_r=None if row.get("max_open_r") is None else float(row["max_open_r"]),
                enforce_one_per_symbol=bool(row.get("enforce_one_per_symbol", False)),
                risk_r_per_trade=float(row.get("risk_r_per_trade", 1.0)),
            )
            for row in configured
        ]

    return [
        PortfolioRule("take_all"),
        PortfolioRule("cap_4r", max_open_r=4.0, enforce_one_per_symbol=True),
        PortfolioRule("cap_6r", max_open_r=6.0, enforce_one_per_symbol=True),
        PortfolioRule("cap_8r", max_open_r=8.0, enforce_one_per_symbol=True),
        PortfolioRule("cap_10r", max_open_r=10.0, enforce_one_per_symbol=True),
    ]


def _profile_label(portfolio_id: str) -> str:
    if portfolio_id == "take_all":
        return "Take all"
    return portfolio_id.replace("cap_", "Cap ").replace("r", "R")


def _sort_profiles(frame: pd.DataFrame) -> pd.DataFrame:
    order = {"take_all": 0, "cap_4r": 1, "cap_6r": 2, "cap_8r": 3, "cap_10r": 4}
    data = frame.copy()
    data["_profile_order"] = data["portfolio_id"].map(lambda value: order.get(str(value), 99))
    return data.sort_values(["pivot_strength", "_profile_order"]).drop(columns=["_profile_order"])


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
    return f'<table class="{classes}"><thead><tr>{thead}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _summary_table(frame: pd.DataFrame, *, limit: int | None = None) -> str:
    data = frame.copy()
    if limit is not None:
        data = data.head(limit)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(f"LP{int(row['pivot_strength'])}"),
                _escape(_profile_label(str(row["portfolio_id"]))),
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
            "LP",
            "Portfolio",
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


def _best_practical(summary: pd.DataFrame) -> pd.DataFrame:
    passed = summary[summary["passed_guardrails"].astype(bool)].copy()
    if passed.empty:
        return passed
    return passed.sort_values(["total_net_r", "return_to_drawdown"], ascending=False)


def _take_all_vs_caps(summary: pd.DataFrame) -> str:
    data = _sort_profiles(summary)
    return _summary_table(data)


def _rejected_interesting(summary: pd.DataFrame) -> str:
    rejected = summary[~summary["passed_guardrails"].astype(bool)].copy()
    if rejected.empty:
        return "<p>No rows were rejected by the V10 guardrails.</p>"
    rejected = rejected.sort_values(["total_net_r", "return_to_drawdown"], ascending=False)
    return _summary_table(rejected, limit=10)


def _drawdown_table(summary: pd.DataFrame) -> str:
    data = summary.sort_values(["max_drawdown_r", "longest_underwater_days", "total_net_r"], ascending=[True, True, False])
    return _summary_table(data)


def _html_report(run_dir: Path, config: dict[str, Any], summary: pd.DataFrame, current_page: str) -> str:
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Portfolio Dashboard",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "What did this generated portfolio run produce?",
            "setup": "This is a run-local portfolio dashboard generated from an experiment report.",
            "how_to_read": "Start with Best Practical Mechanics, then compare drawdown and rejection counts.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    best = _best_practical(summary).head(1)
    if best.empty:
        best_label = "No pass"
        best_note = "No row passed both guardrails"
        best_total = "n/a"
        best_dd = "n/a"
    else:
        row = best.iloc[0]
        best_label = f"LP{int(row['pivot_strength'])} {_profile_label(str(row['portfolio_id']))}"
        best_note = "highest Total R inside guardrails"
        best_total = _fmt_r(row["total_net_r"])
        best_dd = _fmt_r(row["max_drawdown_r"])

    passed = _best_practical(summary)
    closest = summary.sort_values(["total_net_r", "return_to_drawdown"], ascending=False)
    best_section = (
        _summary_table(passed, limit=8)
        if not passed.empty
        else "<p>No candidate passed the 30R / 180D guardrails. The closest alternatives are shown below.</p>"
        + _summary_table(closest, limit=8)
    )

    guardrail_note = (
        f"Pass requires max closed-trade drawdown <= {config['max_drawdown_guardrail_r']}R "
        f"and longest underwater period <= {config['max_underwater_guardrail_days']} days."
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V10 Portfolio - by Cody</title>
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
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 Inter, Segoe UI, Roboto, Arial, sans-serif;
      overflow-x: hidden;
    }}
    header {{
      background: #17202a;
      color: white;
      padding: 28px max(18px, 5vw);
      border-bottom: 4px solid #57a773;
    }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(22px, 4vw, 28px); }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    nav a {{
      color: white;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,.25);
      padding: 7px 10px;
      border-radius: 6px;
      background: rgba(255,255,255,.08);
    }}
    nav a.active {{ background: #57a773; border-color: #57a773; color: #17202a; font-weight: 700; }}
    main {{ padding: 24px max(18px, 5vw) 48px; }}
    section {{
      margin: 0 0 22px;
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(23,32,42,.05);
      overflow-x: auto;
    }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr)); gap: 12px; margin-bottom: 18px; }}
    .kpi {{ background: #f9fbfc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi-value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    .kpi-note {{ color: var(--muted); font-size: 12px; }}
    .note {{ background: #f6f8f2; border-left: 4px solid #8aa936; padding: 12px 14px; color: #34412d; margin-bottom: 14px; }}
    .warning {{ background: #fff8e8; border-left-color: var(--warn); color: #4d3b13; }}
    table {{ width: 100%; min-width: 900px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #455464; background: #f7f9fb; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    {experiment_summary_css()}
    footer {{ color: var(--muted); padding: 0 max(18px, 5vw) 28px; }}
    @media (max-width: 760px) {{
      header {{ padding: 22px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 16px 12px 34px; }}
      section {{ padding: 14px; margin-bottom: 16px; }}
      .kpi-value {{ font-size: 20px; }}
      th, td {{ padding: 6px 7px; font-size: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>LP + Force Strike Portfolio Dashboard - by Cody</h1>
    <p>Static V10 portfolio report generated from <code>{_escape(run_dir)}</code>. This page compares exposure rules only; timeframe mixes are reserved for V11.</p>
    <nav aria-label="Dashboard pages">
      {dashboard_page_links(current_page)}
    </nav>
  </header>
  <main>
    {experiment_summary_html(page_metadata)}
    <section id="overview">
      <h2>Recommended / Rejected Conclusion</h2>
      <div class="kpis">
        {_kpi("Best Practical", best_label, best_note)}
        {_kpi("Best Total R", best_total, "inside guardrails")}
        {_kpi("Best Max DD", best_dd, "closed-trade drawdown")}
        {_kpi("Rows Passing", _fmt_int(len(passed)), guardrail_note)}
      </div>
      <div class="note">What changed from V9: V9 ranked isolated trade rows by LP pivot strength. V10 adds portfolio acceptance rules, open-risk caps, one-symbol exposure, and drawdown/underwater guardrails.</div>
    </section>
    <section id="best">
      <h2>Best Practical Mechanics</h2>
      <div class="note">{_escape(guardrail_note)} Rank is by Total R after those guardrails pass.</div>
      {best_section}
    </section>
    <section id="take-all">
      <h2>Take-All vs Capped</h2>
      <div class="note">Take-all accepts every V9 trade for the pivot. Capped portfolios use one open trade per symbol and reject new trades once open risk would exceed the cap.</div>
      {_take_all_vs_caps(summary)}
    </section>
    <section id="drawdown">
      <h2>Drawdown Table</h2>
      <div class="note">Sorted by smoother curves first: lower max DD, then shorter underwater period, then higher Total R.</div>
      {_drawdown_table(summary)}
    </section>
    <section id="rejected">
      <h2>Rejected But Interesting</h2>
      <div class="note warning">These rows have attractive return or frequency but failed the V10 guardrails. They are research leads, not current recommendations.</div>
      {_rejected_interesting(summary)}
    </section>
  </main>
  <footer>Generated from existing V9 trade logs. Reports are ignored by git; docs pages are the published research snapshot.</footer>
</body>
</html>
"""


def _run(config_path: Path, *, docs_output: Path | None = None) -> int:
    config = _read_json(config_path)
    input_path = REPO_ROOT / str(config["input_trades_path"])
    trades = _read_csv(input_path)
    pivot_strengths = [int(value) for value in config["pivot_strengths"]]
    rules = _rules(config)
    max_drawdown = float(config["max_drawdown_guardrail_r"])
    max_underwater = float(config["max_underwater_guardrail_days"])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / str(config["report_root"]) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    accepted_frames: list[pd.DataFrame] = []
    for pivot_strength in pivot_strengths:
        pivot_trades = trades[trades["pivot_strength"].astype(int) == pivot_strength].copy()
        for rule in rules:
            result, selected = run_portfolio_rule(
                pivot_trades,
                rule=rule,
                pivot_strength=pivot_strength,
                max_drawdown_guardrail_r=max_drawdown,
                max_underwater_guardrail_days=max_underwater,
            )
            summary_rows.append(asdict(result))
            if not selected.empty:
                selected = selected.copy()
                selected["pivot_strength"] = pivot_strength
                accepted_frames.append(selected)
            print(
                f"LP{pivot_strength} {rule.portfolio_id}: trades={result.trades_accepted} "
                f"total_r={result.total_net_r:.1f} dd={result.max_drawdown_r:.1f} "
                f"underwater={result.longest_underwater_days:.0f}d pass={result.passed_guardrails}"
            )

    summary = pd.DataFrame(summary_rows)
    accepted = pd.concat(accepted_frames, ignore_index=True) if accepted_frames else pd.DataFrame()
    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    _write_csv(run_dir / "portfolio_summary.csv", summary)
    _write_csv(run_dir / "accepted_trades.csv", accepted)
    run_summary = {
        "run_dir": str(run_dir),
        "input_trades_path": str(input_path),
        "portfolio_rows": int(len(summary)),
        "accepted_trade_rows": int(len(accepted)),
        "passed_guardrail_rows": int(summary["passed_guardrails"].sum()) if not summary.empty else 0,
    }
    _write_json(run_dir / "run_summary.json", run_summary)

    html_text = _html_report(run_dir, config, summary, current_page="v10.html" if docs_output else "dashboard.html")
    (run_dir / "dashboard.html").write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    if docs_output is not None:
        target = REPO_ROOT / docs_output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")

    print(json.dumps(run_summary, indent=2, sort_keys=True))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    run_config = _read_json(run_dir / "run_config.json")
    config = dict(run_config["config"])
    summary = _read_csv(run_dir / "portfolio_summary.csv")
    html_text = _html_report(run_dir, config, summary, current_page=docs_output.name)
    target = REPO_ROOT / docs_output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    print(f"dashboard={target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V10 portfolio baseline.")
    parser.add_argument("--config", help="Path to portfolio experiment config JSON.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v10.html.")
    parser.add_argument("--render-run-dir", help="Existing portfolio run directory to render without rerunning.")
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
