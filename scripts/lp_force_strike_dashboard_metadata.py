from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_PATH = REPO_ROOT / "configs" / "dashboards" / "lp_force_strike_pages.json"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def load_dashboard_metadata(path: str | Path = DEFAULT_METADATA_PATH) -> dict[str, Any]:
    """Load the human interpretation metadata for LP + Force Strike dashboards."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def dashboard_pages(metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return page metadata in navigation order."""

    payload = metadata or load_dashboard_metadata()
    return sorted(payload["pages"], key=lambda row: int(str(row["nav_label"]).lstrip("V")))


def dashboard_page(page_name: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return metadata for one dashboard page."""

    for page in dashboard_pages(metadata):
        if page["page"] == page_name:
            return page
    raise KeyError(f"No dashboard metadata for {page_name!r}.")


def dashboard_page_links(current_page: str, metadata: dict[str, Any] | None = None) -> str:
    """Render Home and version links from the central metadata file."""

    links = []
    home_active = " active" if current_page == "index.html" else ""
    links.append(f'<a class="page-link{home_active}" href="index.html">Home</a>')
    for page in dashboard_pages(metadata):
        active = " active" if current_page == page["page"] else ""
        href = _escape(page["page"])
        label = _escape(page["nav_label"])
        links.append(f'<a class="page-link{active}" href="{href}">{label}</a>')
    return "\n      ".join(links)


def dashboard_header_html(
    *,
    title: str,
    subtitle_html: str,
    current_page: str,
    section_links: list[tuple[str, str]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render the shared dashboard header with version and section navigation."""

    sections = ""
    if section_links:
        links = []
        for href, label in section_links:
            links.append(f'<a href="{_escape(href)}">{_escape(label)}</a>')
        sections = f"""
    <nav class="report-nav" aria-label="Report sections">
      {"".join(links)}
    </nav>
        """

    return f"""
  <header class="dashboard-header">
    <h1>{_escape(title)}</h1>
    <p>{subtitle_html}</p>
    <nav class="page-nav" aria-label="Dashboard pages">
      {dashboard_page_links(current_page, metadata)}
    </nav>
    {sections}
  </header>
    """


def metric_glossary_html() -> str:
    """Render common trading metric definitions for dashboard interpretation."""

    terms = [
        (
            "Realized DD",
            "Closed-trade equity drawdown only. It ignores open trade risk until a position exits.",
        ),
        (
            "Risk-Reserved DD",
            "Live-account stress drawdown that subtracts full open risk while positions are active.",
        ),
        (
            "Max Reserved Risk",
            "Largest total open risk reserved at one time across accepted portfolio trades.",
        ),
        (
            "Worst Month",
            "Largest calendar-month loss in account-percent terms for the tested schedule.",
        ),
        (
            "Return/DD",
            "Total return divided by risk-reserved drawdown where available; higher is more efficient.",
        ),
        (
            "Avg R / PF",
            "Average net R per trade and profit factor. Use both with trade count before trusting a row.",
        ),
    ]
    items = "".join(
        f"<div><dt>{_escape(label)}</dt><dd>{_escape(description)}</dd></div>"
        for label, description in terms
    )
    return f"""
    <section id="metric-glossary" class="metric-glossary" aria-labelledby="metric-glossary-title">
      <h2 id="metric-glossary-title">Metric Glossary</h2>
      <dl>{items}</dl>
    </section>
    """


def experiment_summary_html(page: dict[str, Any]) -> str:
    """Render the common top-of-page interpretation block."""

    decision_brief = ""
    brief = page.get("decision_brief") or {}
    if brief:
        key_results = brief.get("key_results") or []
        key_items = "".join(f"<li>{_escape(item)}</li>" for item in key_results)
        next_step = brief.get("next_step")
        next_step_html = ""
        if next_step:
            next_step_html = f'<p class="brief-next"><strong>Next:</strong> {_escape(next_step)}</p>'
        decision_brief = f"""
      <div class="decision-brief">
        <h3>Decision Brief</h3>
        <p class="brief-headline">{_escape(brief.get('headline', ''))}</p>
        <ul>{key_items}</ul>
        {next_step_html}
      </div>
        """

    comparison = ""
    comparison_rows = page.get("comparison_rows") or []
    if comparison_rows:
        body = []
        for row in comparison_rows:
            body.append(
                "<tr>"
                + "".join(f"<td>{_escape(value)}</td>" for value in row)
                + "</tr>"
            )
        comparison = (
            '<div class="summary-comparison">'
            "<h3>Baseline Comparison</h3>"
            '<table class="comparison-table"><thead><tr>'
            "<th>Run</th><th>Trades</th><th>Win Rate</th><th>Avg R</th><th>PF</th><th>Total R</th>"
            "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
            "</div>"
        )

    return f"""
    <section id="experiment-summary" class="experiment-summary">
      <div class="summary-heading">
        <div>
          <div class="eyebrow">{_escape(page['nav_label'])} Research Snapshot</div>
          <h2>{_escape(page['title'])}</h2>
        </div>
        <span class="status-badge status-{_escape(page.get('status_kind', 'neutral'))}">{_escape(page['status_label'])}</span>
      </div>
      {decision_brief}
      <div class="summary-grid">
        <div><h3>What This Tests</h3><p>{_escape(page['question'])}</p></div>
        <div><h3>Setup Tested</h3><p>{_escape(page['setup'])}</p></div>
        <div><h3>How To Read This Page</h3><p>{_escape(page['how_to_read'])}</p></div>
        <div><h3>Use / Do Not Use</h3><p>{_escape(page['action'])}</p></div>
      </div>
      <div class="conclusion-box"><strong>Conclusion:</strong> {_escape(page['conclusion'])}</div>
      {comparison}
    </section>
    """


def experiment_summary_css() -> str:
    """Return CSS used by the common experiment summary block."""

    return """
    .experiment-summary {
      border-top: 4px solid var(--accent);
    }
    .summary-heading {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      margin-bottom: 14px;
    }
    .summary-heading h2 {
      margin-bottom: 0;
    }
    .eyebrow {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .05em;
      text-transform: uppercase;
      margin-bottom: 4px;
    }
    .status-badge {
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid var(--line);
      background: #f7f9fb;
      color: var(--muted);
    }
    .status-active {
      color: var(--good);
      border-color: #b9dbc7;
      background: #edf8f1;
    }
    .status-rejected {
      color: var(--bad);
      border-color: #e7bcbc;
      background: #fff1f1;
    }
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr));
      gap: 12px;
    }
    .summary-grid div {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f9fbfc;
      padding: 12px;
    }
    .summary-grid h3 {
      margin: 0 0 6px;
    }
    .summary-grid p {
      margin: 0;
      color: var(--ink);
    }
    .conclusion-box {
      margin-top: 14px;
      background: #f6f8f2;
      border-left: 4px solid #8aa936;
      padding: 12px 14px;
      color: #34412d;
    }
    .decision-brief {
      margin-top: 14px;
      border: 1px solid #cbd8e4;
      border-radius: 8px;
      background: #fbfcfd;
      padding: 14px 16px;
    }
    .decision-brief h3 {
      margin: 0 0 8px;
      font-size: 16px;
      color: var(--ink);
    }
    .decision-brief .brief-headline {
      margin: 0 0 8px;
      font-weight: 700;
    }
    .decision-brief ul {
      margin: 0;
      padding-left: 20px;
    }
    .decision-brief li {
      margin: 6px 0;
    }
    .decision-brief .brief-next {
      margin: 10px 0 0;
      color: var(--muted);
    }
    .summary-comparison {
      margin-top: 14px;
      overflow-x: auto;
    }
    .comparison-table td:first-child,
    .comparison-table th:first-child {
      text-align: left;
    }
    @media (max-width: 760px) {
      .summary-heading {
        display: block;
      }
      .status-badge {
        display: inline-block;
        margin-top: 10px;
      }
    }
    """


def dashboard_base_css(*, table_min_width: str = "900px", extra_css: str = "") -> str:
    """Return shared CSS for static dashboard readability and accessibility."""

    return f"""
    :root {{
      --bg: #f3f6f8;
      --panel: #ffffff;
      --panel-soft: #f8fafb;
      --ink: #17202a;
      --muted: #5d6d7e;
      --line: #d8e0e8;
      --accent: #22577a;
      --accent-2: #3f7f5f;
      --good: #256f46;
      --bad: #9f3333;
      --warn: #8a5a00;
      --focus: #f2c94c;
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 Inter, Segoe UI, Roboto, Arial, sans-serif;
      min-width: 0;
      overflow-x: hidden;
    }}
    code {{ overflow-wrap: anywhere; }}
    .dashboard-header {{
      background: #17202a;
      color: white;
      padding: 28px max(18px, 5vw);
      border-bottom: 4px solid #57a773;
    }}
    .dashboard-header h1 {{
      margin: 0 0 8px;
      font-size: clamp(22px, 4vw, 30px);
      letter-spacing: 0;
    }}
    .dashboard-header p {{
      margin: 0;
      color: #d8e0e8;
      max-width: 1080px;
      overflow-wrap: anywhere;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .page-nav {{
      margin-top: 18px;
    }}
    .report-nav {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(255, 255, 255, .18);
    }}
    nav a {{
      color: white;
      text-decoration: none;
      border: 1px solid rgba(255, 255, 255, .28);
      padding: 7px 10px;
      border-radius: 6px;
      background: rgba(255, 255, 255, .08);
      min-height: 34px;
    }}
    nav a:focus-visible {{
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }}
    .page-nav a.active {{
      background: #57a773;
      border-color: #57a773;
      color: #17202a;
      font-weight: 700;
    }}
    .report-nav a {{
      background: rgba(255, 255, 255, .03);
      color: #edf4f7;
    }}
    main {{
      padding: 24px max(18px, 5vw) 48px;
    }}
    section {{
      margin: 0 0 22px;
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(23, 32, 42, .05);
      max-width: 100%;
      overflow: visible;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    h3 {{
      margin: 18px 0 8px;
      font-size: 15px;
      color: #34495e;
      letter-spacing: 0;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .kpi, .fact {{
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .kpi-label, .fact span, .kpi span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .kpi-value, .kpi strong, .fact strong {{
      display: block;
      font-size: 24px;
      font-weight: 700;
      margin-top: 4px;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }}
    .kpi-note {{
      color: var(--muted);
      font-size: 12px;
      min-height: 18px;
    }}
    .note {{
      background: #f6f8f2;
      border-left: 4px solid #8aa936;
      padding: 12px 14px;
      color: #34412d;
      margin-bottom: 14px;
    }}
    .warning {{
      background: #fff8e8;
      border-left-color: var(--warn);
      color: #4d3b13;
    }}
    .metric-glossary {{
      border-top: 4px solid #5c7f95;
    }}
    .metric-glossary dl {{
      margin: 0;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
      gap: 10px;
    }}
    .metric-glossary dl > div {{
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .metric-glossary dt {{
      margin: 0 0 5px;
      font-weight: 700;
    }}
    .metric-glossary dd {{
      margin: 0;
      color: var(--muted);
    }}
    .table-scroll, .scroll, .summary-comparison {{
      max-width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    table {{
      width: 100%;
      min-width: {table_min_width};
      border-collapse: separate;
      border-spacing: 0;
      font-size: 13px;
      font-variant-numeric: tabular-nums;
    }}
    th, td {{
      padding: 8px 9px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
      vertical-align: top;
    }}
    th:first-child, td:first-child {{
      text-align: left;
      position: sticky;
      left: 0;
      z-index: 1;
      box-shadow: 1px 0 0 var(--line);
    }}
    th:first-child {{
      z-index: 3;
    }}
    td:first-child {{
      background: var(--panel);
      font-weight: 600;
    }}
    th {{
      color: #3f4d5c;
      background: #eef3f6;
      font-weight: 700;
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    tbody tr:nth-child(even) td {{
      background: #fbfcfd;
    }}
    tbody tr:hover td {{
      background: #eef6f2;
    }}
    .positive {{
      color: var(--good);
      font-weight: 700;
    }}
    .negative {{
      color: var(--bad);
      font-weight: 700;
    }}
    .neutral {{
      color: var(--muted);
    }}
    footer {{
      color: var(--muted);
      padding: 0 max(18px, 5vw) 28px;
    }}
    {extra_css}
    @media (max-width: 760px) {{
      .dashboard-header {{
        padding: 22px 16px;
      }}
      nav a {{
        flex: 1 1 auto;
        text-align: center;
      }}
      main {{
        padding: 16px 12px 34px;
      }}
      section {{
        padding: 14px;
        margin-bottom: 16px;
      }}
      h2 {{
        font-size: 18px;
      }}
      h3 {{
        font-size: 14px;
      }}
      .kpis {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
      }}
      .kpi {{
        padding: 10px;
      }}
      .kpi-value, .kpi strong, .fact strong {{
        font-size: 20px;
      }}
      th, td {{
        padding: 6px 7px;
        font-size: 12px;
      }}
    }}
    @media (max-width: 480px) {{
      .kpis {{
        grid-template-columns: 1fr;
      }}
      .report-nav a {{
        flex-basis: calc(50% - 4px);
      }}
    }}
    """
