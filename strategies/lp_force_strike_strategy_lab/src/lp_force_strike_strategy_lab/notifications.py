"""Notification contract and Telegram adapter for LP + Force Strike execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
import ssl
from typing import Any, Literal, Protocol
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from .execution_contract import MT5ExecutionDecision


NotificationKind = Literal[
    "signal_detected",
    "setup_rejected",
    "order_intent_created",
    "order_check_passed",
    "order_check_failed",
    "order_sent",
    "order_adopted",
    "order_rejected",
    "pending_expired",
    "pending_cancelled",
    "position_opened",
    "stop_loss_hit",
    "take_profit_hit",
    "position_closed",
    "runner_started",
    "runner_stopped",
    "executor_error",
    "kill_switch_activated",
]
NotificationMode = Literal["DRY_RUN", "DEMO_LIVE", "LIVE"]
NotificationSeverity = Literal["info", "warning", "error"]
DeliveryStatus = Literal["dry_run", "sent", "failed"]

NOTIFICATION_KINDS: tuple[str, ...] = (
    "signal_detected",
    "setup_rejected",
    "order_intent_created",
    "order_check_passed",
    "order_check_failed",
    "order_sent",
    "order_adopted",
    "order_rejected",
    "pending_expired",
    "pending_cancelled",
    "position_opened",
    "stop_loss_hit",
    "take_profit_hit",
    "position_closed",
    "runner_started",
    "runner_stopped",
    "executor_error",
    "kill_switch_activated",
)
NOTIFICATION_MODES: tuple[str, ...] = ("DRY_RUN", "DEMO_LIVE", "LIVE")
NOTIFICATION_SEVERITIES: tuple[str, ...] = ("info", "warning", "error")


@dataclass(frozen=True)
class NotificationEvent:
    """One executor event that can be logged or sent to Telegram."""

    kind: NotificationKind
    mode: NotificationMode
    title: str
    severity: NotificationSeverity = "info"
    symbol: str = ""
    timeframe: str = ""
    side: str = ""
    status: str = ""
    signal_key: str = ""
    message: str = ""
    occurred_at_utc: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in NOTIFICATION_KINDS:
            raise ValueError(f"Unsupported notification kind: {self.kind!r}.")
        if self.mode not in NOTIFICATION_MODES:
            raise ValueError(f"Unsupported notification mode: {self.mode!r}.")
        if self.severity not in NOTIFICATION_SEVERITIES:
            raise ValueError(f"Unsupported notification severity: {self.severity!r}.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration loaded from environment variables."""

    bot_token: str
    chat_id: str
    dry_run: bool = True
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0
    disable_web_page_preview: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, *, dry_run: bool = True) -> "TelegramConfig":
        source = os.environ if env is None else env
        token = str(source.get("TELEGRAM_BOT_TOKEN", "")).strip()
        chat_id = str(source.get("TELEGRAM_CHAT_ID", "")).strip()
        missing = []
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise ValueError(f"Missing Telegram environment variable(s): {', '.join(missing)}.")
        return cls(bot_token=token, chat_id=chat_id, dry_run=dry_run)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "bot_token_set": bool(self.bot_token),
            "chat_id": self.chat_id,
            "dry_run": self.dry_run,
            "api_base_url": self.api_base_url,
            "timeout_seconds": self.timeout_seconds,
            "disable_web_page_preview": self.disable_web_page_preview,
        }


@dataclass(frozen=True)
class NotificationDelivery:
    """Result of attempting to deliver a notification."""

    status: DeliveryStatus
    attempted: bool
    sent: bool
    message: str
    response: dict[str, Any] | None = None
    error: str | None = None
    message_id: int | None = None
    reply_to_message_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelegramApiError(RuntimeError):
    """Raised when the Telegram HTTP adapter cannot return a valid response."""


