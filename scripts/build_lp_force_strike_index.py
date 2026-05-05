from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import (
    archived_dashboard_pages,
    current_dashboard_pages,
    dashboard_base_css,
    dashboard_header_html,
    load_dashboard_metadata,
    metric_glossary_html,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "index.html"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _fact_grid(facts: list[list[str]]) -> str:
    return "".join(
        f'<div class="fact"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
        for label, value in facts
    )


def _card(page: dict[str, Any]) -> str:
    status_kind = page.get("status_kind", "neutral")
    return f"""
    <section class="card">
      <div class="status status-{_escape(status_kind)}">{_escape(page['status_label'])}</div>
      <h2>{_escape(page['title'])}</h2>
      <p>{_escape(page['conclusion'])}</p>
      <div class="facts">
        {_fact_grid(page.get("facts", []))}
      </div>
      <a class="button" href="{_escape(page['page'])}">Open {_escape(page['nav_label'])} Dashboard</a>
    </section>
    """


def _baseline_card(home: dict[str, Any]) -> str:
    baseline = home["current_baseline"]
    return f"""
    <section id="current-baseline" class="card featured">
      <div class="status status-active">{_escape(baseline['status_label'])}</div>
      <h2>{_escape(baseline['title'])}</h2>
      <p>{_escape(baseline['description'])}</p>
      <div class="facts">
        {_fact_grid(baseline.get("facts", []))}
      </div>
      <a class="button" href="{_escape(baseline['button_href'])}">{_escape(baseline['button_label'])}</a>
    </section>
    """


def _start_here_card() -> str:
    return """
    <section id="start-here" class="card featured">
      <div class="status status-active">Start here</div>
      <h2>LPFS Handoff Entry Point</h2>
      <p>Future agents should start with the LPFS Start Here file, then verify current broker/runtime state before making live-operation conclusions.</p>
      <div class="facts">
        <div class="fact"><span>Primary audience</span><strong>Future AI agents</strong></div>
        <div class="fact"><span>Boundary</span><strong>Local dev vs VPS production</strong></div>
      </div>
      <a class="button" href="https://github.com/CodyChew/TradeAutomation/blob/main/strategies/lp_force_strike_strategy_lab/START_HERE.md">Open START_HERE</a>
    </section>
    """


def _truth_card() -> str:
    return """
    <section id="current-truth" class="card featured">
      <div class="status status-active">Current truth</div>
      <h2>What To Trust First</h2>
      <p>Use Python and MT5 for trading truth, generated dashboards for current contracts, and the VPS status packet for production state. Version pages remain audit history.</p>
      <div class="facts">
        <div class="fact"><span>Strategy contract</span><strong>Strategy guide</strong></div>
        <div class="fact"><span>Production state</span><strong>MT5 + runtime files</strong></div>
      </div>
      <a class="button" href="live_ops.html">Open Live Ops</a>
    </section>
    """


def _strategy_card() -> str:
    return """
    <section id="strategy-guide" class="card featured">
      <div class="status status-active">Strategy guide</div>
      <h2>Current Strategy Guide</h2>
      <p>Plain-English V13 mechanics plus V15 risk buckets and the V22 LP/FS separation rule, with signal rules, backtest trade simulation assumptions, MT5 execution status, and negative-event handling.</p>
      <div class="facts">
        <div class="fact"><span>Basis</span><strong>V13 + V15 + V22</strong></div>
        <div class="fact"><span>Execution</span><strong>Research + guarded live-send</strong></div>
      </div>
      <a class="button" href="strategy.html">Open Strategy Guide</a>
    </section>
    """


def _live_ops_card() -> str:
    return """
    <section id="live-ops" class="card featured">
      <div class="status status-active">Live operations</div>
      <h2>Live Ops Guide</h2>
      <p>Static verification guide for proving the guarded MT5 runner is correct using broker state, local state, journal rows, send gates, reconciliation gates, operator commands, and the separate IC VPS production lane.</p>
      <div class="facts">
        <div class="fact"><span>Cycle</span><strong>Default 30s sleep</strong></div>
        <div class="fact"><span>Pending expiry</span><strong>6 actual MT5 bars</strong></div>
      </div>
      <a class="button" href="live_ops.html">Open Live Ops</a>
    </section>
    """


def _account_validation_card() -> str:
    return """
    <section id="account-validation" class="card featured">
      <div class="status status-active">Broker validation</div>
      <h2>IC Markets Account Validation</h2>
      <p>Local IC Markets Raw Spread account audit, broker-data V22 rerun, FTMO-vs-IC commission comparison, IC growth-practical bucket recommendation, and the evidence path that led to the separate IC VPS live lane.</p>
      <div class="facts">
        <div class="fact"><span>Account</span><strong>ICMarketsSC-MT5-2</strong></div>
        <div class="fact"><span>IC live lane</span><strong>LPFS_IC_Live</strong></div>
      </div>
      <a class="button" href="account_validation.html">Open Account Validation</a>
    </section>
    """


def _section_heading(title: str, body: str) -> str:
    return f"""
    <section class="section-heading">
      <h2>{_escape(title)}</h2>
      <p>{_escape(body)}</p>
    </section>
    """


def _archive_card(page: dict[str, Any]) -> str:
    return f"""
          <article class="archive-card">
            <span>{_escape(page['nav_label'])}</span>
            <strong>{_escape(page['title'])}</strong>
            <p>{_escape(page['conclusion'])}</p>
            <a href="{_escape(page['page'])}">Open {_escape(page['nav_label'])}</a>
          </article>
    """


def _archive_panel(pages: list[dict[str, Any]]) -> str:
    return f"""
    <section id="research-archive" class="archive-panel">
      <details>
        <summary>Research Archive V1-V12</summary>
        <p>Older experiments stay available for audit history, but they no longer compete with the current strategy and live-ops contract on first read.</p>
        <div class="archive-card-grid">
          {"".join(_archive_card(page) for page in pages)}
        </div>
      </details>
    </section>
    """


def build_index(output: Path = DEFAULT_OUTPUT) -> Path:
    metadata = load_dashboard_metadata()
    home = metadata["home"]
    current_pages = sorted(current_dashboard_pages(metadata), key=lambda page: int(page["index_order"]))
    archive_pages = sorted(archived_dashboard_pages(metadata), key=lambda page: int(page["index_order"]))
    cards = [
        _start_here_card(),
        _truth_card(),
        _baseline_card(home),
        _strategy_card(),
        _live_ops_card(),
        _account_validation_card(),
        _section_heading(
            "Current Research Pages",
            "These are the current research snapshots that still feed the active LPFS strategy contract.",
        ),
    ] + [_card(page) for page in current_pages] + [_archive_panel(archive_pages)]
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(home['title'])}</title>
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
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.5 Inter, Segoe UI, Roboto, Arial, sans-serif;
      overflow-x: hidden;
    }}
    header {{
      background: #17202a;
      color: white;
      padding: 34px max(18px, 6vw);
      border-bottom: 4px solid #57a773;
    }}
    header h1 {{
      margin: 0 0 8px;
      font-size: clamp(24px, 5vw, 30px);
    }}
    header p {{
      margin: 0;
      color: #d8e0e8;
      max-width: 920px;
      overflow-wrap: anywhere;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    nav a {{
      color: white;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,.25);
      padding: 7px 10px;
      border-radius: 6px;
      background: rgba(255,255,255,.08);
      min-height: 34px;
    }}
    nav a.active {{
      background: #57a773;
      border-color: #57a773;
      color: #17202a;
      font-weight: 700;
    }}
    main {{
      padding: 28px max(18px, 6vw) 48px;
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 2px rgba(23,32,42,.05);
    }}
    .featured {{
      border-top: 4px solid var(--accent);
    }}
    .card h2 {{
      margin: 0 0 8px;
      font-size: 20px;
    }}
    .card p {{
      color: var(--muted);
      margin: 0 0 16px;
    }}
    .status {{
      display: inline-block;
      border-radius: 999px;
      padding: 5px 9px;
      margin-bottom: 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #f7f9fb;
    }}
    .status-active {{
      color: var(--good);
      border-color: #b9dbc7;
      background: #edf8f1;
    }}
    .status-rejected {{
      color: var(--bad);
      border-color: #e7bcbc;
      background: #fff1f1;
    }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 18px;
      font-size: 13px;
    }}
    .fact {{
      background: #f8fafb;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
    }}
    .fact strong {{
      display: block;
      font-size: 18px;
      color: var(--ink);
    }}
    a.button {{
      display: inline-block;
      background: var(--accent);
      color: white;
      text-decoration: none;
      padding: 9px 12px;
      border-radius: 6px;
      font-weight: 700;
    }}
    .section-heading,
    .archive-panel {{
      grid-column: 1 / -1;
    }}
    .section-heading {{
      background: transparent;
      border: 0;
      box-shadow: none;
      padding: 4px 0 0;
      margin: 0;
    }}
    .section-heading h2 {{
      margin: 0 0 4px;
    }}
    .section-heading p {{
      margin: 0;
      color: var(--muted);
      max-width: 900px;
    }}
    .archive-panel details {{
      border-top: 4px solid #5c7f95;
    }}
    .archive-panel summary {{
      cursor: pointer;
      font-weight: 700;
      font-size: 18px;
      color: var(--ink);
    }}
    .archive-panel p {{
      margin: 10px 0 14px;
      color: var(--muted);
    }}
    .archive-card-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
      gap: 10px;
      margin-top: 12px;
    }}
    .archive-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 12px;
    }}
    .archive-card span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .archive-card strong {{
      display: block;
      margin: 3px 0 5px;
    }}
    .archive-card p {{
      margin: 0 0 8px;
      font-size: 13px;
    }}
    .archive-card a {{
      color: var(--accent);
      font-weight: 700;
    }}
    {dashboard_base_css(table_min_width="720px", extra_css=".metric-glossary { grid-column: 1 / -1; }")}
    footer {{
      padding: 0 max(18px, 6vw) 32px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      header {{ padding: 24px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 18px 12px 36px; }}
      .card {{ padding: 16px; }}
      .facts {{ grid-template-columns: 1fr; }}
      a.button {{ display: block; text-align: center; }}
      .archive-card-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {dashboard_header_html(
      title=str(home["title"]),
      subtitle_html=_escape(home["intro"]),
      current_page="index.html",
      section_links=[
          ("#start-here", "Start Here"),
          ("#current-truth", "Current Truth"),
          ("#current-baseline", "Current Baseline"),
          ("#strategy-guide", "Strategy Guide"),
          ("#live-ops", "Live Ops"),
          ("#research-archive", "Archive"),
          ("#metric-glossary", "Glossary"),
      ],
      metadata=metadata,
  )}
  <main>
    {"".join(cards)}
    {metric_glossary_html()}
  </main>
  <footer>Generated dashboards are static research snapshots. Strategy behavior remains in tested Python modules; live state must be verified from MT5 and VPS runtime files.</footer>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LP + Force Strike dashboard index page.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_index(Path(args.output))
    print(f"dashboard_index={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
