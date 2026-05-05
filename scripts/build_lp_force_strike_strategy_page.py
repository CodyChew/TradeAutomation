from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    load_dashboard_metadata,
    metric_glossary_html,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "strategy.html"

TITLE = "Current Strategy Guide: V13 Mechanics + V15 Risk Buckets + V22 LP/FS Separation"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _cards(items: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"""
        <article class="rule-card">
          <h3>{_escape(title)}</h3>
          <p>{_escape(body)}</p>
        </article>
        """
        for title, body in items
    )


def _event_cards(items: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"""
        <article class="event-card">
          <span class="event-label">{_escape(kind)}</span>
          <h3>{_escape(title)}</h3>
          <p>{_escape(body)}</p>
        </article>
        """
        for kind, title, body in items
    )


def _table(headers: list[str], rows: list[list[str]], *, class_name: str = "data-table") -> str:
    head = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"""
      <div class="table-scroll">
        <table class="{_escape(class_name)}">
          <thead><tr>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    """


def _research_link(href: str, title: str, body: str) -> str:
    return f"""
    <article class="trail-card">
      <h3>{_escape(title)}</h3>
      <p>{_escape(body)}</p>
      <a class="button" href="{_escape(href)}">Open { _escape(title.split()[0]) }</a>
    </article>
    """


def _diagram_card(title: str, svg: str, caption: str) -> str:
    return f"""
    <figure class="diagram-card">
      <figcaption>{_escape(title)}</figcaption>
      {svg}
      <p>{_escape(caption)}</p>
    </figure>
    """


def _bullish_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 220" role="img" aria-labelledby="bullish-title">
        <title id="bullish-title">Bullish LP break and Force Strike confirmation</title>
        <rect x="0" y="0" width="420" height="220" rx="8" class="svg-bg"/>
        <line x1="32" y1="126" x2="388" y2="126" class="svg-support"/>
        <text x="36" y="118" class="svg-label">Selected LP support</text>
        <line x1="74" y1="80" x2="74" y2="168" class="svg-wick"/>
        <rect x="58" y="94" width="32" height="46" class="svg-candle-down"/>
        <text x="38" y="188" class="svg-label">bar 1: wick break</text>
        <path d="M110 156 C146 132, 170 118, 206 122" class="svg-arrow"/>
        <line x1="230" y1="92" x2="230" y2="146" class="svg-wick"/>
        <rect x="214" y="114" width="32" height="25" class="svg-candle-up"/>
        <line x1="214" y1="126" x2="246" y2="126" class="svg-close"/>
        <text x="200" y="74" class="svg-label">raw FS closes at/above LP</text>
        <text x="242" y="184" class="svg-good">valid through bar 6</text>
        <circle cx="74" cy="168" r="5" class="svg-dot"/>
        <circle cx="230" cy="126" r="5" class="svg-dot"/>
      </svg>
    """


def _bearish_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 220" role="img" aria-labelledby="bearish-title">
        <title id="bearish-title">Bearish LP break and Force Strike confirmation</title>
        <rect x="0" y="0" width="420" height="220" rx="8" class="svg-bg"/>
        <line x1="32" y1="92" x2="388" y2="92" class="svg-resistance"/>
        <text x="36" y="84" class="svg-label">Selected LP resistance</text>
        <line x1="78" y1="54" x2="78" y2="144" class="svg-wick"/>
        <rect x="62" y="78" width="32" height="42" class="svg-candle-up"/>
        <text x="38" y="168" class="svg-label">bar 1: wick break</text>
        <path d="M110 74 C144 96, 174 112, 208 108" class="svg-arrow"/>
        <line x1="232" y1="74" x2="232" y2="144" class="svg-wick"/>
        <rect x="216" y="82" width="32" height="40" class="svg-candle-down"/>
        <line x1="216" y1="92" x2="248" y2="92" class="svg-close"/>
        <text x="198" y="158" class="svg-label">raw FS closes at/below LP</text>
        <text x="244" y="186" class="svg-good">valid through bar 6</text>
        <circle cx="78" cy="54" r="5" class="svg-dot"/>
        <circle cx="232" cy="92" r="5" class="svg-dot"/>
      </svg>
    """


