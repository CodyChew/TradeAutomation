from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    load_dashboard_metadata,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "live_ops.html"

TITLE = "LP + Force Strike Live Ops"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _fact_grid(facts: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"""
        <article class="ops-fact">
          <span>{_escape(label)}</span>
          <strong>{_escape(value)}</strong>
          <p>{_escape(note)}</p>
        </article>
        """
        for label, value, note in facts
    )


def _step_cards(items: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"""
        <article class="step-card">
          <span>{_escape(kind)}</span>
          <h3>{_escape(title)}</h3>
          <p>{_escape(body)}</p>
        </article>
        """
        for kind, title, body in items
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"""
    <div class="table-scroll">
      <table>
        <thead><tr>{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


LIVE_OPS_EXTRA_CSS = """
    .ops-hero {
      border-top: 4px solid var(--accent);
    }
    .ops-grid,
    .scenario-grid,
    .checklist-grid,
    .file-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .ops-fact,
    .step-card,
    .checklist-card,
    .file-card {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .ops-fact span,
    .step-card span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
      margin-bottom: 5px;
    }
    .ops-fact strong {
      display: block;
      font-size: 20px;
      line-height: 1.25;
      margin-bottom: 6px;
      font-variant-numeric: tabular-nums;
    }
    .ops-fact p,
    .step-card p,
    .file-card p {
      margin: 0;
      color: var(--muted);
    }
    .step-card h3,
    .checklist-card h3,
    .file-card h3 {
      margin: 0 0 7px;
      color: var(--ink);
    }
    .checklist-card ul {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }
    .checklist-card li + li {
      margin-top: 6px;
    }
    .callout {
      background: #f6f8f2;
      border: 1px solid #cbd9af;
      border-left: 4px solid #8aa936;
      border-radius: 8px;
      padding: 12px 14px;
      margin: 0 0 14px;
      color: #34412d;
    }
    .callout.warning {
      background: #fff8e8;
      border-color: #ead4a8;
      border-left-color: var(--warn);
      color: #4d3b13;
    }
    .command-list {
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }
    .command-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
      padding: 12px;
    }
    .command-row strong {
      display: block;
      margin-bottom: 6px;
    }
    .command-row code {
      display: block;
      padding: 10px;
      border-radius: 6px;
      background: #17202a;
      color: white;
      overflow-x: auto;
      white-space: pre;
    }
    .status-good {
      color: var(--good);
      font-weight: 700;
    }
    .status-warn {
      color: var(--warn);
      font-weight: 700;
    }
    .status-bad {
      color: var(--bad);
      font-weight: 700;
    }
    .file-card code {
      overflow-wrap: anywhere;
    }
