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


def experiment_summary_html(page: dict[str, Any]) -> str:
    """Render the common top-of-page interpretation block."""

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