def _entry_risk_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 240" role="img" aria-labelledby="entry-risk-title">
        <title id="entry-risk-title">Backtest entry, stop, and one R target model</title>
        <rect x="0" y="0" width="420" height="240" rx="8" class="svg-bg"/>
        <line x1="48" y1="130" x2="368" y2="130" class="svg-entry"/>
        <line x1="48" y1="176" x2="368" y2="176" class="svg-stop"/>
        <line x1="48" y1="84" x2="368" y2="84" class="svg-target"/>
        <text x="52" y="122" class="svg-label">0.5 signal-candle pullback entry</text>
        <text x="52" y="168" class="svg-bad">FS structure stop</text>
        <text x="52" y="76" class="svg-good">1R target</text>
        <line x1="214" y1="72" x2="214" y2="176" class="svg-wick"/>
        <rect x="198" y="102" width="32" height="44" class="svg-candle-up"/>
        <path d="M246 130 H326" class="svg-arrow"/>
        <text x="240" y="152" class="svg-label">wait up to 6 bars</text>
        <path d="M336 130 V84" class="svg-arrow"/>
        <path d="M360 130 V176" class="svg-arrow"/>
      </svg>
    """


def _expired_window_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 220" role="img" aria-labelledby="expired-title">
        <title id="expired-title">Expired Force Strike window at bar seven</title>
        <rect x="0" y="0" width="420" height="220" rx="8" class="svg-bg"/>
        <line x1="38" y1="126" x2="382" y2="126" class="svg-support"/>
        <text x="42" y="118" class="svg-label">LP support</text>
        <g class="timeline">
          <circle cx="70" cy="162" r="10" class="svg-dot-good"/><text x="65" y="166">1</text>
          <circle cx="116" cy="162" r="10" class="svg-dot-good"/><text x="111" y="166">2</text>
          <circle cx="162" cy="162" r="10" class="svg-dot-good"/><text x="157" y="166">3</text>
          <circle cx="208" cy="162" r="10" class="svg-dot-good"/><text x="203" y="166">4</text>
          <circle cx="254" cy="162" r="10" class="svg-dot-good"/><text x="249" y="166">5</text>
          <circle cx="300" cy="162" r="10" class="svg-dot-good"/><text x="295" y="166">6</text>
          <circle cx="346" cy="162" r="12" class="svg-dot-bad"/><text x="341" y="166">7</text>
        </g>
        <text x="58" y="64" class="svg-label">break candle counts as bar 1</text>
        <text x="272" y="64" class="svg-bad">FS after bar 6 is expired</text>
        <line x1="346" y1="76" x2="346" y2="126" class="svg-wick"/>
        <rect x="330" y="96" width="32" height="34" class="svg-candle-up"/>
        <path d="M328 78 L364 114 M364 78 L328 114" class="svg-x"/>
      </svg>
    """