"""


def build_live_ops_page(output: Path = DEFAULT_OUTPUT) -> Path:
    metadata = load_dashboard_metadata()
    subtitle = (
        "Static verification guide for the guarded MT5 live-send runner. It explains "
        "what proves correctness, which gates allow sends, which gates reconcile "
        "existing orders, and how operators should inspect alerts without embedding "
        "stale broker snapshots."
    )

    proof_facts = [
        (
            "Broker proof",
            "MT5 orders_get / positions_get",
            "Pending orders and open positions under the LPFS magic/comment prove what is currently live at the broker.",
        ),
        (
            "Restart proof",
            "data/live/lpfs_live_state.json",
            "Processed signal keys, pending metadata, active positions, and Telegram message IDs prevent duplicate sends after restart.",
        ),
        (
            "Audit proof",
            "data/live/lpfs_live_journal.jsonl",
            "Every placement, adoption, fill, cancellation, close, skip, and notification outcome is recorded as durable JSONL.",
        ),
        (
            "Runner proof",
            "process + latest cycle row",
            "The process command line and newest cycle summary show whether the intended runner is still checking the intended config.",
        ),
        (
            "Production proof",
            "heartbeat + logs + status command",
            "The Phase 2 wrapper writes a heartbeat JSON file, timestamped logs, and a status packet that can be pasted for review.",
        ),
        (
            "Telegram role",
            "reporting only",
            "Telegram confirms what the runner attempted to report. It is not broker truth and should be checked against MT5/state/journal.",
        ),
        (
            "Dashboard role",
            "static guide",
            "This page intentionally avoids live broker snapshots so it cannot make stale status claims.",
        ),
    ]

    checklist_groups = [
        (
            "Before starting",
            [
                "Confirm MT5 is logged into the intended demo/real account and server.",
                "Confirm config.local.json intentionally enables or disables live_send_enabled for this account.",
                "Confirm the production runtime root is correct if using C:\\TradeAutomationRuntime.",
                "Copy existing live state/journal before switching runtime roots, or explicitly choose a clean state after broker verification.",
                "Confirm KILL_SWITCH exists while staging and is cleared only when new cycles should run.",
                "Check there is no second LPFS runner already active against the same state file.",
                "Inspect open MT5 LPFS orders/positions and compare against lpfs_live_state.json if resuming.",
            ],
        ),
        (
            "While running",
            [
                "Monitor RUNNER STARTED / STOPPED cards and the latest cycle summary.",
                "Monitor lpfs_live_heartbeat.json and the latest timestamped log when using the Phase 2 wrapper.",
                "Use MT5 orders_get / positions_get as the source of truth for open exposure.",
                "Use lpfs_live_journal.jsonl to audit why a setup was sent, skipped, adopted, or cancelled.",
                "Treat spread waits as retryable until entry touch or bar-count expiry makes the setup invalid; after a touch, default-on market recovery can still enter only at a better executable price.",
            ],
        ),
        (
            "After Telegram alert",
            [
                "For ORDER PLACED, verify the ticket exists in MT5 and the same ref exists in state and journal.",
                "For MARKET RECOVERY, verify MT5 shows an open position, not a pending order; TP should be recalculated to 1R from actual fill and the original structure stop.",
                "For ENTERED, verify the pending moved to a position and state moved from pending to active.",
                "For CANCELLED or cancel_failed, verify MT5 broker state first; failed cancellation is retryable on later cycles.",
                "For TAKE PROFIT / STOP LOSS / TRADE CLOSED, verify deal history and journal classification before acting on the label.",
            ],
        ),
    ]
    checklist_html = "\n".join(
        f"""
        <article class="checklist-card">
          <h3>{_escape(title)}</h3>
          <ul>{"".join(f"<li>{_escape(item)}</li>" for item in items)}</ul>
        </article>
        """
        for title, items in checklist_groups
    )

    lifecycle_steps = [
        (
            "Startup",
            "Reconcile broker state first",
            "Every live-send cycle loads atomically persisted local state, pulls MT5 pending orders and positions by strategy magic, checks recent history, then only scans for fresh closed-candle signals.",
        ),
        (
            "Signal",
            "Build a pending or recovery order",
            "A fresh LPFS signal becomes a BUY LIMIT or SELL LIMIT at the 50% signal-candle pullback. If that entry was touched before placement, the default live path may recover with a market order only when the current executable price is same-or-better than the original entry.",
        ),
        (
            "Guard",
            "Check risk, spread, entry freshness",
            "Before order_check, the runner checks duplicate signal keys, actual-bar expiry, missed-entry state, dynamic spread versus risk, stop/target path for recovery, exposure caps, and broker-accurate risk sizing.",
        ),
        (
            "Send",
            "Refresh quote before order_send",
            "Immediately before sending, the runner refreshes the quote, reruns the relevant spread gate, and checks for an already matching broker order/position. Pending orders use TRADE_ACTION_PENDING; market recovery uses TRADE_ACTION_DEAL with deviation controlled by config.",
        ),
        (
            "Manage",
            "Let MT5 be the truth",
            "Open pending orders and positions are reconciled each cycle. Fills, cancellations, expiries, and closes come from MT5 orders, positions, and deal history. Broker-affecting state is saved immediately after each safety mutation.",
        ),
    ]

    scenario_rows = [
        [
            "Pending still open",
            "Every cycle",
            "Keep order unless the actual-bar window expired. Spread widening after placement does not cancel the order and has no dedicated Telegram alert yet.",
        ],
        [
            "Pending expired",
            "Every cycle",
            "Cancel the MT5 order once the first bar after the allowed 6-bar window appears, remove it from active state, and send a cancelled/expired Telegram event. Weekend time does not count.",
        ],
        [
            "Pending filled",
            "Every cycle",
            "Detect a matching MT5 position by comment or broker history linkage, move state from pending to active, and send ENTERED as a reply to the original order card when message_id exists.",
        ],
        [
            "Existing broker item found",
            "Before order_send",
            "If an exact same pending order or already-open matching position exists under the strategy magic/comment, adopt it into local state and do not send a duplicate order.",
        ],
        [
            "Missed entry, better quote",
            "Before final skip",
            "Default-on market recovery may send a market order if current ask for a long is at or below original entry, or current bid for a short is at or above original entry, spread is within 10%, and the stop/target path after first entry touch is still clean.",
        ],
        [
            "Missed entry, worse quote",
            "Retryable WAITING",
            "If current executable price is worse than original entry, no MT5 order is sent, the signal is not processed, and a future cycle can recover before expiry if price returns same-or-better.",
        ],
        [
            "Missed entry, final recovery block",
            "Before final skip",
            "If recovery is disabled, stop/target traded after first entry touch, the 6-bar window expired, path verification failed, or broker validation fails, the setup is skipped or rejected with explicit audit fields.",
        ],
        [
            "Pending missing",
            "Every cycle",
            "If no matching position exists, treat as broker/user removed or rejected, clear state, and alert once.",
        ],
        [
            "Position still open",
            "Every cycle",
            "Keep tracking the position. MT5 remains the source of truth for SL, TP, volume, and position ID.",
        ],
        [
            "Position closed",
            "Every cycle",
            "Query deal history by position ID first, classify TP/SL where possible, compute PnL/R/hold time, then send the close card once. Manual or unknown exits are shown as TRADE CLOSED, not as stop losses.",
        ],
        [
            "Manual trade",
            "Every cycle",
            "Ignored unless it uses the same strategy magic and compact LPFS comment. Manual trades with normal manual magic should not interfere.",
        ],
        [
            "Manual deletion",
            "Every cycle",
            "The exact signal stays processed locally, so the runner will not re-place that same signal unless state/journal are intentionally reset.",
        ],
    ]

    signal_rows = [
        ["1", "Closed-candle scan", "Signals are based on completed candles, not the forming candle."],
        ["2", "Duplicate key check", "Same symbol, timeframe, direction, LP setup, and signal close time is processed once."],
        ["3", "Missed-entry recovery", "If price already touched the planned entry after the signal, default-on recovery may send a market order only at a better executable price."],
        ["4", "Actual-bar expiry", "Strategy expiry is after 6 actual MT5 bars from the signal candle; weekend gaps pause the count."],
        ["5", "Spread gate", "Current spread must be no more than 10% of entry-to-stop risk distance."],
        ["6", "Risk sizing", "MT5 order_calc_profit sizes the order, floors to volume_step, caps by broker/local max, and rejects below volume_min."],
        ["7", "Recovery path guard", "For market recovery, original stop and original 1R target must not have traded after the signal before recovery."],
        ["8", "Broker validation", "order_check must pass before any live send; pending requests carry the conservative broker backstop."],
        ["9", "Final send", "Pending sends place TRADE_ACTION_PENDING. Recovery sends TRADE_ACTION_DEAL with zero slippage by default."],
    ]

    commands = [
        (
            "Run one live-send cycle",
            r".\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 1",
        ),
        (
            "Run repeated cycles",
            r".\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 12 --sleep-seconds 300",
        ),
        (
            "Run until manually stopped",
            r".\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 100000000 --sleep-seconds 30",
        ),
        (
            "Set production kill switch",
            r'.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "operator stop"',
        ),
        (
            "Clear production kill switch",
            r".\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Clear",
        ),
        (
            "Start production watchdog",
            r".\scripts\run_lpfs_live_forever.ps1 -ConfigPath config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30",
        ),
        (
            "Pasteable production status",
            r".\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 20 -LogLines 40",
        ),
        (
            "Print recent trade summary",
            r".\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --limit 5",
        ),
        (
            "Post recent trade summary to Telegram",
            r".\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --limit 5 --post-telegram",
        ),
        (
            "Run strict core coverage",
            r".\venv\Scripts\python scripts\run_core_coverage.py",
        ),
    ]
    command_html = "\n".join(
        f"""
        <div class="command-row">
          <strong>{_escape(label)}</strong>
          <code>{_escape(command)}</code>
        </div>
        """
        for label, command in commands
    )

    vps_operator_commands = [
        (
            "Primary VPS status packet",
            r"""cd C:\TradeAutomation
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60""",
        ),
        (
            "Check the installed production task",
            r"""Get-ScheduledTask -TaskName "LPFS_Live"
