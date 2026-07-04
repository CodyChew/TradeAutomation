from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import dashboard_base_css, dashboard_header_html


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "dashboards" / "lpfs_command_center.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "lpfs_command_center.html"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _status_class(value: Any) -> str:
    text = str(value or "").lower()
    if any(token in text for token in ("running", "complete", "true", "ok", "sent")):
        return "good"
    if any(token in text for token in ("watch", "warning", "incomplete", "ambiguous")):
        return "warn"
    if any(token in text for token in ("fail", "blocked", "rejected", "false", "disabled")):
        return "bad"
    return "neutral"


def _chip(label: str, value: Any) -> str:
    kind = _status_class(value)
    return f'<span class="chip chip-{kind}"><strong>{_escape(label)}</strong>{_escape(value)}</span>'


def _kpi(label: str, value: Any, note: Any = "") -> str:
    note_html = f'<span class="kpi-note">{_escape(note)}</span>' if note else ""
    return f"""
      <div class="kpi">
        <span>{_escape(label)}</span>
        <strong>{_escape(value)}</strong>
        {note_html}
      </div>
    """


def _link(href: str, label: str) -> str:
    href_text = str(href)
    if href_text.startswith("C:\\"):
        href_text = href_text.replace("\\", "/")
    return f'<a href="{_escape(href_text)}">{_escape(label)}</a>'


def _list(items: list[Any]) -> str:
    if not items:
        return '<p class="empty">No rows recorded.</p>'
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>"


def _operating_boundary_section(config: dict[str, Any]) -> str:
    boundary = config["operating_boundary"]
    lanes = _rows(boundary.get("lanes"))
    lane_cards = []
    for lane in lanes:
        lane_cards.append(
            f"""
        <article class="lane-card">
          <h3>{_escape(lane.get("name"))}</h3>
          <div class="chip-row">
            {_chip("state", lane.get("lane_state"))}
            {_chip("heartbeat", lane.get("heartbeat"))}
            {_chip("broker", lane.get("broker_status"))}
            {_chip("recovery", lane.get("recovery_mode"))}
          </div>
          <div class="fact-grid compact-facts">
            {_kpi("task", lane.get("task"))}
            {_kpi("runner path", lane.get("runner_shape"))}
            {_kpi("kill switch", lane.get("kill_switch"))}
            {_kpi("pending", lane.get("pending_orders"))}
            {_kpi("active", lane.get("active_positions"))}
            {_kpi("mismatch", lane.get("state_broker_mismatch_count"))}
            {_kpi("telemetry failures", lane.get("telemetry_failures"))}
            {_kpi("market-data failures", lane.get("market_data_fetch_failures"))}
          </div>
        </article>
            """
        )
    return f"""
    <section id="operating-boundary">
      <h2>Current Operating Boundary</h2>
      <p class="section-note">{_escape(boundary.get("summary"))}</p>
      <p class="callout warning">{_escape(boundary.get("truth_boundary"))}</p>
      <div class="evidence-strip">
        <div><span>Status packet</span><strong>{_escape(boundary.get("status_packet_path"))}</strong></div>
        <div><span>Status SHA-256</span><strong>{_escape(boundary.get("status_packet_sha256"))}</strong></div>
        <div><span>Packet manifest SHA-256</span><strong>{_escape(boundary.get("status_packet_manifest_sha256"))}</strong></div>
      </div>
      <div class="lane-grid">
        {"".join(lane_cards)}
      </div>
    </section>
    """


