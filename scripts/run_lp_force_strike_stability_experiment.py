from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    dashboard_page,
    dashboard_page_links,
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

from lp_force_strike_strategy_lab import StabilityFilter, run_stability_analysis  # noqa: E402


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _read_trades(run_dir: Path) -> pd.DataFrame:
    trades_path = run_dir / "trades.csv"
    header = pd.read_csv(trades_path, nrows=0).columns
    wanted = ["candidate_id", "symbol", "timeframe", "entry_time_utc", "net_r", "bars_held", "exit_reason"]
    usecols = [column for column in wanted if column in header]
    return pd.read_csv(trades_path, usecols=usecols)


def _filters(payload: list[dict[str, Any]]) -> list[StabilityFilter]:
    return [
        StabilityFilter(
            filter_id=str(item["filter_id"]),
            include_all_pairs=bool(item.get("include_all_pairs", False)),
            min_trades=int(item.get("min_trades", 0)),
            min_avg_net_r=None if item.get("min_avg_net_r") is None else float(item["min_avg_net_r"]),
            min_profit_factor=None if item.get("min_profit_factor") is None else float(item["min_profit_factor"]),
            min_total_net_r=None if item.get("min_total_net_r") is None else float(item["min_total_net_r"]),
        )
        for item in payload
    ]


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(float(value)):,.0f}"
    except (TypeError, ValueError):
        return "0"


def _fmt_num(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(number):
        return ""
    return f"{number:,.{digits}f}"


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100.0:,.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _escape(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return html.escape(str(value))


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


def _candidate_short(candidate_id: str) -> str:
    text = str(candidate_id)
    text = re.sub(r"signal_zone_(\d+p?\d*)_pullback", lambda match: f"zone {match.group(1).replace('p', '.')} pullback", text)
    text = re.sub(r"fs_structure_max_(\d+p?\d*)atr", lambda match: f"structure <= {match.group(1).replace('p', '.')}ATR", text)
    text = text.replace("fs_structure", "structure")
    text = text.replace("__", " / ")
    text = re.sub(r"(?<= / )(\d+p?\d*)r\b", lambda match: f"{match.group(1).replace('p', '.')}R", text)
    return text


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


def _page_nav(current_page: str) -> str:
    return dashboard_page_links(current_page)


def _filter_rows(frame: pd.DataFrame, partition: str) -> list[list[Any]]:
    data = frame[frame["partition"] == partition].sort_values(["avg_net_r", "profit_factor", "trades"], ascending=False)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(_candidate_short(row["candidate_id"])),
                _escape(row["filter_id"]),
                _fmt_int(row["allowed_pair_count"]),
                _fmt_int(row["trades"]),
                _fmt_pct(row["win_rate"]),
                (_fmt_num(row["avg_net_r"]), _metric_class(row["avg_net_r"])),
                (_fmt_num(row["total_net_r"], 1), _metric_class(row["total_net_r"])),
                _fmt_num(row["profit_factor"], 2),
            ]
        )
    return rows


def _allowed_pair_rows(frame: pd.DataFrame) -> list[list[Any]]:
    data = frame.sort_values(["candidate_id", "filter_id", "timeframe", "train_avg_net_r"], ascending=[True, True, True, False])
    rows = []
    for _, row in data.iterrows():
        rows.append(
            [
                _escape(_candidate_short(row["candidate_id"])),
                _escape(row["filter_id"]),
                _escape(row["symbol"]),
                _escape(row["timeframe"]),
                _fmt_int(row["train_trades"]),
                (_fmt_num(row["train_avg_net_r"]), _metric_class(row["train_avg_net_r"])),
                (_fmt_num(row["train_total_net_r"], 1), _metric_class(row["train_total_net_r"])),
                _fmt_num(row["train_profit_factor"], 2),
            ]
        )
    return rows