Get-ScheduledTaskInfo -TaskName "LPFS_Live" """.strip(),
        ),
        (
            "Check for live runner processes",
            r"""Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor|run_lpfs_live_forever" } |
    Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine""",
        ),
        (
            "Confirm one logical Windows venv runner",
            r"""Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor" } |
    Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine

# processes=2 is expected when one entry is venv\Scripts\python.exe
# and the other entry is its child C:\Program Files\Python312\python.exe.""",
        ),
        (
            "Read heartbeat JSON",
            r"""Get-Content C:\TradeAutomationRuntime\data\live\lpfs_live_heartbeat.json -Raw |
    ConvertFrom-Json |
    ConvertTo-Json -Depth 20""",
        ),
        (
            "Read latest wrapper log",
            r"""$LatestLog = Get-ChildItem C:\TradeAutomationRuntime\data\live\logs -Filter "lpfs_live_*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
Get-Content $LatestLog.FullName -Tail 80""",
        ),
        (
            "Pause new live cycles",
            r'.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "operator stop"',
        ),
        (
            "Resume intentionally from paused VPS state",
            r"""Remove-Item "C:\TradeAutomationRuntime\data\live\KILL_SWITCH" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "LPFS_Live"
Start-Sleep -Seconds 60
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60""",
        ),
        (
            "Recover from suspected duplicate runner processes",
            r""".\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "duplicate runner check"
Start-Sleep -Seconds 90
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60""",
        ),
        (
            "Hard-stop remaining LPFS runners only after graceful wait",
            r"""Stop-ScheduledTask -TaskName "LPFS_Live" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }""",
        ),
    ]
    vps_operator_command_html = "\n".join(
        f"""
        <div class="command-row">
          <strong>{_escape(label)}</strong>
          <code>{_escape(command)}</code>
        </div>
        """
        for label, command in vps_operator_commands
    )

    file_cards = [
        (
            "Live runner",
            "scripts/run_lp_force_strike_live_executor.py",
            "CLI wrapper for cycle count, sleep interval, runtime-root override, kill switch, heartbeat, lock, and lifecycle notifications.",
        ),
        (
            "Watchdog launcher",
            "scripts/run_lpfs_live_forever.ps1",
            "Production PowerShell wrapper that logs stdout/stderr and restarts after unexpected crashes while respecting KILL_SWITCH.",
        ),
        (
            "Status command",
            "scripts/Get-LpfsLiveStatus.ps1",
            "Pasteable operator snapshot for process, heartbeat, state, journal, and latest log.",
        ),
        (
            "Kill switch helper",
            "scripts/Set-LpfsKillSwitch.ps1",
            "Creates or clears the runtime KILL_SWITCH file used to stop new live cycles.",
        ),
        (
            "Live engine",
            "strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py",
            "Live-send guards, MT5 request construction, reconciliation, and lifecycle notifications.",
        ),
        (
            "Execution contract",
            "docs/mt5_execution_contract.md",
            "Operational contract for order keys, duplicate prevention, and MT5 source-of-truth behavior.",
        ),
        (
            "Phase 2 plan",
            "docs/phase2_production_hardening.md",
            "Implemented local production-hardening runbook for launcher, kill switch, watchdog, runtime folder, Task Scheduler, and VPS readiness.",
        ),
        (
            "Lightsail runbook",
            "docs/lpfs_lightsail_vps_runbook.md",
            "Amazon Lightsail Windows VPS setup, security, cost sizing, Task Scheduler, and liaison packet.",
        ),
        (
            "State file",
            "data/live/lpfs_live_state.json",
            "Restart continuity, processed signal keys, pending orders, active positions, Telegram message IDs.",
        ),
        (
            "Journal",
            "data/live/lpfs_live_journal.jsonl",
            "Durable audit log with raw technical fields and notification payloads.",
        ),
        (
            "Handoff",
            "SESSION_HANDOFF.md",
            "Current project snapshot for the next Codex run.",
        ),
    ]

    html_text = rf"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(TITLE)}</title>
  <style>
    {dashboard_base_css(table_min_width="900px", extra_css=LIVE_OPS_EXTRA_CSS)}
  </style>