class TelegramHttpClient(Protocol):
    def post_json(self, url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        """Post a JSON payload and return a decoded JSON object."""


class UrllibTelegramHttpClient:
    """Small stdlib HTTP client for Telegram Bot API calls."""

    def __init__(self, opener: Any | None = None, ssl_context: ssl.SSLContext | None = None) -> None:
        self._opener = opener
        self._ssl_context = ssl_context if ssl_context is not None else _telegram_ssl_context()

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            if self._opener is None:
                response_handle = urllib.request.urlopen(
                    request,
                    timeout=timeout_seconds,
                    context=self._ssl_context,
                )
            else:
                response_handle = self._opener(request, timeout=timeout_seconds)
            with response_handle as response:
                raw = response.read().decode("utf-8")
                decoded = json.loads(raw or "{}")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise TelegramApiError(f"Telegram request failed: {exc}") from exc
        if not isinstance(decoded, dict):
            raise TelegramApiError("Telegram response must be a JSON object.")
        return decoded


def _telegram_ssl_context() -> ssl.SSLContext:
    """Build a deterministic CA context for Telegram HTTPS calls."""

    try:
        import certifi  # type: ignore[import-not-found]
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class TelegramNotifier:
    """Deliver notification events to Telegram or return dry-run payloads."""

    def __init__(self, config: TelegramConfig, http_client: TelegramHttpClient | None = None) -> None:
        self.config = config
        self.http_client = UrllibTelegramHttpClient() if http_client is None else http_client

    def send_message(self, message: str, *, reply_to_message_id: int | None = None) -> NotificationDelivery:
        if self.config.dry_run:
            return NotificationDelivery(
                status="dry_run",
                attempted=False,
                sent=False,
                message=message,
                reply_to_message_id=reply_to_message_id,
            )

        url = f"{self.config.api_base_url.rstrip('/')}/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": message,
            "disable_web_page_preview": self.config.disable_web_page_preview,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = int(reply_to_message_id)
            payload["allow_sending_without_reply"] = True
        try:
            response = self.http_client.post_json(url, payload, timeout_seconds=self.config.timeout_seconds)
        except TelegramApiError as exc:
            if reply_to_message_id is not None:
                return self.send_message(message)
            return NotificationDelivery(
                status="failed",
                attempted=True,
                sent=False,
                message=message,
                error=str(exc),
                reply_to_message_id=reply_to_message_id,
            )
        if not bool(response.get("ok")):
            if reply_to_message_id is not None:
                fallback = self.send_message(message)
                if fallback.sent:
                    return fallback
            error = str(response.get("description") or "Telegram response was not ok.")
            return NotificationDelivery(
                status="failed",
                attempted=True,
                sent=False,
                message=message,
                response=response,
                error=error,
                reply_to_message_id=reply_to_message_id,
            )
        return NotificationDelivery(
            status="sent",
            attempted=True,
            sent=True,
            message=message,
            response=response,
            message_id=_telegram_message_id(response),
            reply_to_message_id=reply_to_message_id,
        )

    def send_event(self, event: NotificationEvent, *, reply_to_message_id: int | None = None) -> NotificationDelivery:
        return self.send_message(format_notification_message(event), reply_to_message_id=reply_to_message_id)


def format_notification_message(event: NotificationEvent, *, max_field_value_length: int = 160) -> str:
    """Render a concise plain-text Telegram message."""

    if max_field_value_length < 16:
        raise ValueError("max_field_value_length must be at least 16.")
    if event.mode == "DRY_RUN":
        return _format_dry_run_message(event, max_field_value_length=max_field_value_length)
    if event.mode == "LIVE" and event.kind in {
        "setup_rejected",
        "order_check_failed",
        "order_sent",
        "order_adopted",
        "order_rejected",
        "pending_expired",
        "pending_cancelled",
        "position_opened",
        "stop_loss_hit",
        "take_profit_hit",
        "position_closed",
        "runner_started",
        "runner_stopped",
        "kill_switch_activated",
    }:
        return _format_live_trade_message(event, max_field_value_length=max_field_value_length)

    lines = [f"[{event.mode}] {event.title}"]
    lines.extend([f"Type: {event.kind}", f"Severity: {event.severity}"])
    context = " ".join(value for value in (event.symbol, event.timeframe, event.side) if value)
    if context:
        lines.append(f"Market: {context}")
    if event.status:
        lines.append(f"Status: {event.status}")
    if event.signal_key:
        lines.append(f"Signal: {event.signal_key}")
    if event.occurred_at_utc:
        lines.append(f"Time: {event.occurred_at_utc}")
    for key in sorted(event.fields):
        lines.append(f"{_label(key)}: {_trim(event.fields[key], max_field_value_length)}")
    if event.message:
        lines.append(f"Note: {_trim(event.message, max_field_value_length)}")
    return "\n".join(lines)


def notification_from_execution_decision(
    decision: MT5ExecutionDecision,
    *,
    mode: NotificationMode,
) -> NotificationEvent:
    """Convert an execution-contract decision into a notification event."""

    if decision.ready and decision.intent is not None:
        intent = decision.intent
        return NotificationEvent(
            kind="order_intent_created",
            mode=mode,
            title="Pending order intent ready",
            severity="info",
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            side=intent.side,
            status="ready",
            signal_key=intent.signal_key,
            fields={
                "order_type": intent.order_type,
                "volume": intent.volume,
                "entry": intent.entry_price,
                "stop_loss": intent.stop_loss,
                "take_profit": intent.take_profit,
                "target_risk_pct": intent.target_risk_pct,
                "actual_risk_pct": intent.actual_risk_pct,
                "expiration_utc": intent.expiration_time_utc.isoformat(),
                "signal_time_utc": None if intent.signal_time_utc is None else intent.signal_time_utc.isoformat(),
                "max_entry_wait_bars": intent.max_entry_wait_bars,
                "strategy_expiry_mode": intent.strategy_expiry_mode,
                "broker_backstop_expiration_utc": (
                    intent.broker_backstop_expiration_time_utc or intent.expiration_time_utc
                ).isoformat(),
            },
        )

    return NotificationEvent(
        kind="setup_rejected",
        mode=mode,
        title="Setup rejected before MT5 send",
        severity="warning",
        status=decision.rejection_reason or "rejected",
        message=decision.detail,
        fields={"checks_completed": ", ".join(decision.checks) if decision.checks else "none"},
    )


def _label(key: str) -> str:
    labels = {
        "entry": "Pending Entry",
        "expiration_utc": "Pending Expiration UTC",
        "order_type": "Pending Order Type",
    }
    return labels.get(str(key), str(key).replace("_", " ").title())


def _format_dry_run_message(event: NotificationEvent, *, max_field_value_length: int) -> str:
    if event.kind == "signal_detected":
        lines = [
            "LPFS DRY RUN - SIGNAL",
            f"Market: {_market_context(event)}",
            "Status: watch only - no order sent, not filled.",
            "Meaning: closed-candle LP + Force Strike setup detected.",
        ]
        _append_trade_levels(lines, event, max_field_value_length=max_field_value_length)
        _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
        return "\n".join(lines)

    if event.kind == "order_intent_created":
        lines = [
            "LPFS DRY RUN - PENDING INTENT",
            f"Market: {_market_context(event)}",
            f"Action: {_field(event, 'order_type', 'pending order')}",
            "Status: pending order idea only - no order sent, not filled.",
        ]
        _append_trade_levels(lines, event, max_field_value_length=max_field_value_length)
        _append_risk_and_size(lines, event, max_field_value_length=max_field_value_length)
        wait_bars = _field(event, "max_entry_wait_bars")
        backstop = _field(event, "broker_backstop_expiration_utc") or _field(event, "expiration_utc")
        if wait_bars:
            lines.append(f"Strategy expiry: after {wait_bars} actual bars")
        if backstop:
            lines.append(f"Broker backstop: {backstop}")
        _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
        return "\n".join(lines)

    if event.kind in {"order_check_passed", "order_check_failed"}:
        passed = event.kind == "order_check_passed"
        lines = [
            "LPFS DRY RUN - BROKER CHECK",
            f"Market: {_market_context(event)}",
            "Result: MT5 would accept this pending request." if passed else "Result: MT5 rejected this pending request.",
            "Status: no order sent, not filled.",
        ]
        retcode = _field(event, "retcode")
        comment = _field(event, "comment")
        if retcode:
            lines.append(f"Retcode: {retcode}")
        if comment:
            lines.append(f"Comment: {comment}")
        _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
        return "\n".join(lines)

    if event.kind == "setup_rejected":
        lines = [
            "LPFS DRY RUN - SETUP SKIPPED",
            f"Reason: {event.status or 'rejected'}",
            "Status: rejected before broker check - no order sent.",
        ]
        if event.message:
            lines.append(f"Detail: {_trim(event.message, max_field_value_length)}")
        checks = _field(event, "checks_completed")
        if checks:
            lines.append(f"Checks: {checks}")
        return "\n".join(lines)

    lines = [
        "LPFS DRY RUN - EVENT",
        f"Type: {event.kind}",
        "Status: no live order action.",
    ]
    if event.message:
        lines.append(f"Note: {_trim(event.message, max_field_value_length)}")
    return "\n".join(lines)


def _format_live_trade_message(event: NotificationEvent, *, max_field_value_length: int) -> str:
    if event.kind in {"runner_started", "runner_stopped"}:
        return _format_runner_card(event, max_field_value_length=max_field_value_length)
    if event.kind in {"order_sent", "order_adopted"}:
        return _format_order_placed_card(event, max_field_value_length=max_field_value_length)
    if event.kind == "position_opened":
        return _format_position_opened_card(event, max_field_value_length=max_field_value_length)
    if event.kind in {"stop_loss_hit", "take_profit_hit", "position_closed"}:
        return _format_position_closed_card(event, max_field_value_length=max_field_value_length)
    return _format_live_exception_card(event, max_field_value_length=max_field_value_length)


def _format_runner_card(event: NotificationEvent, *, max_field_value_length: int) -> str:
    if event.kind == "runner_started":
        lines = [
            "LPFS LIVE | RUNNER STARTED",
            f"Status: {_runner_status_text(event.status or 'running')}",
        ]
        cycles = _field(event, "requested_cycles")
        sleep_seconds = _field(event, "sleep_seconds")
        if cycles or sleep_seconds:
            lines.append(
                f"Cadence: every {_format_seconds(sleep_seconds)} | Cycles {cycles or 'n/a'}"
            )
        if event.occurred_at_utc:
            lines.append(f"Started: {format_trader_timestamp(event.occurred_at_utc)}")
        state_path = _field(event, "state_path")
        journal_path = _field(event, "journal_path")
        if state_path:
            lines.append(f"State: {_trim_path(state_path, max_field_value_length)}")
        if journal_path:
            lines.append(f"Journal: {_trim_path(journal_path, max_field_value_length)}")
        return "\n".join(lines)

    lines = [
        "LPFS LIVE | RUNNER STOPPED",
        f"Reason: {_runner_status_text(event.status or 'completed')}",
    ]
    completed = _field(event, "completed_cycles")
    requested = _field(event, "requested_cycles")
    if completed or requested:
        lines.append(f"Cycles: {completed or '0'} / {requested or 'n/a'}")
    runtime = _field(event, "runtime_seconds")
    if runtime:
        lines.append(f"Runtime: {_format_seconds(runtime)}")
    if event.occurred_at_utc:
        lines.append(f"Stopped: {format_trader_timestamp(event.occurred_at_utc)}")
    state_saved = _field(event, "state_saved")
    if state_saved:
        lines.append(f"State saved: {_yes_no(state_saved)}")
    detail = event.message.strip()
    if detail:
        lines.append(f"Detail: {_trim(detail, max_field_value_length)}")
    return "\n".join(lines)


def _format_order_placed_card(event: NotificationEvent, *, max_field_value_length: int) -> str:
    title = "ORDER ADOPTED" if event.kind == "order_adopted" else "ORDER PLACED"
    lines = [
        f"LPFS LIVE | {title}",
        f"{_market_context(event)} | {_format_order_type(_field(event, 'order_type', 'LIMIT'))} #{_field(event, 'order_ticket', 'n/a')}",
        (
            f"Plan: Entry {_format_event_price(event, 'entry')} | "
            f"SL {_format_event_price(event, 'stop_loss')} | "
            f"TP {_format_event_price(event, 'take_profit')}"
        ),
        (
            f"Risk: {format_trader_percent(_field(event, 'actual_risk_pct'), decimals=4)} actual / "
            f"{format_trader_percent(_field(event, 'target_risk_pct'), decimals=4)} target | "
            f"Size {format_trader_volume(_field(event, 'volume'))} lots"
        ),
    ]
    spread = _field(event, "spread_risk_pct")
    wait_bars = _field(event, "max_entry_wait_bars")
    backstop = _field(event, "broker_backstop_expiration_utc") or _field(event, "expiration_utc")
    if spread or wait_bars or backstop:
        spread_text = "n/a" if not spread else format_trader_percent(spread, decimals=1)
        strategy_text = "n/a" if not wait_bars else f"{wait_bars} bars"
        backstop_text = "n/a" if not backstop else format_trader_timestamp(backstop)
        lines.append(f"Spread: {spread_text} of risk | Strategy {strategy_text} | Backstop {backstop_text}")
    reason = _sentence_case(event.message)
    if reason:
        label = "Recovery" if event.kind == "order_adopted" else "Why"
        lines.append(f"{label}: {_trim(reason, max_field_value_length)}")
    if event.kind == "order_adopted":
        source = _field(event, "adoption_source")
        if source:
            lines.append(f"Source: {_trim(source, max_field_value_length)}")
    _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
    return "\n".join(lines)


def _format_position_opened_card(event: NotificationEvent, *, max_field_value_length: int) -> str:
    position = _field(event, "position_id", "n/a")
    order = _field(event, "order_ticket")
    second_line = f"{_market_context(event)} | Position #{position}"
    if order:
        second_line += f" | Order #{order}"
    lines = [
        "LPFS LIVE | ENTERED",
        second_line,
        f"Fill: {_format_event_price(event, 'fill_price')} | Size {format_trader_volume(_field(event, 'volume'))} lots",
        (
            f"Risk: {format_trader_percent(_field(event, 'actual_risk_pct'), decimals=4)} actual / "
            f"{format_trader_percent(_field(event, 'target_risk_pct'), decimals=4)} target"
        ),
        f"Protection: SL {_format_event_price(event, 'stop_loss')} | TP {_format_event_price(event, 'take_profit')}",
    ]
    opened = _field(event, "opened_utc")
    if opened:
        lines.append(f"Opened: {format_trader_timestamp(opened)}")
    _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
    return "\n".join(lines)


def _format_position_closed_card(event: NotificationEvent, *, max_field_value_length: int) -> str:
    title = {
        "take_profit_hit": "TAKE PROFIT",
        "stop_loss_hit": "STOP LOSS",
        "position_closed": "TRADE CLOSED",
    }.get(event.kind, "TRADE CLOSED")
    position = _field(event, "position_id", "n/a")
    deal = _field(event, "deal_ticket")
    lines = [
        f"LPFS LIVE | {title}",
        f"{_market_context(event)} | Position #{position}",
        (
            f"Exit: {_format_event_price(event, 'close_price')} | "
            f"PnL {format_trader_signed_number(_field(event, 'close_profit'))} | "
            f"R {format_trader_r(_field(event, 'r_result'))}"
        ),
        (
            f"Entry {_format_event_price(event, 'entry')} | "
            f"Size {format_trader_volume(_field(event, 'volume'))} lots"
        ),
    ]
    hold = format_trader_hold_time(_field(event, "opened_utc"), _field(event, "closed_utc"))
    closed = _field(event, "closed_utc")
    if hold != "n/a" or closed:
        closed_text = "n/a" if not closed else format_trader_timestamp(closed)
        lines.append(f"Hold: {hold} | Closed {closed_text}")
    if event.kind == "position_closed":
        reason = _field(event, "close_reason") or event.status or "unknown"
        lines.append(f"Reason: {_trim(str(reason).replace('_', ' ').capitalize(), max_field_value_length)}")
    if deal:
        lines.append(f"Deal: #{deal}")
    _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
    return "\n".join(lines)


def _format_live_exception_card(event: NotificationEvent, *, max_field_value_length: int) -> str:
    title_by_kind = {
        "setup_rejected": "SKIPPED",
        "order_check_failed": "REJECTED",
        "order_rejected": "REJECTED",
        "pending_expired": "CANCELLED",
        "pending_cancelled": "CANCELLED",
        "kill_switch_activated": "KILL SWITCH",
    }
    title = title_by_kind.get(event.kind, "NOTICE")
    if event.kind == "setup_rejected" and event.status in {"spread_too_wide", "spread_too_wide_before_send"}:
        title = "WAITING"
    lines = [
        f"LPFS LIVE | {title}",
        _market_context(event),
        f"Reason: {_human_reason(event)}",
        f"Action: {_human_action(event)}",
    ]
    metric = _human_key_metric(event)
    if metric:
        lines.insert(3, _trim(metric, max_field_value_length))
    _append_signal_id(lines, event, max_field_value_length=max_field_value_length)
    return "\n".join(line for line in lines if line)


def _market_context(event: NotificationEvent) -> str:
    parts = _signal_parts(event.signal_key)
    symbol = event.symbol or parts.get("symbol", "")
    timeframe = event.timeframe or parts.get("timeframe", "")
    side = event.side or parts.get("side", "")
    context = " ".join(value for value in (str(symbol).upper(), str(timeframe).upper(), str(side).upper()) if value)
    return context or "n/a"


def _field(event: NotificationEvent, key: str, default: str = "") -> str:
    value = event.fields.get(key, default)
    return "" if value is None else str(value)


def _append_trade_levels(lines: list[str], event: NotificationEvent, *, max_field_value_length: int) -> None:
    entry = _field(event, "entry")
    stop = _field(event, "stop_loss")
    target = _field(event, "take_profit")
    if entry:
        lines.append(f"Pending Entry: {_trim(entry, max_field_value_length)}")
    if stop:
        lines.append(f"Stop Loss: {_trim(stop, max_field_value_length)}")
    if target:
        lines.append(f"Take Profit: {_trim(target, max_field_value_length)}")


def _append_risk_and_size(lines: list[str], event: NotificationEvent, *, max_field_value_length: int) -> None:
    actual = _field(event, "actual_risk_pct")
    target = _field(event, "target_risk_pct")
    volume = _field(event, "volume")
    if actual and target:
        lines.append(f"Risk: {_trim(actual, max_field_value_length)}% actual / {_trim(target, max_field_value_length)}% target")
    if volume:
        lines.append(f"Volume: {_trim(volume, max_field_value_length)}")


def _append_signal_id(lines: list[str], event: NotificationEvent, *, max_field_value_length: int) -> None:
    if event.signal_key:
        lines.append(f"Ref: {_trim(_signal_reference(event.signal_key), max_field_value_length)}")


def _signal_reference(signal_key: str) -> str:
    parts = str(signal_key).split(":")
    if len(parts) >= 5 and parts[0] == "lpfs":
        return f"{parts[1]}-{parts[2]}-{parts[3]}-{parts[4]}"
    return str(signal_key)


def format_trader_price(symbol: str, value: Any, *, price_digits: Any | None = None) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "n/a"
    digits = _safe_int(price_digits)
    if digits is None:
        raw_symbol = str(symbol or "").upper()
        if raw_symbol.endswith("JPY"):
            digits = 3
        elif raw_symbol.startswith("XAU"):
            digits = 2
        else:
            digits = 5
    digits = max(0, min(int(digits), 8))
    return f"{amount:.{digits}f}"


def format_trader_percent(value: Any, *, decimals: int = 4) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "n/a"
    return f"{amount:.{max(0, int(decimals))}f}%"


def format_trader_volume(value: Any) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "n/a"
    text = f"{amount:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def format_trader_signed_number(value: Any, *, decimals: int = 2) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "n/a"
    return f"{amount:+.{max(0, int(decimals))}f}"


def format_trader_r(value: Any) -> str:
    amount = _safe_float(value)
    if amount is None:
        return "n/a"
    return f"{amount:+.2f}R"


def format_trader_timestamp(value: Any) -> str:
    timestamp = _parse_timestamp(value)
    if timestamp is None:
        return "n/a"
    try:
        display_time = timestamp.astimezone(ZoneInfo("Asia/Singapore"))
    except Exception:
        display_time = timestamp.astimezone(timezone(timedelta(hours=8)))
    return display_time.strftime("%Y-%m-%d %H:%M SGT")


def format_trader_hold_time(opened_utc: Any, closed_utc: Any) -> str:
    opened = _parse_timestamp(opened_utc)
    closed = _parse_timestamp(closed_utc)
    if opened is None or closed is None:
        return "n/a"
    seconds = int(max(0, (closed - opened).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _telegram_message_id(response: dict[str, Any]) -> int | None:
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    return _safe_int(result.get("message_id"))


def _format_event_price(event: NotificationEvent, key: str) -> str:
    return format_trader_price(_market_symbol(event), _field(event, key), price_digits=event.fields.get("price_digits"))


def _market_symbol(event: NotificationEvent) -> str:
    parts = _signal_parts(event.signal_key)
    return str(event.symbol or parts.get("symbol", ""))


def _format_order_type(value: str) -> str:
    return str(value or "LIMIT").replace("_", " ").upper()


def _human_reason(event: NotificationEvent) -> str:
    if event.kind == "order_check_failed":
        return "MT5 order check failed"
    if event.kind == "order_rejected":
        return "Broker rejected the pending order"
    if event.kind == "pending_expired":
        if event.status == "cancel_failed":
            return "Pending order reached strategy expiry, but broker cancellation was not confirmed"
        return "Pending order expired"
    if event.kind == "pending_cancelled":
        if event.status == "history":
            return "Pending order is no longer open in MT5"
        if event.status == "missing":
            return "Pending order disappeared from MT5"
        if event.status == "cancel_failed":
            return "Broker did not confirm pending-order cancellation"
        return "Pending order was cancelled"
    if event.kind == "kill_switch_activated":
        return "Kill switch active"
    status = event.status or event.message or "setup_rejected"
    mapping = {
        "spread_too_wide": "Spread is too wide",
        "spread_too_wide_before_send": "Spread widened before send",
        "entry_already_touched_before_placement": "Entry was already touched before placement",
        "missed_entry_check_unavailable": "Could not verify whether entry was already touched",
        "entry_not_pending_pullback": "Entry is no longer a valid pending pullback",
        "pending_expired": "Pending order expired before placement",
        "rejected": "Setup rejected",
    }
    return mapping.get(str(status), str(status).replace("_", " ").capitalize())


def _human_action(event: NotificationEvent) -> str:
    if event.kind == "setup_rejected" and event.status in {"spread_too_wide", "spread_too_wide_before_send"}:
        return "Will retry on future cycles until entry touch or expiry"
    if event.kind in {"setup_rejected", "order_check_failed", "order_rejected"}:
        return "No order placed"
    if event.kind == "pending_expired":
        if event.status == "cancel_failed":
            return "Order kept in local state for retry on next reconciliation"
        return "Expired pending order cancelled"
    if event.kind == "pending_cancelled":
        if event.status == "cancel_failed":
            return "Order kept in local state for next reconciliation"
        return "Removed from local pending tracking"
    if event.kind == "kill_switch_activated":
        return "No new live cycles will run"
    return "Review journal for details"


def _human_key_metric(event: NotificationEvent) -> str:
    if event.fields.get("first_touch_time_utc"):
        return f"Touched: {format_trader_timestamp(event.fields.get('first_touch_time_utc'))}"
    spread = _safe_float(event.fields.get("spread_risk_fraction"))
    limit = _safe_float(event.fields.get("max_spread_risk_fraction"))
    if spread is not None:
        spread_text = format_trader_percent(spread * 100.0, decimals=1)
        if limit is None:
            return f"Spread: {spread_text} of risk"
        return f"Spread: {spread_text} of risk | Limit {format_trader_percent(limit * 100.0, decimals=1)}"
    order_ticket = event.fields.get("order_ticket")
    if order_ticket not in (None, ""):
        return f"Order: #{order_ticket}"
    return ""


def _runner_status_text(value: str) -> str:
    mapping = {
        "running": "Running",
        "completed": "Completed requested cycles",
        "stopped_by_user": "Stopped by user",
        "error": "Stopped after error",
        "kill_switch": "Kill switch active",
    }
    return mapping.get(str(value or "").strip(), str(value).replace("_", " ").capitalize())


def _format_seconds(value: Any) -> str:
    seconds = _safe_float(value)
    if seconds is None:
        return "n/a"
    seconds = max(0.0, seconds)
    if seconds < 60:
        text = f"{seconds:.1f}".rstrip("0").rstrip(".")
        return f"{text}s"
    minutes, remainder = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if remainder:
        return f"{minutes}m {remainder}s"
    return f"{minutes}m"


def _trim_path(value: str, max_field_value_length: int) -> str:
    text = str(value).replace("\\", "/")
    if len(text) <= max_field_value_length:
        return text
    parts = text.split("/")
    if len(parts) >= 3:
        compact = "/".join(("...", *parts[-2:]))
        if len(compact) <= max_field_value_length:
            return compact
    return _trim(text, max_field_value_length)


def _yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return "yes"
    if text in {"0", "false", "no", "n"}:
        return "no"
    return str(value)


def _sentence_case(value: str) -> str:
    text = str(value).strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _signal_parts(signal_key: str) -> dict[str, str]:
    parts = str(signal_key).split(":")
    if len(parts) >= 5 and parts[0] == "lpfs":
        return {"symbol": parts[1], "timeframe": parts[2], "index": parts[3], "side": parts[4]}
    return {}


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


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _trim(value: Any, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
