from __future__ import annotations

import os
import sys
import unittest
import urllib.error
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    MT5AccountSnapshot,
    MT5ExecutionDecision,
    MT5MarketSnapshot,
    MT5SymbolExecutionSpec,
    NotificationEvent,
    TelegramApiError,
    TelegramConfig,
    TelegramNotifier,
    UrllibTelegramHttpClient,
    build_mt5_order_intent,
    format_notification_message,
    notification_from_execution_decision,
)


def _setup(*, entry: float = 1.1000, stop: float = 1.0950, target: float = 1.1050) -> TradeSetup:
    return TradeSetup(
        setup_id="EURUSD_H4_long",
        side="long",
        entry_index=11,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        symbol="EURUSD",
        timeframe="H4",
        signal_index=10,
        metadata={
            "candidate_id": "lp_pivot_3__signal_zone_0p5_pullback__fs_structure__1r",
            "fs_signal_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"),
        },
    )


def _spec() -> MT5SymbolExecutionSpec:
    return MT5SymbolExecutionSpec(
        symbol="EURUSD",
        digits=5,
        point=0.0001,
        trade_tick_value=10.0,
        trade_tick_size=0.0001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_stops_level_points=5,
    )


class FakeTelegramClient:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = {"ok": True, "result": {"message_id": 1}} if response is None else response
        self.error = error
        self.calls: list[tuple[str, dict, float]] = []

    def post_json(self, url: str, payload: dict, *, timeout_seconds: float) -> dict:
        self.calls.append((url, payload, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.response


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class RecordingOpener:
    def __init__(self, payload: bytes | None = None, error: Exception | None = None) -> None:
        self.payload = b'{"ok": true}' if payload is None else payload
        self.error = error
        self.requests = []
        self.timeouts = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


class NotificationTests(unittest.TestCase):
    def test_notification_event_validates_contract_values(self) -> None:
        event = NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal detected")

        self.assertEqual(event.to_dict()["kind"], "signal_detected")
        with self.assertRaisesRegex(ValueError, "Unsupported notification kind"):
            NotificationEvent(kind="bad", mode="DRY_RUN", title="Bad")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Unsupported notification mode"):
            NotificationEvent(kind="signal_detected", mode="BAD", title="Bad")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "Unsupported notification severity"):
            NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Bad", severity="bad")  # type: ignore[arg-type]

    def test_telegram_config_loads_from_env_without_leaking_token(self) -> None:
        config = TelegramConfig.from_env({"TELEGRAM_BOT_TOKEN": "123456:secret", "TELEGRAM_CHAT_ID": "987"}, dry_run=False)

        self.assertEqual(config.bot_token, "123456:secret")
        self.assertFalse(config.dry_run)
        self.assertEqual(config.safe_dict()["bot_token_set"], True)
        self.assertNotIn("secret", str(config.safe_dict()))
        with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"):
            TelegramConfig.from_env({})
        with self.assertRaisesRegex(ValueError, "TELEGRAM_CHAT_ID"):
            TelegramConfig.from_env({"TELEGRAM_BOT_TOKEN": "token"})

        old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        old_chat = os.environ.get("TELEGRAM_CHAT_ID")
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "env-chat"
            self.assertEqual(TelegramConfig.from_env().chat_id, "env-chat")
        finally:
            if old_token is None:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            else:
                os.environ["TELEGRAM_BOT_TOKEN"] = old_token
            if old_chat is None:
                os.environ.pop("TELEGRAM_CHAT_ID", None)
            else:
                os.environ["TELEGRAM_CHAT_ID"] = old_chat

    def test_format_notification_message_handles_optional_fields_and_trimming(self) -> None:
        minimal = format_notification_message(NotificationEvent(kind="executor_error", mode="DRY_RUN", title="Executor error"))
        self.assertIn("[DRY_RUN] Executor error", minimal)
        self.assertNotIn("Market:", minimal)

        event = NotificationEvent(
            kind="order_sent",
            mode="DEMO_LIVE",
            title="Order sent",
            severity="info",
            symbol="EURUSD",
            timeframe="H4",
            side="long",
            status="sent",
            signal_key="lpfs:EURUSD:H4:10:long",
            occurred_at_utc="2026-01-01T00:00:00Z",
            fields={"actual_risk_pct": 0.2, "long_text": "x" * 30},
            message="y" * 30,
        )
        message = format_notification_message(event, max_field_value_length=20)

        self.assertIn("Market: EURUSD H4 long", message)
        self.assertIn("Status: sent", message)
        self.assertIn("Signal: lpfs:EURUSD:H4:10:long", message)
        self.assertIn("Time: 2026-01-01T00:00:00Z", message)
        self.assertIn("Actual Risk Pct: 0.2", message)
        self.assertIn("Long Text: xxxxxxxxxxxxxxxxx...", message)
        self.assertIn("Note: yyyyyyyyyyyyyyyyy...", message)
        with self.assertRaisesRegex(ValueError, "at least 16"):
            format_notification_message(event, max_field_value_length=15)

    def test_notification_from_execution_decision_reports_ready_and_rejected_states(self) -> None:
        ready = build_mt5_order_intent(
            _setup(),
            account=MT5AccountSnapshot(equity=100_000.0),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        ready_event = notification_from_execution_decision(ready, mode="DRY_RUN")

        self.assertEqual(ready_event.kind, "order_intent_created")
        self.assertEqual(ready_event.symbol, "EURUSD")
        self.assertEqual(ready_event.fields["order_type"], "BUY_LIMIT")
        self.assertEqual(ready_event.fields["target_risk_pct"], 0.20)

        rejected_with_checks = build_mt5_order_intent(
            _setup(entry=1.1030, stop=1.0950, target=1.1100),
            account=MT5AccountSnapshot(equity=100_000.0),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        checked_event = notification_from_execution_decision(rejected_with_checks, mode="DRY_RUN")
        self.assertEqual(checked_event.kind, "setup_rejected")
        self.assertEqual(checked_event.status, "entry_not_pending_pullback")
        self.assertEqual(checked_event.fields["checks_completed"], "basic_contract")

        rejected_empty = MT5ExecutionDecision(status="rejected", rejection_reason=None, detail="manual reject")
        empty_event = notification_from_execution_decision(rejected_empty, mode="LIVE")
        self.assertEqual(empty_event.status, "rejected")
        self.assertEqual(empty_event.fields["checks_completed"], "none")
        self.assertEqual(empty_event.message, "manual reject")

    def test_telegram_notifier_dry_run_success_and_failure_paths(self) -> None:
        event = NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal detected")
        dry_notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=True), FakeTelegramClient())
        dry = dry_notifier.send_event(event)

        self.assertEqual(dry.status, "dry_run")
        self.assertFalse(dry.attempted)
        self.assertFalse(dry.sent)
        self.assertEqual(dry.to_dict()["status"], "dry_run")

        client = FakeTelegramClient()
        live = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False, api_base_url="https://example.test", timeout_seconds=3), client)
        sent = live.send_event(event)
        self.assertEqual(sent.status, "sent")
        self.assertTrue(sent.sent)
        self.assertEqual(client.calls[0][0], "https://example.test/bottoken/sendMessage")
        self.assertEqual(client.calls[0][1]["chat_id"], "chat")
        self.assertEqual(client.calls[0][2], 3)

        api_error = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            FakeTelegramClient(error=TelegramApiError("offline")),
        ).send_event(event)
        self.assertEqual(api_error.status, "failed")
        self.assertEqual(api_error.error, "offline")

        not_ok = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            FakeTelegramClient(response={"ok": False, "description": "chat not found"}),
        ).send_event(event)
        self.assertEqual(not_ok.status, "failed")
        self.assertEqual(not_ok.error, "chat not found")

        no_description = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            FakeTelegramClient(response={"ok": False}),
        ).send_event(event)
        self.assertEqual(no_description.error, "Telegram response was not ok.")

    def test_urllib_telegram_client_posts_json_and_validates_response(self) -> None:
        default_client = UrllibTelegramHttpClient()
        self.assertIsNotNone(default_client)

        opener = RecordingOpener()
        client = UrllibTelegramHttpClient(opener=opener)
        response = client.post_json("https://example.test/send", {"text": "hello"}, timeout_seconds=5)

        self.assertEqual(response, {"ok": True})
        self.assertEqual(opener.timeouts, [5])
        request = opener.requests[0]
        self.assertEqual(request.full_url, "https://example.test/send")
        self.assertEqual(request.get_method(), "POST")
        self.assertIn(b'"text": "hello"', request.data)

        with self.assertRaisesRegex(TelegramApiError, "Telegram request failed"):
            UrllibTelegramHttpClient(opener=RecordingOpener(error=urllib.error.URLError("down"))).post_json(
                "https://example.test/send",
                {},
                timeout_seconds=5,
            )
        with self.assertRaisesRegex(TelegramApiError, "Telegram request failed"):
            UrllibTelegramHttpClient(opener=RecordingOpener(payload=b"{bad")).post_json(
                "https://example.test/send",
                {},
                timeout_seconds=5,
            )
        with self.assertRaisesRegex(TelegramApiError, "JSON object"):
            UrllibTelegramHttpClient(opener=RecordingOpener(payload=b"[]")).post_json(
                "https://example.test/send",
                {},
                timeout_seconds=5,
            )


if __name__ == "__main__":
    unittest.main()
