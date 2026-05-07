"""Gate-attribution summaries for LPFS live JSONL journals."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd


RETRYABLE_WAIT_STATUSES = {
    "spread_too_wide",
    "spread_too_wide_before_send",
    "market_recovery_not_better",
    "market_recovery_spread_too_wide",
    "autotrading_disabled",
    "market_closed",
}
ENTRY_TOUCH_STATUSES = {
    "entry_already_touched_before_placement",
    "market_recovery_stop_touched",
    "market_recovery_target_touched",
}
EXPIRY_STATUSES = {"pending_expired"}
PLACEMENT_EVENTS = {"order_sent", "market_recovery_sent"}


@dataclass(frozen=True)
class LPFSGateSignalSummary:
    """Attribution for one live signal key."""

    signal_key: str
    symbol: str
    timeframe: str
    side: str
    first_seen_utc: str
    last_seen_utc: str
    event_counts: dict[str, int]
    statuses: dict[str, int]
    spread_waits: int = 0
    final_spread_waits: int = 0
    market_recovery_price_waits: int = 0
    market_recovery_spread_waits: int = 0
    broker_session_waits: int = 0
    entry_touch_skips: int = 0
    expiries: int = 0
    placements: int = 0
    market_recoveries: int = 0
    adopted: int = 0
    later_placement_after_spread_wait: bool = False
    weekly_open_waits: int = 0


@dataclass(frozen=True)
class LPFSGateAttributionReport:
    """Aggregate live gate attribution for one journal source."""

    source: str
    event_count: int
    first_event_utc: str
    last_event_utc: str
    unique_signals: int
    event_counts: dict[str, int]
    status_counts: dict[str, int]
    by_symbol_timeframe: dict[tuple[str, str], int]
    by_timeframe: dict[str, int]
    signals: tuple[LPFSGateSignalSummary, ...]
    weekly_open_window_hours: int

    @property
    def detected_setups(self) -> int:
        return self.unique_signals

    @property
    def placed_orders(self) -> int:
        return sum(signal.placements for signal in self.signals)

    @property
    def market_recoveries(self) -> int:
        return sum(signal.market_recoveries for signal in self.signals)

    @property
    def adopted_orders(self) -> int:
        return sum(signal.adopted for signal in self.signals)

    @property
    def spread_waits(self) -> int:
        return sum(signal.spread_waits + signal.final_spread_waits for signal in self.signals)

    @property
    def market_recovery_price_waits(self) -> int:
        return sum(signal.market_recovery_price_waits for signal in self.signals)

    @property
    def market_recovery_spread_waits(self) -> int:
        return sum(signal.market_recovery_spread_waits for signal in self.signals)

    @property
    def broker_session_waits(self) -> int:
        return sum(signal.broker_session_waits for signal in self.signals)

    @property
    def entry_touch_skips(self) -> int:
        return sum(signal.entry_touch_skips for signal in self.signals)

    @property
    def expiries(self) -> int:
        return sum(signal.expiries for signal in self.signals)

    @property
    def later_placements_after_spread_wait(self) -> int:
        return sum(1 for signal in self.signals if signal.later_placement_after_spread_wait)

    @property
    def weekly_open_waits(self) -> int:
        return sum(signal.weekly_open_waits for signal in self.signals)


def load_jsonl_events(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL rows while skipping blank lines."""

    source_path = Path(path)
    if not source_path.exists():
        raise FileNotFoundError(f"Journal not found: {source_path}")
    with source_path.open("r", encoding="utf-8") as handle:
        return parse_jsonl_lines(handle)