def _html_report(run_dir: Path, config: dict[str, Any], filter_results: pd.DataFrame, allowed_pairs: pd.DataFrame, *, current_page: str) -> str:
    test_rows = filter_results[filter_results["partition"] == "test"].copy()
    best = test_rows.sort_values(["avg_net_r", "profit_factor", "trades"], ascending=False).head(1)
    best_label = _candidate_short(best.iloc[0]["candidate_id"]) if not best.empty else "n/a"
    best_filter = str(best.iloc[0]["filter_id"]) if not best.empty else "n/a"
    try:
        page_metadata = dashboard_page(current_page)
    except KeyError:
        page_metadata = {
            "page": current_page,
            "nav_label": "Run",
            "title": "LP + Force Strike Stability Dashboard",
            "status_label": "Run report",
            "status_kind": "neutral",
            "question": "What did this generated stability run produce?",
            "setup": "This is a run-local stability dashboard generated from the selected report directory.",
            "how_to_read": "Use the test period first, then compare training-period filters.",
            "conclusion": "No version-level conclusion is attached to this run-local page.",
            "action": "Use versioned docs pages for research conclusions.",
        }

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LP + Force Strike V4 Stability Dashboard - by Cody</title>
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
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 Inter, Segoe UI, Roboto, Arial, sans-serif; min-width: 0; overflow-x: hidden; }}
    header {{ background: #17202a; color: white; padding: 28px max(18px, 5vw); border-bottom: 4px solid #57a773; }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(22px, 4vw, 28px); }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; overflow-wrap: anywhere; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    nav a {{ color: white; text-decoration: none; border: 1px solid rgba(255,255,255,.25); padding: 7px 10px; border-radius: 6px; background: rgba(255,255,255,.08); min-height: 34px; }}
    nav a.active {{ background: #57a773; border-color: #57a773; color: #17202a; font-weight: 700; }}
    main {{ padding: 24px max(18px, 5vw) 48px; }}
    section {{ margin: 0 0 22px; padding: 20px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(23,32,42,.05); max-width: 100%; overflow-x: auto; }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: 12px; margin-bottom: 16px; }}
    .kpi {{ background: #f9fbfc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .kpi span {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .kpi strong {{ display: block; margin-top: 4px; font-size: 22px; }}
    .note {{ background: #f6f8f2; border-left: 4px solid #8aa936; padding: 12px 14px; color: #34412d; margin-bottom: 14px; }}
    {experiment_summary_css()}
    .scroll {{ overflow-x: auto; max-width: 100%; }}
    table {{ width: 100%; min-width: 720px; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; vertical-align: top; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: #455464; background: #f7f9fb; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .positive {{ color: var(--good); font-weight: 700; }}
    .negative {{ color: var(--bad); font-weight: 700; }}
    .neutral {{ color: var(--muted); }}
    {dashboard_base_css(table_min_width="720px")}
    @media (max-width: 760px) {{
      header {{ padding: 22px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 16px 12px 34px; }}
      section {{ padding: 14px; margin-bottom: 16px; }}
      h2 {{ font-size: 18px; }}
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .kpi {{ padding: 10px; }}
      .kpi strong {{ font-size: 20px; }}
      th, td {{ padding: 6px 7px; font-size: 12px; }}
    }}
    @media (max-width: 480px) {{
      .kpis {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LP + Force Strike V4 Stability Dashboard - by Cody",
      subtitle_html="Walk-forward stability check using V3 trades. Stable symbol/timeframe pairs are selected from training data before evaluating the later test period.",
      current_page=current_page,
      section_links=[
          ("#experiment-summary", "Snapshot"),
          ("#overview", "Overview"),
          ("#metric-glossary", "Glossary"),
          ("#test-period", "Test Results"),
          ("#training-period", "Training Results"),
          ("#allowed-pairs", "Allowed Pairs"),
      ],
  )}
  <main>
    {experiment_summary_html(page_metadata)}
    {metric_glossary_html()}

    <section id="overview">
      <h2>Overview</h2>
      <div class="kpis">
        <div class="kpi"><span>Split Time</span><strong>{_escape(config["split_time_utc"])}</strong></div>
        <div class="kpi"><span>Candidates</span><strong>{_fmt_int(len(config["candidate_ids"]))}</strong></div>
        <div class="kpi"><span>Filters</span><strong>{_fmt_int(len(config["filters"]))}</strong></div>
        <div class="kpi"><span>Best Test Row</span><strong>{_escape(best_filter)}</strong></div>
      </div>
      <div class="note">Current best test candidate: {_escape(best_label)}. This is still in-sample research at the strategy-family level; use it to choose the next controlled experiment, not as a live-trading verdict.</div>
    </section>
    <section id="test-period">
      <h2>Test Period Results</h2>
      <div class="scroll">{_table(["Candidate", "Filter", "Pairs", "Trades", "Win Rate", "Avg R", "Total R", "PF"], _filter_rows(filter_results, "test"))}</div>
    </section>
    <section id="training-period">
      <h2>Training Period Results</h2>
      <div class="scroll">{_table(["Candidate", "Filter", "Pairs", "Trades", "Win Rate", "Avg R", "Total R", "PF"], _filter_rows(filter_results, "train"))}</div>
    </section>
    <section id="allowed-pairs">
      <h2>Allowed Symbol/Timeframe Pairs</h2>
      <div class="note">These pairs are selected using training-period performance only.</div>
      <div class="scroll">{_table(["Candidate", "Filter", "Symbol", "TF", "Train Trades", "Train Avg R", "Train Total R", "Train PF"], _allowed_pair_rows(allowed_pairs))}</div>
    </section>
  </main>
</body>
</html>
"""


def _run(config_path: Path, docs_output: Path | None) -> int:
    config = _read_json(config_path)
    input_run_dir = REPO_ROOT / str(config["input_run_dir"])
    trades = _read_trades(input_run_dir)
    result = run_stability_analysis(
        trades,
        split_time_utc=config["split_time_utc"],
        candidate_ids=[str(value) for value in config["candidate_ids"]],
        filters=_filters(config["filters"]),
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / str(config["report_root"]) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    result.filter_results.to_csv(run_dir / "filter_results.csv", index=False)
    result.allowed_pairs.to_csv(run_dir / "allowed_pairs.csv", index=False)
    _write_json(run_dir / "run_config.json", {"config_path": str(config_path), "config": config})
    summary = {
        "run_dir": str(run_dir),
        "input_run_dir": str(input_run_dir),
        "split_time_utc": config["split_time_utc"],
        "candidates": len(config["candidate_ids"]),
        "filters": len(config["filters"]),
        "allowed_pair_rows": int(len(result.allowed_pairs)),
        "filter_result_rows": int(len(result.filter_results)),
    }
    _write_json(run_dir / "run_summary.json", summary)

    html_text = _html_report(
        run_dir,
        config,
        result.filter_results,
        result.allowed_pairs,
        current_page="v4.html" if docs_output else "dashboard.html",
    )
    (run_dir / "dashboard.html").write_text(html_text, encoding="utf-8")
    if docs_output is not None:
        docs_target = REPO_ROOT / docs_output
        docs_target.parent.mkdir(parents=True, exist_ok=True)
        docs_target.write_text(html_text, encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _render_existing(run_dir: Path, docs_output: Path) -> int:
    run_config = _read_json(run_dir / "run_config.json")
    config = dict(run_config["config"])
    filter_results = pd.read_csv(run_dir / "filter_results.csv")
    allowed_pairs = pd.read_csv(run_dir / "allowed_pairs.csv")
    html_text = _html_report(
        run_dir,
        config,
        filter_results,
        allowed_pairs,
        current_page=docs_output.name,
    )
    docs_target = REPO_ROOT / docs_output
    docs_target.parent.mkdir(parents=True, exist_ok=True)
    docs_target.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    print(f"dashboard={docs_target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LP + Force Strike V4 stability analysis from a prior trade run.")
    parser.add_argument("--config", help="Path to stability experiment config JSON.")
    parser.add_argument("--render-run-dir", help="Existing stability run directory to render without rerunning analysis.")
    parser.add_argument("--docs-output", help="Optional docs HTML output, e.g. docs/v4.html.")
    args = parser.parse_args()
    if args.render_run_dir:
        if args.docs_output is None:
            raise SystemExit("--docs-output is required with --render-run-dir")
        return _render_existing(Path(args.render_run_dir), Path(args.docs_output))
    if args.config is None:
        raise SystemExit("--config is required unless --render-run-dir is used")
    return _run(Path(args.config), None if args.docs_output is None else Path(args.docs_output))


if __name__ == "__main__":
    raise SystemExit(main())
