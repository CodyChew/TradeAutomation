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
) -> str:
    """Render a compact manual Telegram summary."""

    rows = list(trades if trades is not None else build_closed_trade_summaries(events or []))
    recent = rows[: max(0, int(limit))]
    if not recent:
        return "LPFS LIVE | RECENT TRADE SUMMARY\nNo closed trades found in the live journal."

    pnl_values = [float(row.close_profit) for row in recent if row.close_profit is not None]
    r_values = [float(row.r_result) for row in recent if row.r_result is not None]
    wins = sum(1 for row in recent if _trade_result_value(row) > 0)
    losses = sum(1 for row in recent if _trade_result_value(row) < 0)
    total_pnl = "n/a" if not pnl_values else format_trader_signed_number(sum(pnl_values))
    avg_r = "n/a" if not r_values else format_trader_r(sum(r_values) / len(r_values))
    exit_mix = Counter(row.close_kind for row in recent)

    lines = [
        "LPFS LIVE | RECENT TRADE SUMMARY",
        f"Trades: {len(recent)} | Wins {wins} | Losses {losses}",
        f"Net PnL {total_pnl} | Avg {avg_r}",
        (
            f"Exit mix: TP {exit_mix.get('TAKE PROFIT', 0)} | "
            f"SL {exit_mix.get('STOP LOSS', 0)} | Other {exit_mix.get('TRADE CLOSED', 0)}"
        ),
        "",
    ]

    for index, trade in enumerate(recent, start=1):
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
