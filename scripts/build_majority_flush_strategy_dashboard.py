from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = REPO_ROOT / "reports" / "strategies" / "majority_flush_strategy_all_timeframes"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "majority_flush_strategy.html"
TIMEFRAME_ORDER = ["M30", "H4", "H8", "H12", "D1", "W1"]


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _latest_run_dir(report_root: Path = DEFAULT_REPORT_ROOT) -> Path | None:
    if not report_root.exists():
        return None
    candidates = [path for path in report_root.iterdir() if path.is_dir() and (path / "run_summary.json").exists()]
    return max(candidates, key=lambda path: (path / "run_summary.json").stat().st_mtime) if candidates else None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _fmt_number(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{digits}f}"


def _fmt_int(value: Any) -> str:
    if value is None or value == "":
        return "0"
    return f"{int(float(value)):,}"


def _fmt_pct(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _decision_label(decision: str) -> tuple[str, str]:
    labels = {
        "continue_to_entry_iteration": ("Continue", "Baseline is positive enough to justify entry-model iteration."),
        "reject_or_rework_baseline": ("Rework", "Baseline does not yet justify optimization; inspect signal quality before continuing."),
        "pause_low_signal_count": ("Pause", "Signal count is too low for a robust conclusion."),
        "pause_no_trades": ("Pause", "Signals did not produce completed baseline trades."),
        "review_data_failures": ("Review", "One or more datasets failed and must be fixed before research conclusions."),
    }
    return labels.get(decision, ("Review", "Decision state is unknown; inspect generated report files."))


def _metric_cards(summary: dict[str, Any], best: dict[str, Any] | None) -> str:
    values = [
        ("Datasets", _fmt_int(summary.get("datasets"))),
        ("Signals", _fmt_int(summary.get("signals"))),
        ("Trades", _fmt_int(summary.get("trades"))),
        ("Skipped", _fmt_int(summary.get("skipped"))),
    ]
    if best:
        values.extend(
            [
                ("Avg R", _fmt_number(best.get("avg_net_r"))),
                ("Total R", _fmt_number(best.get("total_net_r"))),
                ("Win Rate", _fmt_pct(best.get("win_rate"))),
                ("Profit Factor", _fmt_number(best.get("profit_factor"))),
                ("Max DD", _fmt_number(best.get("max_closed_trade_drawdown_r"))),
            ]
        )
    return "".join(f"<div class=\"metric\"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>" for label, value in values)


def _table(frame: pd.DataFrame, columns: list[tuple[str, str]], *, limit: int = 12) -> str:
    if frame.empty:
        return '<p class="empty">No rows available.</p>'
    head = "".join(f"<th>{_escape(label)}</th>" for _, label in columns)
    body_rows = []
    for _, row in frame.head(limit).iterrows():
        cells = "".join(f"<td>{_escape(row.get(column, ''))}</td>" for column, _ in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _prepared_summary_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    data = frame.copy()
    for column in ("win_rate",):
        if column in data:
            data[column] = data[column].map(_fmt_pct)
    for column in ("avg_net_r", "total_net_r", "profit_factor", "max_closed_trade_drawdown_r"):
        if column in data:
            data[column] = data[column].map(_fmt_number)
    for column in ("trades", "signals", "skipped"):
        if column in data:
            data[column] = data[column].map(_fmt_int)
    return data


def _sort_timeframes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "timeframe" not in frame:
        return frame
    data = frame.copy()
    order = {timeframe: index for index, timeframe in enumerate(TIMEFRAME_ORDER)}
    data["_order"] = data["timeframe"].map(lambda value: order.get(str(value), len(order)))
    return data.sort_values(["_order", "timeframe"]).drop(columns=["_order"])


def _m30_impact_html(timeframe_summary: pd.DataFrame, best: dict[str, Any] | None) -> str:
    if timeframe_summary.empty or "timeframe" not in timeframe_summary:
        return "<p class=\"empty\">No timeframe rows available.</p>"
    if "M30" not in set(timeframe_summary["timeframe"].astype(str)):
        return "<p class=\"empty\">M30 was not included in this report.</p>"

    m30 = timeframe_summary.loc[timeframe_summary["timeframe"].astype(str) == "M30"].iloc[0]
    total_r = 0.0 if best is None else float(best.get("total_net_r") or 0.0)
    m30_r = float(m30.get("total_net_r") or 0.0)
    non_m30_r = total_r - m30_r
    impact = "improved" if total_r > non_m30_r else "worsened"
    return "\n".join(
        [
            f"      <p>M30 {_escape(impact)} the all-timeframe total by {_escape(_fmt_number(m30_r))}R versus the non-M30 total.</p>",
            '      <div class="metrics">',
            f'        <div class="metric"><span>M30 Trades</span><strong>{_escape(_fmt_int(m30.get("trades")))}</strong></div>',
            f'        <div class="metric"><span>M30 Total R</span><strong>{_escape(_fmt_number(m30_r))}</strong></div>',
            f'        <div class="metric"><span>M30 Avg R</span><strong>{_escape(_fmt_number(m30.get("avg_net_r"), 4))}</strong></div>',
            f'        <div class="metric"><span>M30 PF</span><strong>{_escape(_fmt_number(m30.get("profit_factor")))}</strong></div>',
            f'        <div class="metric"><span>Non-M30 Total R</span><strong>{_escape(_fmt_number(non_m30_r))}</strong></div>',
            f'        <div class="metric"><span>All-Timeframe Total R</span><strong>{_escape(_fmt_number(total_r))}</strong></div>',
            "      </div>",
        ]
    )


def _timeframe_recommendation_html(timeframe_summary: pd.DataFrame) -> str:
    if timeframe_summary.empty:
        return "<p class=\"empty\">No timeframe rows available.</p>"
    rows = []
    for _, row in _sort_timeframes(timeframe_summary).iterrows():
        avg_r = float(row.get("avg_net_r") or 0.0)
        profit_factor = row.get("profit_factor")
        pf_value = 0.0 if profit_factor in (None, "") else float(profit_factor)
        if avg_r > 0.0 and pf_value > 1.0:
            action = "Keep for next iteration"
        elif avg_r > -0.005 and pf_value >= 0.99:
            action = "Retest with entry variants"
        else:
            action = "Rework or deprioritize"
        rows.append(
            {
                "timeframe": row.get("timeframe"),
                "trades": _fmt_int(row.get("trades")),
                "avg_net_r": _fmt_number(avg_r, 4),
                "total_net_r": _fmt_number(row.get("total_net_r")),
                "profit_factor": _fmt_number(pf_value),
                "recommendation": action,
            }
        )
    frame = pd.DataFrame(rows)
    return _table(
        frame,
        [
            ("timeframe", "TF"),
            ("trades", "Trades"),
            ("avg_net_r", "Avg R"),
            ("total_net_r", "Total R"),
            ("profit_factor", "PF"),
            ("recommendation", "Recommendation"),
        ],
        limit=len(rows),
    )


def build_dashboard(run_dir: Path | None = None, output: Path = DEFAULT_OUTPUT) -> Path:
    resolved_run_dir = run_dir or _latest_run_dir()
    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if resolved_run_dir is None:
        summary: dict[str, Any] = {
            "decision": "pause_no_trades",
            "datasets": 0,
            "signals": 0,
            "trades": 0,
            "skipped": 0,
            "failed_datasets": 0,
            "run_dir": "",
        }
        config = {"config": {"timeframes": ["M30", "H4", "H8", "H12", "D1", "W1"], "pivot_strength": 3}}
        candidate_summary = pd.DataFrame()
        timeframe_summary = pd.DataFrame()
        symbol_summary = pd.DataFrame()
        dataset_rows = pd.DataFrame()
        skipped_summary = pd.DataFrame()
    else:
        summary = _read_json(resolved_run_dir / "run_summary.json")
        config = _read_json(resolved_run_dir / "run_config.json")
        candidate_summary = _read_csv(resolved_run_dir / "summary_by_candidate.csv")
        timeframe_summary = _read_csv(resolved_run_dir / "summary_by_timeframe.csv")
        symbol_summary = _read_csv(resolved_run_dir / "summary_by_symbol.csv")
        dataset_rows = _read_csv(resolved_run_dir / "datasets.csv")
        skipped_summary = _read_csv(resolved_run_dir / "skipped_summary.csv")

    best = None if candidate_summary.empty else candidate_summary.iloc[0].to_dict()
    decision, decision_body = _decision_label(str(summary.get("decision", "")))
    tested_config = config.get("config", {})
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Majority Flush Strategy Baseline</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #627181;
      --line: #d8e0e8;
      --accent: #22577a;
      --good: #2e7d50;
      --warn: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.5 Inter, Segoe UI, Roboto, Arial, sans-serif; }}
    header {{ background: #17202a; color: white; padding: 32px max(18px, 6vw); border-bottom: 4px solid #57a773; }}
    header h1 {{ margin: 0 0 8px; font-size: clamp(24px, 5vw, 32px); }}
    header p {{ margin: 0; color: #d8e0e8; max-width: 980px; }}
    nav {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; }}
    nav a {{ color: white; text-decoration: none; border: 1px solid rgba(255,255,255,.25); padding: 7px 10px; border-radius: 6px; background: rgba(255,255,255,.08); }}
    nav a.active {{ background: #57a773; border-color: #57a773; color: #17202a; font-weight: 700; }}
    main {{ padding: 24px max(18px, 6vw) 48px; display: grid; gap: 18px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 1px 2px rgba(23,32,42,.05); }}
    h2 {{ margin: 0 0 10px; font-size: 20px; }}
    p {{ margin: 0 0 12px; color: var(--muted); }}
    .status {{ display: inline-block; border-radius: 999px; padding: 5px 9px; margin-bottom: 10px; font-size: 12px; font-weight: 700; background: #edf8f1; color: var(--good); border: 1px solid #b9dbc7; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .metric {{ background: #f8fafb; border: 1px solid var(--line); border-radius: 6px; padding: 10px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 12px; }}
    .metric strong {{ display: block; font-size: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(360px, 100%), 1fr)); gap: 18px; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 4px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--line); padding: 8px; vertical-align: top; }}
    th {{ background: #f8fafb; color: var(--muted); font-size: 12px; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    code {{ background: #eef3f7; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>Majority Flush Strategy Baseline</h1>
    <p>research/backtest-only V1 baseline for final-LP Majority Flush execution signals. LPFS live execution, live runners, configs, runtime files, journals, broker state, and MQL5 files are out of scope.</p>
    <nav aria-label="Dashboard pages">
      <a href="index.html">Home</a>
      <a class="active" href="majority_flush_strategy.html">Majority Flush</a>
      <a href="strategy.html">LPFS Strategy</a>
      <a href="live_ops.html">LPFS Live Ops</a>
    </nav>
  </header>
  <main>
    <section>
      <div class="status">{_escape(decision)}</div>
      <h2>Implementation State</h2>
      <p>{_escape(decision_body)}</p>
      <div class="metrics">{_metric_cards(summary, best)}</div>
      <p>Generated: {_escape(generated_utc)}. Latest report: <code>{_escape(summary.get("run_dir", ""))}</code>.</p>
    </section>
    <section>
      <h2>Rules Tested</h2>
      <ul>
        <li>Dataset: existing 10-year FTMO FX Parquet data.</li>
        <li>Timeframes: {_escape(", ".join(str(item) for item in tested_config.get("timeframes", [])))}.</li>
        <li>Pivot strength: {_escape(tested_config.get("pivot_strength", 3))}; execution window: {_escape(tested_config.get("max_bars_from_lp_break", 6))} bars including the LP-breaking candle as bar 1.</li>
        <li>Short: upside flush into final resistance LP, bearish lower-third close strictly below the LP.</li>
        <li>Long: downside flush into final support LP, bullish upper-third close strictly above the LP.</li>
        <li>Entry: next candle open. Stop: flush structure. Target: 1R. Costs: candle spread enabled.</li>
      </ul>
    </section>
    <div class="grid">
      <section>
        <h2>Timeframe Breakdown</h2>
        {_table(_prepared_summary_table(_sort_timeframes(timeframe_summary)), [("timeframe", "TF"), ("trades", "Trades"), ("avg_net_r", "Avg R"), ("total_net_r", "Total R"), ("win_rate", "Win"), ("profit_factor", "PF"), ("max_closed_trade_drawdown_r", "DD")], limit=8)}
      </section>
      <section>
        <h2>Skipped Attribution</h2>
        {_table(skipped_summary, [("reason", "Reason"), ("timeframe", "TF"), ("skipped", "Skipped")])}
      </section>
    </div>
    <section>
      <h2>M30 Impact</h2>
      {_m30_impact_html(timeframe_summary, best)}
    </section>
    <section>
      <h2>Timeframe Recommendation</h2>
      {_timeframe_recommendation_html(timeframe_summary)}
    </section>
    <section>
      <h2>Symbol Breakdown</h2>
      {_table(_prepared_summary_table(symbol_summary.sort_values("total_net_r", ascending=False) if not symbol_summary.empty else symbol_summary), [("symbol", "Symbol"), ("trades", "Trades"), ("avg_net_r", "Avg R"), ("total_net_r", "Total R"), ("win_rate", "Win"), ("profit_factor", "PF"), ("max_closed_trade_drawdown_r", "DD")], limit=28)}
    </section>
    <section>
      <h2>Dataset Coverage</h2>
      {_table(dataset_rows, [("symbol", "Symbol"), ("timeframe", "TF"), ("status", "Status"), ("rows", "Rows"), ("signals", "Signals"), ("trades", "Trades"), ("skipped", "Skipped")], limit=40)}
    </section>
    <section>
      <h2>Next Research Step</h2>
      <p>If the baseline remains worth continuing, the next iteration should test entry models only while keeping signal, stop, and target fixed. If the baseline is weak or concentrated, inspect signal examples before adding optimization degrees of freedom.</p>
    </section>
  </main>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Majority Flush strategy dashboard.")
    parser.add_argument("--run-dir", help="Optional explicit report run directory.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    run_dir = None if args.run_dir is None else Path(args.run_dir)
    output = build_dashboard(run_dir=run_dir, output=Path(args.output))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
