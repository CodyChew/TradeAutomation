"""Manual summaries for LPFS live lifecycle journal events."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .notifications import (
    format_trader_hold_time,
    format_trader_price,
    format_trader_r,
    format_trader_signed_number,
    format_trader_timestamp,
    format_trader_volume,
)


@dataclass(frozen=True)
class LPFSLiveClosedTrade:
    """One closed LPFS trade paired from order, fill, and close journal cards."""

    symbol: str
    timeframe: str
    side: str
    close_kind: str
    position_id: int | None
    deal_ticket: int | None
    entry_price: float | None
    close_price: float | None
    volume: float | None
    close_profit: float | None
    r_result: float | None
    opened_utc: str | None
    closed_utc: str | None
    signal_key: str
    price_digits: int | None = None


def load_live_journal_events(path: str | Path) -> list[dict[str, Any]]:
    """Load LPFS JSONL audit rows."""

    journal_path = Path(path)
    if not journal_path.exists():
        raise FileNotFoundError(f"Live journal not found: {journal_path}")
    events: list[dict[str, Any]] = []
    with journal_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            events.append(dict(json.loads(line)))
    return events


def build_closed_trade_summaries(events: Sequence[dict[str, Any]]) -> list[LPFSLiveClosedTrade]:
    """Pair order/adoption, position_opened, and close notification_event rows."""

    orders_by_ticket: dict[int, dict[str, Any]] = {}
    positions_by_id: dict[int, dict[str, Any]] = {}
    trades: list[LPFSLiveClosedTrade] = []

    for row in events:
        event = _notification_event(row)
        if event is None:
            continue
        fields = dict(event.get("fields", {}) or {})
        kind = str(event.get("kind", "") or "")
        if kind in {"order_sent", "order_adopted"}:
            ticket = _safe_int(fields.get("order_ticket"))
            if ticket is not None:
                orders_by_ticket[ticket] = event
            continue
        if kind == "position_opened":
            position_id = _safe_int(fields.get("position_id"))
            if position_id is not None:
                positions_by_id[position_id] = event
            continue
        if kind not in {"take_profit_hit", "stop_loss_hit", "position_closed"}:
            continue

        position_id = _safe_int(fields.get("position_id"))
        opened = positions_by_id.get(position_id or -1, {})
        opened_fields = dict(opened.get("fields", {}) or {})
        order = orders_by_ticket.get(_safe_int(opened_fields.get("order_ticket")) or -1, {})
        order_fields = dict(order.get("fields", {}) or {})

        symbol = str(event.get("symbol") or opened.get("symbol") or order.get("symbol") or _signal_part(event, 1) or "")
        timeframe = str(event.get("timeframe") or opened.get("timeframe") or order.get("timeframe") or _signal_part(event, 2) or "")
        side = str(event.get("side") or opened.get("side") or order.get("side") or _signal_part(event, 4) or "")
        price_digits = _first_int(fields.get("price_digits"), opened_fields.get("price_digits"), order_fields.get("price_digits"))

        trades.append(
            LPFSLiveClosedTrade(
                symbol=symbol.upper(),
                timeframe=timeframe.upper(),
                side=side.upper(),
                close_kind={
                    "take_profit_hit": "TAKE PROFIT",
                    "stop_loss_hit": "STOP LOSS",
                    "position_closed": "TRADE CLOSED",
                }[kind],
                position_id=position_id,
                deal_ticket=_safe_int(fields.get("deal_ticket")),
                entry_price=_first_float(fields.get("entry"), opened_fields.get("fill_price"), order_fields.get("entry")),
                close_price=_safe_float(fields.get("close_price")),
                volume=_first_float(fields.get("volume"), opened_fields.get("volume"), order_fields.get("volume")),
                close_profit=_safe_float(fields.get("close_profit")),
                r_result=_safe_float(fields.get("r_result")),
                opened_utc=_first_text(fields.get("opened_utc"), opened_fields.get("opened_utc")),
                closed_utc=_first_text(fields.get("closed_utc")),
                signal_key=str(event.get("signal_key") or opened.get("signal_key") or order.get("signal_key") or ""),
                price_digits=price_digits,
            )
        )

    return sorted(trades, key=lambda trade: _timestamp_sort_key(trade.closed_utc), reverse=True)


def build_recent_trade_summary_message(
    *,
    events: Sequence[dict[str, Any]] | None = None,
    trades: Sequence[LPFSLiveClosedTrade] | None = None,
    limit: int = 5,
    days: int | None = None,
    weeks: int | None = None,
    include_trades: bool = False,
    now_utc: Any = None,
) -> str:
    """Render a compact manual Telegram performance summary."""

    rows = sorted(
        list(trades if trades is not None else build_closed_trade_summaries(events or [])),
        key=lambda trade: _timestamp_sort_key(trade.closed_utc),
        reverse=True,
    )
    recent, period_label = _select_trade_window(rows, limit=limit, days=days, weeks=weeks, now_utc=now_utc)
    if not recent:
        return f"LPFS LIVE | PERFORMANCE SUMMARY\nPeriod: {period_label}\nNo closed trades found in the live journal."

    pnl_values = [float(row.close_profit) for row in recent if row.close_profit is not None]
    r_values = [float(row.r_result) for row in recent if row.r_result is not None]
    wins = sum(1 for row in recent if _trade_result_value(row) > 0)
    losses = sum(1 for row in recent if _trade_result_value(row) < 0)
    flat = len(recent) - wins - losses
    total_pnl = "n/a" if not pnl_values else format_trader_signed_number(sum(pnl_values))
    total_r = "n/a" if not r_values else format_trader_r(sum(r_values))
    avg_r = "n/a" if not r_values else format_trader_r(sum(r_values) / len(r_values))
    best_r = "n/a" if not r_values else format_trader_r(max(r_values))
    worst_r = "n/a" if not r_values else format_trader_r(min(r_values))
    avg_win = _average_text([value for value in r_values if value > 0])
    avg_loss = _average_text([value for value in r_values if value < 0])
    exit_mix = Counter(row.close_kind for row in recent)
    side_mix = Counter(row.side for row in recent if row.side)
    timeframe_mix = Counter(row.timeframe for row in recent if row.timeframe)

    lines = [
        "LPFS LIVE | PERFORMANCE SUMMARY",
        f"Period: {period_label} | Closed trades {len(recent)}",
        f"Closed: {_closed_range_text(recent)}",
        f"Win rate: {_percent_text(wins, len(recent))} | Wins {wins} | Losses {losses} | Flat {flat}",
        f"Net PnL {total_pnl} | Total {total_r} | Avg {avg_r}",
        f"Profit factor: {_profit_factor_text(r_values)} | Best {best_r} | Worst {worst_r}",
        f"Avg win {avg_win} | Avg loss {avg_loss} | Avg hold {_average_hold_text(recent)}",
        (
            f"Exit mix: TP {exit_mix.get('TAKE PROFIT', 0)} | "
            f"SL {exit_mix.get('STOP LOSS', 0)} | Other {exit_mix.get('TRADE CLOSED', 0)}"
        ),
        f"By side: {_counter_text(side_mix, ['LONG', 'SHORT'])}",
        f"By TF: {_counter_text(timeframe_mix, ['H4', 'H8', 'H12', 'D1', 'W1'])}",
    ]

    if not include_trades:
        return "\n".join(lines)

    lines.append("")
    detail_limit = max(0, int(limit))
    detail_rows = recent[:detail_limit] if detail_limit else recent
    for index, trade in enumerate(detail_rows, start=1):
        lines.append(
            f"{index}) {_trade_market(trade)} | {trade.close_kind} | "
            f"{format_trader_r(trade.r_result)} | {format_trader_signed_number(trade.close_profit)}"
        )
        lines.append(
            f"   Entry {format_trader_price(trade.symbol, trade.entry_price, price_digits=trade.price_digits)} -> "
            f"Exit {format_trader_price(trade.symbol, trade.close_price, price_digits=trade.price_digits)} | "
            f"Size {format_trader_volume(trade.volume)}"
        )
        lines.append(
            f"   Hold {format_trader_hold_time(trade.opened_utc, trade.closed_utc)} | "
            f"Closed {format_trader_timestamp(trade.closed_utc)}"
        )

    return "\n".join(lines)


def _select_trade_window(
    rows: Sequence[LPFSLiveClosedTrade],
    *,
    limit: int,
    days: int | None,
    weeks: int | None,
    now_utc: Any,
) -> tuple[list[LPFSLiveClosedTrade], str]:
    if days is not None and weeks is not None:
        raise ValueError("Use either days or weeks, not both.")
    if days is not None:
        if days <= 0:
            raise ValueError("days must be positive.")
        start = _period_start(days=days, now_utc=now_utc)
        return [row for row in rows if _timestamp_sort_key(row.closed_utc) >= start], _plural(days, "day")
    if weeks is not None:
        if weeks <= 0:
            raise ValueError("weeks must be positive.")
        start = _period_start(days=weeks * 7, now_utc=now_utc)
        return [row for row in rows if _timestamp_sort_key(row.closed_utc) >= start], _plural(weeks, "week")

    count = max(0, int(limit))
    if count == 0:
        return list(rows), "All closed trades"
    return list(rows[:count]), f"Latest {_plural(count, 'closed trade')}"


def _period_start(*, days: int, now_utc: Any) -> pd.Timestamp:
    if now_utc is None:
        now = pd.Timestamp.now(tz="UTC")
    else:
        now = _timestamp_sort_key(str(now_utc))
    return now - pd.Timedelta(days=days)


def _plural(count: int, word: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {word}{suffix}"


def _percent_text(part: int, whole: int) -> str:
    if whole <= 0:
        return "n/a"
    return f"{(part / whole) * 100:.1f}%"


def _profit_factor_text(r_values: Sequence[float]) -> str:
    if not r_values:
        return "n/a"
    gross_win = sum(value for value in r_values if value > 0)
    gross_loss = abs(sum(value for value in r_values if value < 0))
    if gross_loss <= 0:
        return "no losses" if gross_win > 0 else "n/a"
    return f"{gross_win / gross_loss:.2f}"


def _average_text(values: Sequence[float]) -> str:
    if not values:
        return "n/a"
    return format_trader_r(sum(values) / len(values))


def _closed_range_text(trades: Sequence[LPFSLiveClosedTrade]) -> str:
    timestamps = [_timestamp_sort_key(row.closed_utc) for row in trades if row.closed_utc not in (None, "")]
    valid_timestamps = [timestamp for timestamp in timestamps if timestamp != pd.Timestamp.min.tz_localize("UTC")]
    if not valid_timestamps:
        return "n/a"
    oldest = min(valid_timestamps).isoformat()
    newest = max(valid_timestamps).isoformat()
    return f"{format_trader_timestamp(oldest)} -> {format_trader_timestamp(newest)}"


def _average_hold_text(trades: Sequence[LPFSLiveClosedTrade]) -> str:
    seconds = [_hold_seconds(row) for row in trades]
    valid_seconds = [value for value in seconds if value is not None]
    if not valid_seconds:
        return "n/a"
    return _duration_text(int(sum(valid_seconds) / len(valid_seconds)))


def _hold_seconds(trade: LPFSLiveClosedTrade) -> int | None:
    opened = _timestamp_sort_key(trade.opened_utc)
    closed = _timestamp_sort_key(trade.closed_utc)
    minimum = pd.Timestamp.min.tz_localize("UTC")
    if opened == minimum or closed == minimum:
        return None
    return int(max(0, (closed - opened).total_seconds()))


def _duration_text(seconds: int) -> str:
    days, remainder = divmod(max(0, int(seconds)), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _counter_text(counter: Counter[str], preferred_order: Sequence[str]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for key in preferred_order:
        if counter.get(key, 0) > 0:
            parts.append(f"{key.title()} {counter[key]}")
            seen.add(key)
    for key, count in sorted(counter.items()):
        if key not in seen and count > 0:
            parts.append(f"{key.title()} {count}")
    return " | ".join(parts) if parts else "n/a"


def _notification_event(row: dict[str, Any]) -> dict[str, Any] | None:
    event = row.get("notification_event")
    return event if isinstance(event, dict) else None


def _trade_market(trade: LPFSLiveClosedTrade) -> str:
    return " ".join(part for part in (trade.symbol, trade.timeframe, trade.side) if part) or "n/a"


def _trade_result_value(trade: LPFSLiveClosedTrade) -> float:
    if trade.r_result is not None:
        return float(trade.r_result)
    if trade.close_profit is not None:
        return float(trade.close_profit)
    return 0.0


def _signal_part(event: dict[str, Any], index: int) -> str:
    parts = str(event.get("signal_key", "") or "").split(":")
    return parts[index] if len(parts) > index and parts[0] == "lpfs" else ""


def _timestamp_sort_key(value: str | None) -> pd.Timestamp:
    try:
        if value in (None, ""):
            return pd.Timestamp.min.tz_localize("UTC")
        timestamp = pd.Timestamp(value)
        return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    except Exception:
        return pd.Timestamp.min.tz_localize("UTC")


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _safe_int(value)
        if parsed is not None:
            return parsed
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
