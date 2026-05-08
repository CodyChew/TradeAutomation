from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import dashboard_base_css, dashboard_header_html
from export_lpfs_ea_fixtures import BASE_RISK_PROFILES


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "ea_migration.html"


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _profile_rows() -> str:
    rows = []
    for profile, payload in BASE_RISK_PROFILES.items():
        buckets = payload["risk_buckets_pct"]
        rows.append(
            "<tr>"
            f"<td>{_escape(profile)}</td>"
            f"<td>{buckets['H4']:.2f}% / {buckets['H8']:.2f}%</td>"
            f"<td>{buckets['H12']:.2f}% / {buckets['D1']:.2f}%</td>"
            f"<td>{buckets['W1']:.2f}%</td>"
            f"<td>{payload['max_open_risk_pct']:.2f}%</td>"
            f"<td>{payload['max_concurrent_trades']}</td>"
            "</tr>"
        )
    return "".join(rows)


def build_page(output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LPFS Native MQL5 EA Migration</title>
  <style>
{dashboard_base_css()}
    .status-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    .status-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #ffffff;
    }}
    .status-card span {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .status-card strong {{
      display: block;
      margin-top: 6px;
      font-size: 17px;
    }}
    .warning {{
      border-left: 4px solid #a23b3b;
      background: #fff6f4;
      padding: 14px;
    }}
    .ok {{
      border-left: 4px solid #2e7d50;
      background: #f3fbf6;
      padding: 14px;
    }}
  </style>
</head>
<body>
{dashboard_header_html(
    title="LPFS Native MQL5 EA Migration",
    subtitle_html="Native MT5 Strategy Tester-only port status for LP + Force Strike. Python remains canonical until EA parity, compile, and tester smoke checks pass.",
    current_page="ea_migration.html",
    section_links=[
        ("#status", "Status"),
        ("#risk-profiles", "Risk Profiles"),
        ("#safety", "Live Safety"),
        ("#operator-followups", "MT5 Follow-Ups"),
        ("#files", "Files"),
    ],
)}
  <main>
    <section id="status" class="panel">
      <h2>Current EA Status</h2>
      <div class="status-grid">
        <div class="status-card"><span>Port stage</span><strong>Scaffolded / tester-only</strong></div>
        <div class="status-card"><span>Python truth</span><strong>V13 + V15 + V22</strong></div>
        <div class="status-card"><span>EA parity</span><strong>Fixture harness added; MetaEditor compile passed; tester load/config smoke passed</strong></div>
        <div class="status-card"><span>Next task</span><strong>Add single-chart smoke mode and new-bar gating</strong></div>
        <div class="status-card"><span>Live impact</span><strong>No VPS, config, state, journal, or order changes</strong></div>
      </div>
      <p class="ok"><strong>Boundary:</strong> EA migration files are isolated under <code>mql5/lpfs_ea/</code>. The FTMO and IC Python live runners remain production truth until a separate EA demo/live deployment plan is approved.</p>
      <p class="warning"><strong>Tester observation:</strong> the first EURUSD H4 Strategy Tester run loaded the EA and printed the LPFS configuration, but was intentionally stopped because the scaffold currently requests the full 28-symbol x 5-timeframe basket on every tick. Do not run another long full-basket smoke before adding <code>InpSmokeTestSingleChartOnly</code> and new-bar gating.</p>
    </section>

    <section id="risk-profiles" class="panel">
      <h2>Blackbox Risk Profiles</h2>
      <p>Users choose a tested profile instead of editing raw LPFS buckets. Every tester run must disclose the effective schedule so the backtest remains auditable.</p>
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>Profile</th><th>H4/H8</th><th>H12/D1</th><th>W1</th><th>Max Open Risk</th><th>Max Trades</th></tr></thead>
          <tbody>{_profile_rows()}</tbody>
        </table>
      </div>
      <p class="source-note">Raw bucket editing is intentionally deferred. The EA exposes profile, open-risk caps, concurrency caps, MagicNumber, CommentPrefix, and logging controls. A cap value of <code>0</code> uses the selected profile default.</p>
    </section>

    <section id="safety" class="panel">
      <h2>Live Safety Boundary</h2>
      <p class="warning"><strong>Tester-only v1:</strong> the EA must refuse to initialize outside Strategy Tester while <code>InpTesterOnly=true</code> and <code>InpAllowLiveTrading=false</code>. Do not attach it to FTMO or IC live charts.</p>
      <ul>
        <li>Default EA identity: <code>MagicNumber=331500</code>, <code>CommentPrefix=LPFSEA</code>.</li>
        <li>Does not collide with FTMO <code>131500/LPFS</code> or IC <code>231500/LPFSIC</code>.</li>
        <li>No live configs, VPS scheduled tasks, runtime state, JSONL journals, Telegram channels, or broker orders are part of this migration slice.</li>
      </ul>
    </section>

    <section id="operator-followups" class="panel">
      <h2>Operator Follow-Ups For MT5</h2>
      <ol>
        <li>Install or confirm MT5 with MetaEditor available on a local test terminal.</li>
        <li>Keep the EA test terminal separate from FTMO and IC production terminals.</li>
        <li>Compile <code>mql5/lpfs_ea/Experts/LPFS/LPFS_EA.mq5</code> using the helper script or MetaEditor.</li>
        <li>Next code change: add <code>InpSmokeTestSingleChartOnly=true</code> and scan only <code>_Symbol/_Period</code> for first smoke tests.</li>
        <li>After that patch, run Strategy Tester with one symbol first, real ticks or highest-quality ticks available, then save tester reports for Conservative, Standard, and Growth.</li>
      </ol>
    </section>

    <section id="files" class="panel">
      <h2>Migration Files</h2>
      <div class="card-grid">
        <article class="file-card"><h3>EA source</h3><p><code>mql5/lpfs_ea/Experts/LPFS/LPFS_EA.mq5</code></p><p>Native tester-only MQL5 scaffold with blackbox inputs, profile disclosure, LP/FS detector port, and guarded pending-order path.</p></article>
        <article class="file-card"><h3>Parity fixtures</h3><p><code>mql5/lpfs_ea/fixtures/canonical_lpfs_ea_fixture.json</code></p><p>Small Python-generated parity cases for signal and execution contract matching.</p></article>
        <article class="file-card"><h3>Fixture exporter</h3><p><code>scripts/export_lpfs_ea_fixtures.py</code></p><p>Regenerates canonical fixtures from Python truth after strategy changes.</p></article>
        <article class="file-card"><h3>Compile helper</h3><p><code>mql5/lpfs_ea/scripts/Compile-LpfsEa.ps1</code></p><p>Local MetaEditor compile wrapper. It does not touch live terminals or VPS runtime folders.</p></article>
      </div>
    </section>
  </main>
</body>
</html>
"""
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    build_page()
    print(f"Wrote {DEFAULT_OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