</head>
<body>
  {dashboard_header_html(
      title=TITLE,
      subtitle_html=_escape(subtitle),
      current_page="live_ops.html",
      section_links=[
          ("#proof", "Proof"),
          ("#operator-checklist", "Checklist"),
          ("#send-gates", "Send Gates"),
          ("#reconciliation-gates", "Reconcile"),
          ("#pending-expiry", "Expiry"),
          ("#telegram", "Telegram"),
          ("#vps-operator", "VPS"),
          ("#commands", "Commands"),
          ("#limits", "Limits"),
          ("#files", "Files"),
      ],
      metadata=metadata,
  )}
  <main>
    <section id="proof" class="ops-hero" aria-labelledby="proof-title">
      <div class="eyebrow">Static Verification Guide</div>
      <h2 id="proof-title">What Proves The Runner Is Correct</h2>
      <p class="callout warning"><strong>Real orders can be sent.</strong> Correctness is proven from MT5 broker state, local state, and journal rows. Telegram is useful for operator awareness, but Telegram is reporting only and does not prove broker state.</p>
      <div class="ops-grid">
        {_fact_grid(proof_facts)}
      </div>
    </section>

    <section id="operator-checklist" aria-labelledby="operator-checklist-title">
      <h2 id="operator-checklist-title">Operator Checklist</h2>
      <p class="callout">Use this checklist to verify live correctness without relying on stale dashboard status. It separates setup checks, running checks, and alert follow-up.</p>
      <div class="checklist-grid">
        {checklist_html}
      </div>
    </section>

    <section id="send-gates" aria-labelledby="send-gates-title">
      <h2 id="send-gates-title">Send Gates</h2>
      <p class="callout">The runner sends only after the signal is valid, the entry is still fresh, spread is acceptable, exposure and sizing pass, broker order_check passes, and the final refreshed quote still passes spread.</p>
      {_table(["Step", "Gate", "Meaning"], signal_rows)}
    </section>

    <section id="spread-policy" aria-labelledby="spread-policy-title">
      <h2 id="spread-policy-title">Spread Policy</h2>
      <p class="callout"><strong>Current behavior:</strong> a setup blocked because spread is too wide stays retryable. The runner records one WAITING alert, does not mark the signal processed, and can place the pending order on a future cycle if spread improves while the setup is still valid.</p>
      <p class="callout"><strong>Market recovery:</strong> if spread was too wide first and the entry later touches before a pending order exists, the default live path tries a better-than-entry market recovery. It sends only if the current executable price is same-or-better than the original pending entry and spread is still no more than 10% of actual fill-to-stop risk. Worse-than-entry quotes are WAITING, not permanently skipped, while the actual 6-bar window remains open.</p>
      <p class="callout warning"><strong>Weekly-open observation:</strong> first live VPS market-open monitoring showed multiple WAITING cards where spread was far above the 10% risk-distance limit, followed by missed-entry recovery checks. Market recovery reduces this forward/backtest drift when a later live quote becomes same-or-better than the backtested entry and the stop/target path after first entry touch remains clean.</p>
      <div class="ops-grid">
        {_fact_grid([
            ("Check cadence", "Once per live cycle", "Default sleep is 30 seconds only when the runner is started with cycles greater than one."),
            ("Before placement", "Retryable WAITING", "If spread is above 10% of risk distance, no order is placed yet and the same signal can be checked again."),
            ("After missed touch", "Default recovery", "If the pending entry was touched before placement, market recovery is attempted at a same-or-better executable price before final skip."),
            ("Recovery price", "Same-or-better", "Long recovery requires ask <= original entry. Short recovery requires bid >= original entry. Worse prices stay retryable WAITING until expiry or path invalidation."),
            ("Recovery path", "From first touch", "Stop/target movement after first entry touch blocks late recovery; pre-touch target movement does not by itself skip the setup."),
            ("Recovery TP", "Recalculated 1R", "The original structure stop is kept and TP is reset to 1R from the actual market fill."),
            ("Before order_send", "Final quote refresh", "After order_check passes, spread is checked again immediately before live order_send."),
            ("After placement", "No spread cancel", "Once pending, spread widening does not remove the order by default."),
            ("Order removal", "Expiry / fill / broker removal", "The pending order is kept until it fills, reaches expiry and is cancelled, or MT5 shows it was removed/rejected."),
            ("NZDCHF example", "11.5% vs 10.0%", "With the patched policy, this means wait. A future cycle can place the order if spread improves before entry touch or expiry."),
            ("Cycle summary", "setups_blocked", "Spread-only waits are counted separately from real rejected setups in the live cycle audit row."),
            ("Evidence task", "Live gate attribution", "Before tuning the 10% gate, measure detected setups, placed orders, spread waits, later placements, entry-touch skips, expiries, and whether blocks cluster around weekly open."),
        ])}
      </div>
    </section>

    <section id="reconciliation-gates" aria-labelledby="reconciliation-gates-title">
      <h2 id="reconciliation-gates-title">Reconciliation Gates</h2>
      <p class="callout">Existing pending orders and positions are managed from broker evidence first. Reconciliation runs at the start of each cycle before new signals are scanned.</p>
      {_table(["Scenario", "When checked", "Action"], scenario_rows)}
    </section>

    <section id="pending-expiry" aria-labelledby="pending-expiry-title">
      <h2 id="pending-expiry-title">Bar-Counted Pending Expiry</h2>
      <p class="callout warning"><strong>Strategy expiry is after 6 actual MT5 bars from the signal candle.</strong> Broker expiry is only a conservative emergency backstop for runner-down protection, not the strategy decision rule.</p>
      <div class="ops-grid">
        {_fact_grid([
            ("Signal early Friday", "Friday bars count", "Any real broker candles that close after the signal count normally before the weekend gap."),
            ("Final Friday candle", "Weekend pauses", "No Saturday/Sunday bars form, so the first post-open closed candle becomes the next counted bar."),
            ("Runner online", "Exact cancellation", "The runner cancels on reconciliation once more than the allowed actual bars have closed after the signal candle."),
            ("Runner offline", "Backstop only", "The broker-side ORDER_TIME_SPECIFIED expiration can protect only after its conservative calendar backstop."),
        ])}
      </div>
    </section>

    <section id="telegram" aria-labelledby="telegram-title">
      <h2 id="telegram-title">Telegram Alerts</h2>
      <div class="ops-grid">
        {_fact_grid([
            ("ORDER PLACED", "Standalone card", "Ticket, market, entry/SL/TP, actual/target risk, size, spread, expiry, ref."),
            ("MARKET RECOVERY", "Standalone card", "Position/deal, original entry, actual fill, original stop, recalculated TP, actual/target risk, size, spread, touch high/low/time, ref."),
            ("ENTERED", "Reply to order", "Fill time/price, position ID, volume, SL/TP, risk, ref."),
            ("TAKE PROFIT / STOP LOSS", "Reply to order", "Exit price/time, PnL, R, hold time, deal ticket, position ID, ref."),
            ("ORDER ADOPTED / TRADE CLOSED", "Recovery and manual exits", "Adopted broker items are not resent; manual/unknown exits keep real MT5 PnL and R without a false SL label."),
            ("SKIPPED / REJECTED / CANCELLED", "Readable reason", "Human reason, action taken, key metric, and ref. Raw fields remain in JSONL."),
            ("RUNNER STARTED / STOPPED", "Process heartbeat", "Cadence, cycle count, runtime, state-save status, and SGT start/stop time."),
        ])}
      </div>
      <p class="callout">Telegram delivery is best effort. A failed Telegram send must never validate or invalidate a trade. The journal remains the durable audit record.</p>
    </section>

    <section id="vps-operator" aria-labelledby="vps-operator-title">
      <h2 id="vps-operator-title">VPS Operator Quick Reference</h2>
      <p class="callout warning"><strong>Installed VPS baseline:</strong> final task <code>LPFS_Live</code> is installed, MT5 is the broker source of truth, and the runtime folder is <code>C:\TradeAutomationRuntime</code>. Do not rely on this static page for current process state; run the status packet.</p>
      <div class="ops-grid">
        {_fact_grid([
            ("Code path", "C:\\TradeAutomation", "Repository clone used by the Lightsail production task."),
            ("Runtime root", "C:\\TradeAutomationRuntime", "State, journal, heartbeat, kill switch, and logs live outside OneDrive."),
            ("Scheduled task", "LPFS_Live", "At-logon task that starts the production wrapper with 100000000 cycles and 30-second cadence."),
            ("Recovery rollback", "market_recovery_mode=disabled", "Set this local live_send flag only if operator evidence shows recovery should be paused."),
            ("Safe paused state", "KILL_SWITCH exists", "Task can be installed and ready while live cycles are blocked."),
            ("Broker truth", "MT5 orders/positions", "Use MT5 as the source of truth for open exposure; Telegram is an alert channel."),
            ("Codex packet", "Get-LpfsLiveStatus", "Paste status, MT5 screenshots, and Telegram alert context when asking for inspection."),
        ])}
      </div>
      <p class="callout">Do not run the local PC runner and the VPS runner at the same time. After RDP review, disconnect instead of signing out so the interactive MT5 session stays open.</p>
      <p class="callout warning"><strong>Windows process count:</strong> <code>processes=2</code> can be one healthy logical runner when <code>parent_pid</code> links <code>venv\Scripts\python.exe</code> to its child <code>C:\Program Files\Python312\python.exe</code>. Treat it as suspicious only if the parent/child link is absent, configs/runtime roots differ, the heartbeat is stale, or there are more than two runner entries.</p>
      <div class="command-list">
        {vps_operator_command_html}
      </div>
    </section>

    <section id="commands" aria-labelledby="commands-title">
      <h2 id="commands-title">Operator Commands</h2>
      <p>Run these from the repository root after confirming <code>config.local.json</code> is intentionally set for the target account.</p>
      <div class="command-list">
        {command_html}
      </div>
    </section>

    <section id="limits" aria-labelledby="limits-title">
      <h2 id="limits-title">Known Operating Limits</h2>
      <div class="scenario-grid">
        {_step_cards([
            ("Limit", "Not a daemon", "The runner only keeps checking when started with multiple cycles or wrapped by an external scheduler/process manager."),
            ("Protection", "Single-runner lock", "A lock file beside the live state blocks a second live runner from starting against the same state."),
            ("Phase 2", "Production wrapper", "The wrapper adds a launcher, kill switch, watchdog, logs, heartbeat, runtime-root override, Task Scheduler rehearsal path, and Lightsail runbook."),
            ("Protection", "Kill switch", "KILL_SWITCH stops new live cycles before MT5 initialization, before each live cycle, and during sleeps. It does not close positions or delete pending orders by itself."),
            ("Limit", "No spread auto-cancel", "Spread is a send gate. Once an order is pending, spread widening does not cancel it and does not have a dedicated Telegram alert yet."),
            ("Limit", "Forward/backtest drift", "Live recovery narrows missed-entry drift but still skips on expiry, path invalidation after first touch, broker rejection, or disabled recovery."),
            ("Limit", "Manual deletion is respected", "Deleting a pending order manually does not automatically re-arm that same signal because the signal key stays processed."),
            ("Limit", "Close reason depends on broker history", "TP/SL classification uses MT5 deal/order history. Ambiguous broker comments may fall back to a less specific close alert."),
        ])}
      </div>
    </section>

    <section id="files" aria-labelledby="files-title">
      <h2 id="files-title">Where To Inspect The Implementation</h2>
      <div class="file-grid">
        {"".join(f'<article class="file-card"><h3>{_escape(title)}</h3><p><code>{_escape(path)}</code></p><p>{_escape(note)}</p></article>' for title, path, note in file_cards)}
      </div>
    </section>
  </main>
  <footer>Generated static live-ops guide. Current broker state must be checked from MT5, live state, and the JSONL journal.</footer>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LP + Force Strike live ops dashboard page.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_live_ops_page(Path(args.output))
    print(f"live_ops_page={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
