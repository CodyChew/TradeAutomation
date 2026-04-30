"""Notification contract and Telegram adapter for LP + Force Strike execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any, Literal, Protocol
import urllib.error
import urllib.request

from .execution_contract import MT5ExecutionDecision


NotificationKind = Literal[
    "signal_detected",
    "setup_rejected",
    "order_intent_created",
    "order_check_passed",
    "order_check_failed",
    "order_sent",
    "order_rejected",
    "pending_expired",
    "pending_cancelled",
    "position_opened",
    "stop_loss_hit",
    "take_profit_hit",
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
    "order_rejected",
    "pending_expired",
    "pending_cancelled",
    "position_opened",
    "stop_loss_hit",
    "take_profit_hit",
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelegramApiError(RuntimeError):
    """Raised when the Telegram HTTP adapter cannot return a valid response."""


class TelegramHttpClient(Protocol):
    def post_json(self, url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        """Post a JSON payload and return a decoded JSON object."""


class UrllibTelegramHttpClient:
    """Small stdlib HTTP client for Telegram Bot API calls."""

    def __init__(self, opener: Any | None = None) -> None:
        self._opener = urllib.request.urlopen if opener is None else opener

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                decoded = json.loads(raw or "{}")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise TelegramApiError(f"Telegram request failed: {exc}") from exc
        if not isinstance(decoded, dict):
            raise TelegramApiError("Telegram response must be a JSON object.")
        return decoded


class TelegramNotifier:
    """Deliver notification events to Telegram or return dry-run payloads."""

    def __init__(self, config: TelegramConfig, http_client: TelegramHttpClient | None = None) -> None:
        self.config = config
        self.http_client = UrllibTelegramHttpClient() if http_client is None else http_client

    def send_event(self, event: NotificationEvent) -> NotificationDelivery:
        message = format_notification_message(event)
        if self.config.dry_run:
            return NotificationDelivery(status="dry_run", attempted=False, sent=False, message=message)

        url = f"{self.config.api_base_url.rstrip('/')}/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": message,
            "disable_web_page_preview": self.config.disable_web_page_preview,
        }
        try:
            response = self.http_client.post_json(url, payload, timeout_seconds=self.config.timeout_seconds)
        except TelegramApiError as exc:
            return NotificationDelivery(
                status="failed",
                attempted=True,
                sent=False,
                message=message,
                error=str(exc),
            )
        if not bool(response.get("ok")):
            error = str(response.get("description") or "Telegram response was not ok.")
            return NotificationDelivery(
                status="failed",
                attempted=True,
                sent=False,
                message=message,
                response=response,
                error=error,
            )
        return NotificationDelivery(status="sent", attempted=True, sent=True, message=message, response=response)


def format_notification_message(event: NotificationEvent, *, max_field_value_length: int = 160) -> str:
    """Render a concise plain-text Telegram message."""

    if max_field_value_length < 16:
        raise ValueError("max_field_value_length must be at least 16.")

    lines = [f"[{event.mode}] {event.title}", f"Type: {event.kind}", f"Severity: {event.severity}"]
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
            title="MT5 order intent ready",
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
    return str(key).replace("_", " ").title()


def _trim(value: Any, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