def _wrong_side_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 220" role="img" aria-labelledby="wrong-side-title">
        <title id="wrong-side-title">Wrong side close invalidation</title>
        <rect x="0" y="0" width="420" height="220" rx="8" class="svg-bg"/>
        <line x1="38" y1="112" x2="382" y2="112" class="svg-support"/>
        <text x="42" y="104" class="svg-label">Selected LP support</text>
        <line x1="92" y1="78" x2="92" y2="158" class="svg-wick"/>
        <rect x="76" y="100" width="32" height="40" class="svg-candle-down"/>
        <text x="58" y="178" class="svg-label">wick break starts setup</text>
        <line x1="248" y1="86" x2="248" y2="156" class="svg-wick"/>
        <rect x="232" y="118" width="32" height="30" class="svg-candle-down"/>
        <line x1="232" y1="142" x2="264" y2="142" class="svg-close-bad"/>
        <text x="214" y="74" class="svg-bad">close remains below LP</text>
        <path d="M274 92 L310 128 M310 92 L274 128" class="svg-x"/>
        <text x="214" y="180" class="svg-bad">wrong-side close invalidates</text>
      </svg>
    """


def _same_bar_svg() -> str:
    return """
      <svg class="strategy-diagram" viewBox="0 0 420 240" role="img" aria-labelledby="same-bar-title">
        <title id="same-bar-title">Same-bar stop and target conflict</title>
        <rect x="0" y="0" width="420" height="240" rx="8" class="svg-bg"/>
        <line x1="48" y1="82" x2="368" y2="82" class="svg-target"/>
        <line x1="48" y1="130" x2="368" y2="130" class="svg-entry"/>
        <line x1="48" y1="178" x2="368" y2="178" class="svg-stop"/>
        <text x="52" y="74" class="svg-good">target touched</text>
        <text x="52" y="122" class="svg-label">entry active</text>
        <text x="52" y="170" class="svg-bad">stop touched</text>
        <line x1="236" y1="64" x2="236" y2="192" class="svg-wick-strong"/>
        <rect x="218" y="112" width="36" height="34" class="svg-candle-up"/>
        <circle cx="236" cy="82" r="5" class="svg-dot-good"/>
        <circle cx="236" cy="178" r="5" class="svg-dot-bad"/>
        <path d="M270 150 H352" class="svg-arrow-bad"/>
        <text x="260" y="208" class="svg-bad">OHLC conflict resolves stop-first</text>
      </svg>
    """


STRATEGY_EXTRA_CSS = """
    .guide-hero {
      border-top: 4px solid var(--accent);
    }
    .guide-kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr));
      gap: 12px;
      margin-top: 16px;
    }
    .guide-kpis .fact strong {
      font-size: 18px;
      line-height: 1.25;
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
    .contract-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
      gap: 10px;
      margin-top: 16px;
    }
    .contract-strip .fact {
      padding: 11px;
    }
    .contract-strip .fact strong {
      font-size: 17px;
      line-height: 1.25;
    }
    .mechanics-flow {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr));
      gap: 12px;
      counter-reset: mechanic-step;
      margin-top: 14px;
    }
    .mechanic-card {
      position: relative;
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 14px 14px 48px;
    }
    .mechanic-card::before {
      counter-increment: mechanic-step;
      content: counter(mechanic-step);
      position: absolute;
      left: 14px;
      top: 14px;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      background: var(--accent);
      color: white;
      font-weight: 700;
      font-size: 12px;
    }
    .mechanic-card h3 {
      margin: 0 0 6px;
    }
    .mechanic-card p {
      margin: 0;
      color: var(--muted);
    }
    .split-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .contract-table th:first-child,
    .contract-table td:first-child {
      min-width: 180px;
    }
    .rule-grid,
    .event-grid,
    .trail-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
      gap: 12px;
      margin: 14px 0 0;
    }
    .rule-card,
    .event-card,
    .trail-card {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .rule-card h3,
    .event-card h3,
    .trail-card h3 {
      margin-top: 0;
    }
    .rule-card p,
    .event-card p,
    .trail-card p {
      margin: 0;
      color: var(--muted);
    }
    .event-label {
      display: inline-block;
      margin-bottom: 8px;
      padding: 3px 7px;
      border: 1px solid #e5c4c4;
      border-radius: 999px;
      background: #fff1f1;
      color: var(--bad);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .diagram-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .diagram-card {
      margin: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-soft);
    }
    .diagram-card figcaption {
      font-weight: 700;
      margin-bottom: 8px;
      color: #34495e;
    }
    .diagram-card p {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .strategy-diagram {
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
    }
    .svg-bg { fill: #ffffff; }
    .svg-support { stroke: #22577a; stroke-width: 3; stroke-dasharray: 7 5; }
    .svg-resistance { stroke: #7a4f22; stroke-width: 3; stroke-dasharray: 7 5; }
    .svg-entry { stroke: #22577a; stroke-width: 3; }
    .svg-stop { stroke: #9f3333; stroke-width: 3; }
    .svg-target { stroke: #256f46; stroke-width: 3; }
    .svg-wick { stroke: #17202a; stroke-width: 3; }
    .svg-wick-strong { stroke: #17202a; stroke-width: 5; }
    .svg-candle-up { fill: #dff2e5; stroke: #256f46; stroke-width: 2; }
    .svg-candle-down { fill: #fde9e9; stroke: #9f3333; stroke-width: 2; }
    .svg-close { stroke: #256f46; stroke-width: 4; }
    .svg-close-bad { stroke: #9f3333; stroke-width: 4; }
    .svg-arrow { fill: none; stroke: #5d6d7e; stroke-width: 3; marker-end: url(#none); }
    .svg-arrow-bad { fill: none; stroke: #9f3333; stroke-width: 3; }
    .svg-dot { fill: #22577a; }
    .svg-dot-good { fill: #edf8f1; stroke: #256f46; stroke-width: 2; }
    .svg-dot-bad { fill: #fff1f1; stroke: #9f3333; stroke-width: 3; }
    .svg-x { stroke: #9f3333; stroke-width: 4; stroke-linecap: round; }
    .svg-label,
    .timeline text {
      fill: #34495e;
      font: 12px Inter, Segoe UI, Arial, sans-serif;
      letter-spacing: 0;
    }
    .svg-good {
      fill: #256f46;
      font: 700 12px Inter, Segoe UI, Arial, sans-serif;
      letter-spacing: 0;
    }
    .svg-bad {
      fill: #9f3333;
      font: 700 12px Inter, Segoe UI, Arial, sans-serif;
      letter-spacing: 0;
    }
    .risk-table th:first-child,
    .risk-table td:first-child {
      min-width: 220px;
    }
    .button {
      display: inline-block;
      margin-top: 12px;
      background: var(--accent);
      color: white;
      text-decoration: none;
      padding: 8px 11px;
      border-radius: 6px;
      font-weight: 700;
    }
    @media (max-width: 760px) {
      .diagram-grid {
        grid-template-columns: 1fr;
      }
      .strategy-diagram {
        min-width: 300px;
      }
    }
"""


def build_strategy_page(output: Path = DEFAULT_OUTPUT) -> Path:
    metadata = load_dashboard_metadata()
    subtitle = (
        "Static guide for the current LP + Force Strike research baseline. "
        "Signal rules and backtest assumptions are tested research behavior; "
        "guarded MT5 live-send behavior is documented separately in Live Ops."
    )

    signal_rules = [
        (
            "LP3 break opens the setup",
            "The current mechanics use LP3 across H4, H8, H12, D1, and W1. A wick through an active LP support or resistance starts the trap window.",
        ),
        (
            "Selected LP level is deterministic",
            "If multiple LP break windows are still valid, bullish chooses the lowest support and bearish chooses the highest resistance. Equal-price ties use the latest break.",
        ),
        (
            "LP pivot before FS mother",
            "The selected LP pivot bar must be before the Force Strike mother bar. LP==mother and LP-inside-FS selections are rejected by default after V22.",
        ),
        (
            "Raw Force Strike confirms the setup",
            "A bullish confirmation must close at or above the selected support. A bearish confirmation must close at or below the selected resistance.",
        ),
        (
            "Fixed 6-bar signal window",
            "The LP break candle is bar 1. Raw Force Strike must confirm by bar 6; a confirmation first appearing on bar 7 is expired.",
        ),
        (
            "Trap windows stay explicit",
            "Overlapping bullish and bearish trap windows are handled independently, so a later opposite-side setup does not silently rewrite the earlier one.",
        ),
    ]
    trade_rules = [
        (
            "Entry",
            "After a valid signal, the simulated entry is a 0.5 signal-candle pullback. The model waits a fixed 6 bars for that pullback.",
        ),
        (
            "Stop and target",
            "The stop uses the full Force Strike structure stop. The target is fixed at 1R from entry to stop distance.",
        ),
        (
            "Invalid trade geometry",
            "The simulator rejects stop equals entry, stop on the wrong side of entry, and any invalid pullback range before measuring results.",
        ),
        (
            "Conservative OHLC conflicts",
            "If entry, stop, and target ambiguity happens inside one candle, same-bar stop-first handling is used. Gap-through outcomes remain OHLC simulation, not tick reconstruction.",
        ),
    ]
    negative_events = [
        ("Expired", "Force Strike after bar 6", "A raw Force Strike close that first appears on bar 7 or later is outside the fixed signal window and is ignored."),
        ("Invalid", "Wrong-side close", "For a bullish setup, a close below the selected LP does not confirm. For a bearish setup, a close above the selected LP does not confirm."),
        ("Rejected", "LP/FS overlap", "The selected LP pivot cannot be the Force Strike mother bar or any bar inside the Force Strike formation."),
        ("Rejected", "Pullback not reached", "A valid signal still produces no trade if the 0.5 pullback entry is not touched inside the fixed 6-bar pullback wait."),
        ("Rejected", "No next candle after signal", "A signal on the final available candle cannot be tested for pullback entry and is rejected."),
        ("Rejected", "Bad stop or pullback geometry", "Stop equals entry, stop on the wrong side, and invalid pullback ranges are rejected before the result set is built."),
        ("Conservative", "Same-bar stop/target conflict", "When one OHLC bar touches both stop and target after entry, the test records the stop first."),
        ("Limit", "Gap-through stop or target", "Gap-through behavior is measured using OHLC candles only. It is not tick reconstruction and should not be treated as final fill logic."),
        ("Invalid", "Missing or zero ATR", "ATR-dependent checks require a valid positive ATR. Missing or zero ATR invalidates those checks."),
        ("Explicit", "Multiple valid LPs", "Bullish active windows choose the lowest support; bearish active windows choose the highest resistance. Equal-price ties use the latest break."),
        ("Explicit", "Overlapping trap windows", "Bullish and bearish trap windows can overlap. They stay explicit and independently handled rather than being merged into one vague state."),
        ("Risk", "Risk-reserved DD can exceed realized DD", "Risk-reserved DD subtracts open reserved risk, so it can be larger than closed-trade realized DD."),
        ("Risk", "High return can fail practical filters", "A high-return row can still be rejected if risk-reserved DD, max reserved open risk, or monthly losses breach practical limits."),
    ]
    contract_facts = [
        ("LP pivot", "LP3 take-all"),
        ("Timeframes", "H4/H8/H12/D1/W1"),
        ("Setup", "LP break + raw Force Strike"),
        ("LP/FS separation", "LP before FS mother"),
        ("Entry", "0.5 signal-candle pullback"),
        ("Stop", "FS structure stop"),
        ("Target", "1R target"),
        ("Signal window", "6 bars from LP break"),
        ("Pending wait", "6 actual closed bars"),
        ("Risk buckets", "V15 0.20 / 0.30 / 0.75"),
        ("Live expiry", "Broker backstop only"),
    ]
    mechanic_steps = [
        (
            "Signal formation",
            "A wick break through the selected LP3 support or resistance opens a trap window. The selected LP pivot must be before the Force Strike mother bar, and raw Force Strike must close back on the correct side of that LP by bar 6.",
        ),
        (
            "Pending entry",
            "After confirmation, the trade waits at the 0.5 signal-candle pullback. The backtest and live contract both treat the wait as bars, not weekend wall-clock time.",
        ),
        (
            "Stop and target",
            "Stop is the full Force Strike structure stop. Target is fixed at 1R from entry-to-stop distance so every result is measured on the same R basis.",
        ),
        (
            "Expiry / cancel",
            "Strategy expiry is after 6 actual closed bars from the signal candle. Broker expiry is only a conservative emergency backstop in MT5 live execution.",
        ),
        (
            "Sizing",
            "V15 risk buckets are H4/H8 0.20%, H12/D1 0.30%, and W1 0.75% for the research row; live default scale can be smaller in local config.",
        ),
    ]
    correctness_rows = [
        ["Wrong-side close", "A bullish setup must close at or above selected support; a bearish setup must close at or below selected resistance."],
        ["LP/FS overlap", "The selected LP pivot must be before the Force Strike mother bar. LP==mother or LP-inside-FS selections are rejected by default."],
        ["Expired signal", "The LP break candle is bar 1. A first Force Strike confirmation on bar 7 is ignored."],
        ["Expired pending", "The pending entry is cancelled only after the configured number of actual closed bars has passed after the signal candle."],
        ["Missed entry", "If price already touched the planned entry before live placement, no late pending order is sent."],
        ["Invalid geometry", "Stop equals entry, stop on the wrong side, and invalid pullback ranges are rejected before result measurement."],
        ["Conservative OHLC", "Same-bar entry/target/stop ambiguity is stop-first. Gap-through stop or target is OHLC simulation, not tick reconstruction."],
        ["Risk practicality", "A high-return row can still fail if risk-reserved DD, max reserved open risk, or monthly loss is too high."],
    ]
    research_live_rows = [
        ["Research reports", "Historical candles, deterministic LPFS signals, simulated pending fills, OHLC stop/target resolution, portfolio risk accounting."],
        ["MT5 live runner", "Closed-candle scan, spread and exposure gates, order_check, real MT5 pending orders, broker reconciliation, Telegram and JSONL audit."],
        ["Fill truth", "Backtest uses OHLC assumptions; live truth comes from MT5 orders, positions, and deal history."],
        ["Pending expiry", "Research is bar-counted; live cancellation is also bar-counted while the runner is online, with a broker time backstop only for runner-down protection."],
        ["Telegram", "Telegram is reporting only. It does not prove a broker order exists or that an exit reason is final."],
    ]

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(TITLE)}</title>
  <style>
    {dashboard_base_css(table_min_width="860px", extra_css=STRATEGY_EXTRA_CSS)}
  </style>
</head>
<body>
  {dashboard_header_html(
      title=TITLE,
      subtitle_html=_escape(subtitle),
      current_page="strategy.html",
      section_links=[
          ("#strategy-contract", "Contract"),
          ("#trade-mechanics", "Mechanics"),
          ("#correctness", "Correctness"),
          ("#risk-model", "Risk Model"),
          ("#visual-reference", "Visuals"),
          ("#research-trail", "Research Trail"),
      ],
      metadata=metadata,
  )}
  <main>
    <section id="strategy-contract" class="guide-hero" aria-labelledby="strategy-contract-title">
      <div class="eyebrow">Current Baseline In One Screen</div>
      <h2 id="strategy-contract-title">Trade Mechanics Contract</h2>
      <p>Use this as the current LPFS decision contract: LP3 on H4/H8/H12/D1/W1, LP break, selected LP pivot before FS mother, raw Force Strike confirmation, 0.5 signal-candle pullback, FS structure stop, 1R target, 6-bar waits, and V15 risk buckets.</p>
      <div class="contract-strip">
        {"".join(f'<div class="fact"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>' for label, value in contract_facts)}
      </div>
    </section>

    <section id="trade-mechanics" aria-labelledby="trade-mechanics-title">
      <h2 id="trade-mechanics-title">Trade Mechanics</h2>
      <p class="callout">The mechanics are ordered as signal formation, pending entry, stop/target, expiry/cancel conditions, then sizing. The pending wait is counted by actual closed bars, so weekend time does not consume the setup window.</p>
      <div class="mechanics-flow">
        {"".join(f'<article class="mechanic-card"><h3>{_escape(title)}</h3><p>{_escape(body)}</p></article>' for title, body in mechanic_steps)}
      </div>
    </section>

    <section id="correctness" aria-labelledby="correctness-title">
      <h2 id="correctness-title">Correctness And Verification</h2>
      <p class="callout warning">This section is the guardrail for implementation work: invalidation rules stay explicit, backtests stay conservative where OHLC data is ambiguous, and research output is not treated as proof of live broker behavior.</p>
      <div class="split-grid">
        <article class="rule-card">
          <h3>What Invalidates A Setup</h3>
          {_table(["Rule", "Contract"], correctness_rows, class_name="data-table contract-table")}
        </article>
        <article class="rule-card">
          <h3>Research vs Live Execution</h3>
          {_table(["Area", "Distinction"], research_live_rows, class_name="data-table contract-table")}
          <a class="button" href="live_ops.html">Open Live Ops</a>
        </article>
      </div>
    </section>

    <section id="risk-model" aria-labelledby="risk-model-title">
      <h2 id="risk-model-title">Risk Model</h2>
      <p class="callout">V15 did not rerun signals. It re-used the V13/V14 baseline trade rows to compare three risk buckets: H4/H8, H12/D1, and W1.</p>
      <div class="table-scroll">
        <table class="data-table risk-table">
          <thead>
            <tr>
              <th>Risk Row</th>
              <th>H4/H8</th>
              <th>H12/D1</th>
              <th>W1</th>
              <th>Return</th>
              <th>Realized DD</th>
              <th>Risk-Reserved DD</th>
              <th>Max Reserved Risk</th>
              <th>Worst Month</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>First account-constraint candidate</td>
              <td>0.20%</td>
              <td>0.30%</td>
              <td>0.75%</td>
              <td>383.17%</td>
              <td>6.57%</td>
              <td>7.89%</td>
              <td>5.75%</td>
              <td>-3.22%</td>
            </tr>
            <tr>
              <td>Higher-return growth contrast</td>
              <td>0.25%</td>
              <td>0.30%</td>
              <td>0.60%</td>
              <td>421.82%</td>
              <td>8.22%</td>
              <td>9.72%</td>
              <td>5.95%</td>
              <td>-4.05%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section id="visual-reference" aria-labelledby="visual-reference-title">
      <h2 id="visual-reference-title">Visual Reference</h2>
      <p class="callout">Diagrams are reference material after the contract, not the primary source of truth. They show the same rules in chart form for faster review.</p>
      <div class="diagram-grid">
        {_diagram_card("Bullish Setup", _bullish_svg(), "Wick breaks selected support, then raw Force Strike must close back at or above that LP by bar 6.")}
        {_diagram_card("Bearish Setup", _bearish_svg(), "Wick breaks selected resistance, then raw Force Strike must close back at or below that LP by bar 6.")}
        {_diagram_card("Entry And Risk Model", _entry_risk_svg(), "The pending entry sits at the 0.5 signal-candle pullback, uses the FS structure stop, and targets 1R.")}
        {_diagram_card("Same-Bar Stop-First Conflict", _same_bar_svg(), "When a candle can be interpreted as touching both target and stop after entry, the backtest records the stop first.")}
        {_diagram_card("Expired Window", _expired_window_svg(), "The break candle is bar 1. A first confirmation on bar 7 is expired.")}
        {_diagram_card("Wrong-Side Close Invalidation", _wrong_side_svg(), "A bullish setup must close back at or above support. Closing below the LP is not a confirmation.")}
      </div>
    </section>

    <section id="negative-events" aria-labelledby="negative-events-title">
      <h2 id="negative-events-title">Invalid / Negative Events</h2>
      <p class="callout warning">These cases are intentionally explicit so a future implementation does not silently convert ambiguous market behavior into favorable results.</p>
      <div class="event-grid">
        {_event_cards(negative_events)}
      </div>
    </section>

    <section id="research-trail" aria-labelledby="research-trail-title">
      <h2 id="research-trail-title">Research Trail</h2>
      <p>The current strategy guide is a compact reading layer over the latest versioned research pages. Use those pages for full tables, report values, and audit detail.</p>
      <div class="trail-grid">
        {_research_link("v13.html", "V13 Mechanics", "Relaxed portfolio selection set the current LP3 take-all mechanics across H4, H8, H12, D1, and W1.")}
        {_research_link("v14.html", "V14 Drawdown", "Risk sizing added realized drawdown versus risk-reserved drawdown accounting and practical exposure checks.")}
        {_research_link("v15.html", "V15 Buckets", "Bucket sensitivity selected the current first account-constraint row and the higher-return growth contrast.")}
        {_research_link("v22.html", "V22 Separation", "Hard LP-before-FS separation was accepted as the current signal-quality baseline after improving PF, win rate, and average R.")}
      </div>
    </section>

    {metric_glossary_html()}
  </main>
  <footer>Generated static guide. Strategy behavior remains in tested Python modules; live MT5 operation is documented in Live Ops and audited through state and journal files.</footer>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LP + Force Strike strategy guide page.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_strategy_page(Path(args.output))
    print(f"strategy_page={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
