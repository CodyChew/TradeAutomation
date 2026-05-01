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
    .file-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .ops-fact,
    .step-card,
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
    .file-card h3 {
      margin: 0 0 7px;
      color: var(--ink);
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
        "Operational guide for the guarded MT5 live-send runner: cycle cadence, "
        "order lifecycle, Telegram alerts, and restart behavior. This page is a "
        "static guide, not a live broker-state monitor."
    )

    lifecycle_steps = [
        (
            "Startup",
            "Reconcile broker state first",
            "Every live-send cycle loads atomically persisted local state, pulls MT5 pending orders and positions by strategy magic, checks recent history, then only scans for fresh closed-candle signals.",
        ),
        (
            "Signal",
            "Build a pending limit order",
            "A valid LPFS signal becomes a BUY LIMIT or SELL LIMIT at the 50% signal-candle pullback, with broker-side SL, TP, expiration, compact comment, and full signal key stored locally.",
        ),
        (
            "Guard",
            "Check risk, spread, entry freshness",
            "Before order_check, the runner checks duplicate signal keys, entry already touched after the signal, dynamic spread versus setup risk, exposure caps, expiry, and broker-accurate risk sizing.",
        ),
        (
            "Send",
            "Refresh quote before order_send",
            "Immediately before sending, the runner refreshes the quote, reruns the spread gate, and checks for an already matching broker order/position. A matching broker item is adopted; otherwise the order is sent only after broker order_check passes.",
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
            "Keep order unless expired. Spread widening after placement does not cancel the order and has no dedicated Telegram alert yet.",
        ],
        [
            "Pending expired",
            "Every cycle",
            "Cancel the MT5 order when expiry is reached, remove it from active state, and send a cancelled/expired Telegram event.",
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
        ["3", "Missed-entry guard", "If price already touched the planned entry after the signal, no late pending order is placed."],
        ["4", "Spread gate", "Current spread must be no more than 10% of entry-to-stop risk distance."],
        ["5", "Risk sizing", "MT5 order_calc_profit sizes the order, floors to volume_step, caps by broker/local max, and rejects below volume_min."],
        ["6", "Broker validation", "order_check must pass before any live send."],
        ["7", "Final spread gate", "Quote is refreshed and spread is checked again immediately before order_send."],
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

    file_cards = [
        (
            "Live runner",
            "scripts/run_lp_force_strike_live_executor.py",
            "CLI wrapper for cycle count and sleep interval. It does not run as a service by itself.",
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

    html_text = f"""<!doctype html>
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
          ("#live-status", "Status"),
          ("#cycle-model", "Cycle Model"),
          ("#signal-send-path", "Send Path"),
          ("#spread-policy", "Spread Policy"),
          ("#lifecycle-scenarios", "Scenarios"),
          ("#telegram", "Telegram"),
          ("#commands", "Commands"),
          ("#files", "Files"),
      ],
      metadata=metadata,
  )}
  <main>
    <section id="live-status" class="ops-hero" aria-labelledby="live-status-title">
      <div class="eyebrow">Real Account Safety</div>
      <h2 id="live-status-title">Guarded Live-Send Exists</h2>
      <p class="callout warning"><strong>Real orders can be sent.</strong> The live runner must be treated as production-capable when <code>execution_mode</code>, <code>live_send_enabled</code>, account acknowledgement, and MT5 account/server checks pass. Do not run it casually.</p>
      <div class="ops-grid">
        {_fact_grid([
            ("Default risk scale", "0.05x V15", "H4/H8 0.01%, H12/D1 0.015%, W1 0.0375% before broker volume rounding."),
            ("Spread gate", "10% of risk", "Checked before order_check and again immediately before order_send."),
            ("Max open risk", "0.65%", "Strategy exposure cap across active/pending LPFS live-send trades."),
            ("Position caps", "4 same symbol / 17 strategy", "Full V15 stack and concurrent-trade caps remain active."),
            ("Source of truth", "MT5 broker state", "Local JSON state prevents duplicates and allows restart continuity; it does not decide fills or exits."),
            ("Dashboard role", "Static ops guide", "Use state/journal files or the summary script for current account state."),
        ])}
      </div>
    </section>

    <section id="cycle-model" aria-labelledby="cycle-model-title">
      <h2 id="cycle-model-title">How Often It Checks</h2>
      <p>The live runner is cycle-based. One cycle reconciles MT5 first, scans all configured symbols/timeframes for new closed-candle signals, then stops unless the CLI was started with multiple cycles and a sleep interval.</p>
      <div class="scenario-grid">
        {_step_cards(lifecycle_steps)}
      </div>
    </section>

    <section id="signal-send-path" aria-labelledby="signal-send-path-title">
      <h2 id="signal-send-path-title">When A New Limit Order Is Sent</h2>
      <p class="callout">The runner sends only after the signal is valid, the entry is still fresh, spread is acceptable, exposure and sizing pass, broker order_check passes, and the final refreshed quote still passes spread.</p>
      {_table(["Step", "Gate", "Meaning"], signal_rows)}
    </section>

    <section id="spread-policy" aria-labelledby="spread-policy-title">
      <h2 id="spread-policy-title">Spread Policy</h2>
      <p class="callout"><strong>Current behavior:</strong> a setup blocked because spread is too wide stays retryable. The runner records one WAITING alert, does not mark the signal processed, and can place the pending order on a future cycle if spread improves while the setup is still valid.</p>
      <p class="callout"><strong>Baseline alignment:</strong> this keeps the live path closer to V15 because V15 assumes the 50% pullback pending idea can live through the fixed 6-bar entry window. The setup is still rejected permanently if entry already touched or the pending window expired.</p>
      <div class="ops-grid">
        {_fact_grid([
            ("Check cadence", "Once per live cycle", "Default sleep is 30 seconds only when the runner is started with cycles greater than one."),
            ("Before placement", "Retryable WAITING", "If spread is above 10% of risk distance, no order is placed yet and the same signal can be checked again."),
            ("Before order_send", "Final quote refresh", "After order_check passes, spread is checked again immediately before live order_send."),
            ("After placement", "No spread cancel", "Once pending, spread widening does not remove the order by default."),
            ("Order removal", "Expiry / fill / broker removal", "The pending order is kept until it fills, reaches expiry and is cancelled, or MT5 shows it was removed/rejected."),
            ("NZDCHF example", "11.5% vs 10.0%", "With the patched policy, this means wait. A future cycle can place the order if spread improves before entry touch or expiry."),
            ("Cycle summary", "setups_blocked", "Spread-only waits are counted separately from real rejected setups in the live cycle audit row."),
        ])}
      </div>
    </section>

    <section id="lifecycle-scenarios" aria-labelledby="lifecycle-scenarios-title">
      <h2 id="lifecycle-scenarios-title">Order And Position Scenarios</h2>
      <p>These checks happen during reconciliation at the start of every cycle.</p>
      {_table(["Scenario", "When checked", "Action"], scenario_rows)}
    </section>

    <section id="telegram" aria-labelledby="telegram-title">
      <h2 id="telegram-title">Telegram Alerts</h2>
      <div class="ops-grid">
        {_fact_grid([
            ("ORDER PLACED", "Standalone card", "Ticket, market, entry/SL/TP, actual/target risk, size, spread, expiry, ref."),
            ("ENTERED", "Reply to order", "Fill time/price, position ID, volume, SL/TP, risk, ref."),
            ("TAKE PROFIT / STOP LOSS", "Reply to order", "Exit price/time, PnL, R, hold time, deal ticket, position ID, ref."),
            ("ORDER ADOPTED / TRADE CLOSED", "Recovery and manual exits", "Adopted broker items are not resent; manual/unknown exits keep real MT5 PnL and R without a false SL label."),
            ("SKIPPED / REJECTED / CANCELLED", "Readable reason", "Human reason, action taken, key metric, and ref. Raw fields remain in JSONL."),
            ("RUNNER STARTED / STOPPED", "Process heartbeat", "Cadence, cycle count, runtime, state-save status, and SGT start/stop time."),
        ])}
      </div>
      <p class="callout">Telegram delivery is best effort. A failed Telegram send must never validate or invalidate a trade. The journal remains the durable audit record.</p>
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
            ("Limit", "No spread auto-cancel", "Spread is a send gate. Once an order is pending, spread widening does not cancel it and does not have a dedicated Telegram alert yet."),
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