def _weekly_section(config: dict[str, Any]) -> str:
    weekly = config["weekly_evidence"]
    lanes = _rows(weekly.get("lanes"))
    body = []
    for lane in lanes:
        body.append(
            "<tr>"
            f"<td>{_escape(lane.get('lane'))}</td>"
            f"<td>{_escape(lane.get('analysis_eligible'))}</td>"
            f"<td>{_escape(lane.get('coverage_status'))}</td>"
            f"<td>{_escape(lane.get('performance_confidence'))}</td>"
            f"<td>{_escape(lane.get('closed_trades'))}</td>"
            f"<td>{_escape(lane.get('wins'))}/{_escape(lane.get('losses'))}</td>"
            f"<td>{_escape(lane.get('win_rate'))}</td>"
            f"<td>{_escape(lane.get('net_r'))}</td>"
            f"<td>{_escape(lane.get('broker_pnl'))}</td>"
            f"<td>{_escape(lane.get('profit_factor'))}</td>"
            f"<td>{_escape(lane.get('historical_percentile_band'))}</td>"
            f"<td>{_escape(lane.get('account_outcome_status'))}</td>"
            f"<td>{_escape(lane.get('r_pnl_alignment'))}</td>"
            "</tr>"
        )
    readouts = []
    for lane in lanes:
        readouts.append(
            f"""
        <article class="readout">
          <h3>{_escape(lane.get("lane"))}</h3>
          <p><strong>What is working:</strong> {_escape(lane.get("working"))}</p>
          <p><strong>Weak / under investigation:</strong> {_escape(lane.get("weak"))}</p>
        </article>
            """
        )
    return f"""
    <section id="weekly-evidence">
      <h2>Can This Packet Be Analyzed?</h2>
      <div class="chip-row">
        {_chip("analysis_eligible", weekly.get("analysis_eligible"))}
        {_chip("coverage_status", weekly.get("coverage_status"))}
        {_chip("performance_confidence", weekly.get("performance_confidence"))}
      </div>
      <p class="section-note">{_escape(weekly.get("freshness_note"))}</p>
      <div class="evidence-strip">
        <div><span>weekly_packet_path</span><strong>{_escape(weekly.get("weekly_packet_path"))}</strong></div>
        <div><span>weekly_packet_manifest_sha256</span><strong>{_escape(weekly.get("weekly_packet_manifest_sha256"))}</strong></div>
        <div><span>weekly_summary_sha256</span><strong>{_escape(weekly.get("weekly_summary_sha256"))}</strong></div>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>Lane</th><th>analysis_eligible</th><th>coverage_status</th>
              <th>performance_confidence</th><th>Closed</th><th>W/L</th>
              <th>Win rate</th><th>Net R</th><th>Broker PnL</th><th>PF</th>
              <th>Band</th><th>account_outcome_status</th><th>R/PnL alignment</th>
            </tr>
          </thead>
          <tbody>
            {"".join(body)}
          </tbody>
        </table>
      </div>
      <div class="readout-grid">
        {"".join(readouts)}
      </div>
    </section>
    """


def _strategy_section(config: dict[str, Any]) -> str:
    strategy = config["strategy_context"]
    repo = config["repo_context"]
    return f"""
    <section id="triage">
      <h2>Triage Outcome And Next Action</h2>
      <div class="hero-grid">
        {_kpi("Primary outcome", strategy.get("primary_outcome"), strategy.get("current_decision"))}
        {_kpi("Active strategy", strategy.get("active_strategy"))}
        {_kpi("Deployed runtime SHA", repo.get("latest_deployed_runtime_sha"))}
        {_kpi("Local docs HEAD", repo.get("local_docs_head"))}
      </div>
      <p><strong>What is being tested now:</strong> {_escape(strategy.get("what_is_being_tested"))}</p>
      <p><strong>Next responsible action:</strong> {_escape(strategy.get("next_responsible_action"))}</p>
      <div class="callout stop">
        <strong>Explicitly not approved:</strong>
        {_list(strategy.get("not_approved") or [])}
      </div>
    </section>
    """


def _research_section(config: dict[str, Any]) -> str:
    queue = config["research_queue"]
    candidate_rows = []
    for row in _rows(queue.get("active_candidates")):
        candidate_rows.append(
            f"""
        <article class="candidate">
          <h3>{_escape(row.get("name"))}</h3>
          <span class="status-tag">{_escape(row.get("status"))}</span>
          <p>{_escape(row.get("current_hypothesis"))}</p>
          <p><strong>Next test:</strong> {_escape(row.get("next_test"))}</p>
        </article>
            """
        )
    rejected_rows = []
    for row in _rows(queue.get("rejected_hypotheses")):
        rejected_rows.append(
            f"<tr><td>{_escape(row.get('name'))}</td><td>{_escape(row.get('reason'))}</td></tr>"
        )
    return f"""
    <section id="research-queue">
      <h2>Strategy Research Queue</h2>
      <p class="section-note">Research candidates are not approved live filters. They require offline cohort tagging, backtests, and review before any production change.</p>
      <div class="candidate-grid">
        {"".join(candidate_rows)}
      </div>
      <h3>Rejected Ideas</h3>
      <div class="table-scroll">
        <table class="data-table narrow-table">
          <thead><tr><th>Hypothesis</th><th>Why rejected</th></tr></thead>
          <tbody>{"".join(rejected_rows)}</tbody>
        </table>
      </div>
      <h3>Active Data Gaps</h3>
      {_list(queue.get("data_gaps") or [])}
    </section>
    """


def _drilldowns_section(config: dict[str, Any]) -> str:
    links = []
    for row in _rows(config.get("drilldowns")):
        links.append(
            f"""
        <article class="drilldown-card">
          <h3>{_link(str(row.get("href") or "#"), str(row.get("label") or ""))}</h3>
          <p>{_escape(row.get("purpose"))}</p>
        </article>
            """
        )
    return f"""
    <section id="drilldowns">
      <h2>Evidence Packets And Drilldowns</h2>
      <div class="drilldown-grid">
        {"".join(links)}
      </div>
    </section>
    """