def parse_jsonl_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse JSONL rows from an iterable of strings."""

    rows: list[dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        rows.append(dict(json.loads(line)))
    return rows


def build_gate_attribution_report(
    events: Sequence[dict[str, Any]],
    *,
    source: str = "LPFS live journal",
    weekly_open_window_hours: int = 12,
) -> LPFSGateAttributionReport:
    """Aggregate live journal gate behavior by signal key."""

    event_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    by_signal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    timestamps: list[pd.Timestamp] = []

    for row in events:
        event_name = str(row.get("event") or "")
        if event_name:
            event_counts[event_name] += 1
        timestamp = _row_timestamp(row)
        if timestamp is not None:
            timestamps.append(timestamp)
        status = _row_status(row)
        if status:
            status_counts[status] += 1
        signal_key = _row_signal_key(row)
        if _is_decision_signal_row(row, signal_key):
            by_signal[signal_key].append(row)

    signals = tuple(
        sorted(
            (
                _build_signal_summary(
                    signal_key,
                    rows,
                    weekly_open_window_hours=weekly_open_window_hours,
                )
                for signal_key, rows in by_signal.items()
            ),
            key=lambda item: (_timestamp_or_min(item.first_seen_utc), item.symbol, item.timeframe, item.signal_key),
        )
    )
    by_symbol_timeframe = Counter((signal.symbol, signal.timeframe) for signal in signals)
    by_timeframe = Counter(signal.timeframe for signal in signals)
    first = min(timestamps).isoformat() if timestamps else ""
    last = max(timestamps).isoformat() if timestamps else ""
    return LPFSGateAttributionReport(
        source=source,
        event_count=len(events),
        first_event_utc=first,
        last_event_utc=last,
        unique_signals=len(signals),
        event_counts=dict(sorted(event_counts.items())),
        status_counts=dict(sorted(status_counts.items())),
        by_symbol_timeframe=dict(sorted(by_symbol_timeframe.items())),
        by_timeframe=dict(sorted(by_timeframe.items())),
        signals=signals,
        weekly_open_window_hours=weekly_open_window_hours,
    )


def render_gate_attribution_markdown(
    reports: Sequence[LPFSGateAttributionReport],
    *,
    generated_at_utc: str | None = None,
    detail_limit: int = 20,
) -> str:
    """Render one or more gate-attribution reports as Markdown."""

    generated = generated_at_utc or pd.Timestamp.now(tz="UTC").isoformat()
    lines = [
        "# LPFS Live Gate Attribution",
        "",
        f"Generated: {generated}",
        "",
        "This report is read-only. It summarizes JSONL journal evidence and does not touch MT5, state, or Telegram.",
        "High-volume `market_snapshot` rows are usually omitted by the CLI because they are quote telemetry, not gate decisions.",
        "",
    ]
    for report in reports:
        lines.extend(_render_single_report(report, detail_limit=detail_limit))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_single_report(report: LPFSGateAttributionReport, *, detail_limit: int) -> list[str]:
    lines = [
        f"## {report.source}",
        "",
        f"- Event rows: `{report.event_count}`",
        f"- Window UTC: `{report.first_event_utc or 'n/a'}` to `{report.last_event_utc or 'n/a'}`",
        f"- Unique decision signal keys: `{report.detected_setups}`",
        f"- New placements: `{report.placed_orders}` pending/market orders; market recoveries: `{report.market_recoveries}`; adoptions: `{report.adopted_orders}`",
        f"- Spread waits: `{report.spread_waits}`; later placements after spread wait: `{report.later_placements_after_spread_wait}`",
        f"- Market-recovery waits: price `{report.market_recovery_price_waits}`, spread `{report.market_recovery_spread_waits}`",
        f"- Broker-session waits: `{report.broker_session_waits}`",
        f"- Entry-touch/path skips: `{report.entry_touch_skips}`; expiries: `{report.expiries}`",
        f"- Retryable waits inside weekly-open window: `{report.weekly_open_waits}` using `{report.weekly_open_window_hours}` hours after Sunday 21:00 UTC",
        "",
        "### Event Mix",
        "",
        _counter_table(report.event_counts, ("event", "count")),
        "",
        "### Gate Status Mix",
        "",
        _counter_table(report.status_counts, ("status", "count")),
        "",
        "### Signal Distribution",
        "",
        _distribution_table(report),
        "",
        "### Notable Signals",
        "",
        _signal_table(report.signals, limit=detail_limit),
    ]
    return lines


def _build_signal_summary(
    signal_key: str,
    rows: Sequence[dict[str, Any]],
    *,
    weekly_open_window_hours: int,
) -> LPFSGateSignalSummary:
    event_counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    timestamps: list[pd.Timestamp] = []
    spread_wait_times: list[pd.Timestamp] = []
    placement_times: list[pd.Timestamp] = []
    weekly_open_waits = 0

    for row in rows:
        event_name = str(row.get("event") or "")
        if event_name:
            event_counts[event_name] += 1
        status = _row_status(row)
        if status:
            statuses[status] += 1
        timestamp = _row_timestamp(row)
        if timestamp is not None:
            timestamps.append(timestamp)
        if status in {"spread_too_wide", "spread_too_wide_before_send"}:
            if timestamp is not None:
                spread_wait_times.append(timestamp)
            if _is_weekly_open_window(timestamp, hours=weekly_open_window_hours):
                weekly_open_waits += 1
        if status in {"market_recovery_not_better", "market_recovery_spread_too_wide"}:
            if _is_weekly_open_window(timestamp, hours=weekly_open_window_hours):
                weekly_open_waits += 1
        if status == "market_closed":
            if _is_weekly_open_window(timestamp, hours=weekly_open_window_hours):
                weekly_open_waits += 1
        if event_name in PLACEMENT_EVENTS:
            if timestamp is not None:
                placement_times.append(timestamp)

    first = min(timestamps).isoformat() if timestamps else ""
    last = max(timestamps).isoformat() if timestamps else ""
    return LPFSGateSignalSummary(
        signal_key=signal_key,
        symbol=_signal_part(signal_key, 1).upper(),
        timeframe=_signal_part(signal_key, 2).upper(),
        side=_signal_part(signal_key, 4).upper(),
        first_seen_utc=first,
        last_seen_utc=last,
        event_counts=dict(sorted(event_counts.items())),
        statuses=dict(sorted(statuses.items())),
        spread_waits=statuses.get("spread_too_wide", 0),
        final_spread_waits=statuses.get("spread_too_wide_before_send", 0),
        market_recovery_price_waits=statuses.get("market_recovery_not_better", 0),
        market_recovery_spread_waits=statuses.get("market_recovery_spread_too_wide", 0),
        broker_session_waits=statuses.get("market_closed", 0),
        entry_touch_skips=sum(statuses.get(status, 0) for status in ENTRY_TOUCH_STATUSES),
        expiries=event_counts.get("pending_expired", 0) + statuses.get("pending_expired", 0),
        placements=event_counts.get("order_sent", 0) + event_counts.get("market_recovery_sent", 0),
        market_recoveries=event_counts.get("market_recovery_sent", 0),
        adopted=event_counts.get("order_adopted", 0),
        later_placement_after_spread_wait=_has_later_placement(spread_wait_times, placement_times),
        weekly_open_waits=weekly_open_waits,
    )


def _row_signal_key(row: dict[str, Any]) -> str:
    direct = str(row.get("signal_key") or "")
    if direct:
        return direct
    notification = row.get("notification_event")
    if isinstance(notification, dict):
        nested = str(notification.get("signal_key") or "")
        if nested:
            return nested
    decision = row.get("decision")
    if isinstance(decision, dict):
        intent = decision.get("intent")
        if isinstance(intent, dict):
            nested = str(intent.get("signal_key") or "")
            if nested:
                return nested
    skipped = row.get("skipped")
    if isinstance(skipped, dict):
        nested = str(skipped.get("signal_key") or "")
        if nested:
            return nested
    return ""


def _row_status(row: dict[str, Any]) -> str:
    notification = row.get("notification_event")
    if isinstance(notification, dict):
        status = str(notification.get("status") or "")
        if status:
            return status
    decision = row.get("decision")
    if isinstance(decision, dict):
        status = str(decision.get("status") or "")
        rejection = str(decision.get("rejection_reason") or "")
        return rejection or status
    skipped = row.get("skipped")
    if isinstance(skipped, dict):
        return str(skipped.get("skip_reason") or skipped.get("reason") or skipped.get("status") or "")
    return ""


def _row_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    value = row.get("occurred_at_utc")
    if not value:
        notification = row.get("notification_event")
        if isinstance(notification, dict):
            value = notification.get("occurred_at_utc")
    if not value:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _is_decision_signal_row(row: dict[str, Any], signal_key: str) -> bool:
    if not signal_key:
        return False
    event_name = str(row.get("event") or "")
    if event_name == "signal_already_processed":
        return False
    if event_name == "market_snapshot":
        return False
    return event_name in {
        "setup_skipped",
        "setup_rejected",
        "order_intent_created",
        "order_check_failed",
        "order_rejected",
        "order_sent",
        "market_recovery_intent_created",
        "market_recovery_sent",
        "order_adopted",
        "pending_expired",
        "pending_cancelled",
        "position_opened",
        "stop_loss_hit",
        "take_profit_hit",
        "position_closed",
        "active_position_missing_close",
    }


def _has_later_placement(wait_times: Sequence[pd.Timestamp], placement_times: Sequence[pd.Timestamp]) -> bool:
    if not wait_times or not placement_times:
        return False
    first_wait = min(wait_times)
    return any(placement > first_wait for placement in placement_times)


def _is_weekly_open_window(timestamp: pd.Timestamp | None, *, hours: int) -> bool:
    if timestamp is None or hours <= 0:
        return False
    ts = timestamp.tz_convert("UTC")
    days_since_sunday = (ts.weekday() - 6) % 7
    sunday = (ts - pd.Timedelta(days=days_since_sunday)).normalize()
    weekly_open = sunday + pd.Timedelta(hours=21)
    if weekly_open > ts:
        weekly_open -= pd.Timedelta(days=7)
    delta = ts - weekly_open
    return pd.Timedelta(0) <= delta <= pd.Timedelta(hours=hours)


def _counter_table(values: dict[str, int], headers: tuple[str, str]) -> str:
    if not values:
        return "_None._"
    lines = [f"| {headers[0]} | {headers[1]} |", "|---|---:|"]
    for key, value in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{key or 'n/a'}` | {value} |")
    return "\n".join(lines)


def _distribution_table(report: LPFSGateAttributionReport) -> str:
    if not report.by_symbol_timeframe:
        return "_None._"
    lines = ["| symbol | timeframe | signals |", "|---|---|---:|"]
    for (symbol, timeframe), count in sorted(report.by_symbol_timeframe.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{symbol}` | `{timeframe}` | {count} |")
    return "\n".join(lines)


def _signal_table(signals: Sequence[LPFSGateSignalSummary], *, limit: int) -> str:
    interesting = [
        signal
        for signal in signals
        if signal.placements
        or signal.spread_waits
        or signal.final_spread_waits
        or signal.market_recovery_price_waits
        or signal.market_recovery_spread_waits
        or signal.broker_session_waits
        or signal.entry_touch_skips
        or signal.expiries
        or signal.adopted
    ]
    if not interesting:
        return "_No decision-bearing signal rows._"
    rows = sorted(
        interesting,
        key=lambda signal: (
            -(
                signal.placements
                + signal.adopted
                + signal.spread_waits
                + signal.market_recovery_price_waits
                + signal.market_recovery_spread_waits
                + signal.broker_session_waits
            ),
            signal.symbol,
            signal.timeframe,
            signal.first_seen_utc,
        ),
    )
    if limit > 0:
        rows = rows[:limit]
    lines = [
        "| signal | first seen UTC | placements | waits | recovery waits | broker waits | skips/expiries | notes |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for signal in rows:
        waits = signal.spread_waits + signal.final_spread_waits
        recovery_waits = signal.market_recovery_price_waits + signal.market_recovery_spread_waits
        skips = signal.entry_touch_skips + signal.expiries
        notes = []
        if signal.later_placement_after_spread_wait:
            notes.append("later placement after spread wait")
        if signal.weekly_open_waits:
            notes.append(f"{signal.weekly_open_waits} weekly-open waits")
        if signal.market_recoveries:
            notes.append(f"{signal.market_recoveries} market recovery")
        if signal.adopted:
            notes.append(f"{signal.adopted} adopted")
        label = f"{signal.symbol} {signal.timeframe} {signal.side}".strip()
        lines.append(
            f"| `{label}` | `{signal.first_seen_utc}` | {signal.placements} | {waits} | "
            f"{recovery_waits} | {signal.broker_session_waits} | {skips} | {', '.join(notes) or '-'} |"
        )
    return "\n".join(lines)


def _signal_part(signal_key: str, index: int) -> str:
    parts = str(signal_key or "").split(":")
    if 0 <= index < len(parts):
        return parts[index]
    return ""


def _timestamp_or_min(value: str) -> pd.Timestamp:
    if not value:
        return pd.Timestamp.min.tz_localize("UTC")
    return pd.Timestamp(value)