def _ownership_section(config: dict[str, Any]) -> str:
    ownership = config["ownership"]
    return f"""
    <section id="ownership">
      <h2>Ownership And Refresh Workflow</h2>
      <p>{_escape(ownership.get("strategy_agent_reflection"))}</p>
      <div class="two-col">
        <div>
          <h3>Role coverage</h3>
          {_list(ownership.get("role_coverage") or [])}
        </div>
        <div>
          <h3>Maintenance checklist</h3>
          {_list(ownership.get("maintenance_checklist") or [])}
        </div>
      </div>
    </section>
    """


def build_command_center(config_path: Path = DEFAULT_CONFIG, output_path: Path = DEFAULT_OUTPUT) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    page = config["page"]
    extra_css = """
    .source-banner {
      background: #fff8e8;
      border-left: 5px solid var(--warn);
      color: #49370d;
      padding: 14px 16px;
      border-radius: 6px;
      margin-bottom: 18px;
    }
    .hero-grid,
    .fact-grid,
    .lane-grid,
    .readout-grid,
    .candidate-grid,
    .drilldown-grid,
    .two-col {
      display: grid;
      gap: 12px;
    }
    .hero-grid { grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr)); }
    .lane-grid,
    .readout-grid,
    .candidate-grid,
    .drilldown-grid,
    .two-col { grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); }
    .lane-card,
    .readout,
    .candidate,
    .drilldown-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: var(--panel-soft);
    }
    .lane-card h3,
    .readout h3,
    .candidate h3,
    .drilldown-card h3 { margin-top: 0; }
    .compact-facts { grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr)); }
    .compact-facts .kpi strong { font-size: 15px; overflow-wrap: anywhere; }
    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 8px 0 12px;
    }
    .chip,
    .status-tag {
      display: inline-flex;
      gap: 6px;
      align-items: baseline;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: #f7f9fb;
      color: var(--muted);
      font-size: 12px;
    }
    .chip strong { text-transform: uppercase; }
    .chip-good { color: var(--good); background: #eef8f2; border-color: #b9dbc7; }
    .chip-warn { color: var(--warn); background: #fff8e8; border-color: #e7d19a; }
    .chip-bad { color: var(--bad); background: #fff1f1; border-color: #e7bcbc; }
    .evidence-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr));
      gap: 10px;
      margin: 12px 0 16px;
    }
    .evidence-strip div {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfd;
    }
    .evidence-strip span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .evidence-strip strong {
      display: block;
      margin-top: 3px;
      overflow-wrap: anywhere;
      white-space: normal;
    }
    .callout {
      border-left: 5px solid var(--accent);
      background: #f5f8fb;
      padding: 12px 14px;
      border-radius: 6px;
    }
    .callout.warning { border-left-color: var(--warn); background: #fff8e8; }
    .callout.stop { border-left-color: var(--bad); background: #fff1f1; }
    .callout ul { margin-bottom: 0; }
    .narrow-table { min-width: 640px; }
    .empty { color: var(--muted); }
    .section-note { color: var(--muted); }
    """
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(page.get("title"))}</title>
  <style>
    {dashboard_base_css(table_min_width="1180px", extra_css=extra_css)}
  </style>
</head>
<body>
  {dashboard_header_html(
      title=str(page.get("title")),
      subtitle_html=_escape(page.get("subtitle")),
      current_page="lpfs_command_center.html",
      section_links=[
          ("#source", "Source"),
          ("#operating-boundary", "Live/Ops"),
          ("#weekly-evidence", "Weekly"),
          ("#triage", "Next Action"),
          ("#research-queue", "Research"),
          ("#drilldowns", "Drilldowns"),
          ("#ownership", "Ownership"),
      ],
  )}
  <main>
    <section id="source">
      <h2>Source And Freshness</h2>
      <div class="source-banner">
        <strong>Static generated dashboard, not broker truth.</strong>
        {_escape(page.get("freshness_warning"))}
      </div>
      <div class="hero-grid">
        {_kpi("Generated", page.get("generated_at_ict"))}
        {_kpi("source_mode", page.get("source_mode"))}
        {_kpi("Authoritative branch", config["repo_context"].get("current_authoritative_branch"))}
        {_kpi("Primary outcome", config["strategy_context"].get("primary_outcome"))}
      </div>
    </section>
    {_operating_boundary_section(config)}
    {_weekly_section(config)}
    {_strategy_section(config)}
    {_research_section(config)}
    {_drilldowns_section(config)}
    {_ownership_section(config)}
  </main>
  <footer>Generated from configs/dashboards/lpfs_command_center.json by scripts/build_lpfs_command_center.py. It summarizes existing evidence only and performs no live reads.</footer>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static LPFS command-center dashboard.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Input JSON config.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_command_center(Path(args.config), Path(args.output))
    print(f"lpfs_command_center={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
