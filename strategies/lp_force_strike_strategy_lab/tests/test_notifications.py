from __future__ import annotations

import builtins
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

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
    format_trader_hold_time,
    format_trader_percent,
    format_trader_price,
    format_trader_signed_number,
    format_trader_timestamp,
    format_trader_volume,
    notification_from_execution_decision,
)
import lp_force_strike_strategy_lab.notifications as notification_module  # noqa: E402


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


class SequenceTelegramClient:
    def __init__(self, results: list[dict | Exception]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict, float]] = []

    def post_json(self, url: str, payload: dict, *, timeout_seconds: float) -> dict:
        self.calls.append((url, payload, timeout_seconds))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


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
        minimal = format_notification_message(
            NotificationEvent(kind="executor_error", mode="DRY_RUN", title="Executor error", message="watch the loop")
        )
        self.assertIn("LPFS DRY RUN - EVENT", minimal)
        self.assertIn("Status: no live order action.", minimal)
        self.assertIn("Note: watch the loop", minimal)
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
        live_minimal = format_notification_message(
            NotificationEvent(kind="executor_error", mode="LIVE", title="Executor error")
        )
        self.assertIn("[LIVE] Executor error", live_minimal)
        self.assertNotIn("Market:", live_minimal)
        self.assertNotIn("Status:", live_minimal)
        self.assertNotIn("Signal:", live_minimal)
        self.assertNotIn("Time:", live_minimal)
        self.assertNotIn("Note:", live_minimal)
        with self.assertRaisesRegex(ValueError, "at least 16"):
            format_notification_message(event, max_field_value_length=15)

    def test_dry_run_messages_are_trader_facing_and_explicitly_not_filled(self) -> None:
        signal = format_notification_message(
            NotificationEvent(
                kind="signal_detected",
                mode="DRY_RUN",
                title="Signal",
                symbol="NZDCHF",
                timeframe="H4",
                side="long",
                signal_key="lpfs:NZDCHF:H4:299:long:signal_zone_0p5_pullback__fs_structure__1r:2026-04-30 13:00:00+00:00",
                fields={"entry": 0.46043, "stop_loss": 0.45956, "take_profit": 0.4613},
            ),
            max_field_value_length=40,
        )

        self.assertIn("LPFS DRY RUN - SIGNAL", signal)
        self.assertIn("Market: NZDCHF H4 LONG", signal)
        self.assertIn("Status: watch only - no order sent, not filled.", signal)
        self.assertIn("Pending Entry: 0.46043", signal)
        self.assertIn("Ref: NZDCHF-H4-299-long", signal)

        empty_signal = format_notification_message(
            NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal")
        )
        self.assertIn("Market: n/a", empty_signal)
        self.assertNotIn("Pending Entry:", empty_signal)
        self.assertNotIn("Ref:", empty_signal)

        custom_ref = format_notification_message(
            NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal", signal_key="manual-ref")
        )
        self.assertIn("Ref: manual-ref", custom_ref)

        intent = format_notification_message(
            NotificationEvent(
                kind="order_intent_created",
                mode="DRY_RUN",
                title="Intent",
                symbol="NZDCHF",
                timeframe="H4",
                side="long",
                fields={
                    "order_type": "BUY_LIMIT",
                    "entry": 0.46043,
                    "stop_loss": 0.45956,
                    "take_profit": 0.4613,
                    "actual_risk_pct": 0.1992,
                    "target_risk_pct": 0.2,
                    "volume": 1.62,
                    "expiration_utc": "2026-05-01T17:00:00+00:00",
                    "max_entry_wait_bars": 6,
                    "broker_backstop_expiration_utc": "2026-05-11T17:00:00+00:00",
                },
            )
        )
        self.assertIn("LPFS DRY RUN - PENDING INTENT", intent)
        self.assertIn("Action: BUY_LIMIT", intent)
        self.assertIn("Status: pending order idea only - no order sent, not filled.", intent)
        self.assertIn("Risk: 0.1992% actual / 0.2% target", intent)
        self.assertIn("Strategy expiry: after 6 actual bars", intent)
        self.assertIn("Broker backstop: 2026-05-11T17:00:00+00:00", intent)

        empty_intent = format_notification_message(
            NotificationEvent(kind="order_intent_created", mode="DRY_RUN", title="Intent")
        )
        self.assertIn("Action: pending order", empty_intent)
        self.assertNotIn("Risk:", empty_intent)
        self.assertNotIn("Volume:", empty_intent)
        self.assertNotIn("Strategy expiry:", empty_intent)
        self.assertNotIn("Broker backstop:", empty_intent)

        passed = format_notification_message(
            NotificationEvent(
                kind="order_check_passed",
                mode="DRY_RUN",
                title="Check",
                fields={"retcode": 0, "comment": "Done"},
            )
        )
        self.assertIn("Result: MT5 would accept this pending request.", passed)
        self.assertIn("Status: no order sent, not filled.", passed)
        self.assertIn("Retcode: 0", passed)
        self.assertIn("Comment: Done", passed)

        failed = format_notification_message(
            NotificationEvent(
                kind="order_check_failed",
                mode="DRY_RUN",
                title="Check",
                fields={"retcode": None, "comment": None},
            )
        )
        self.assertIn("Result: MT5 rejected this pending request.", failed)
        self.assertNotIn("Retcode:", failed)
        self.assertNotIn("Comment:", failed)

        generic_without_note = format_notification_message(
            NotificationEvent(kind="executor_error", mode="DRY_RUN", title="Executor error")
        )
        self.assertIn("LPFS DRY RUN - EVENT", generic_without_note)
        self.assertNotIn("Note:", generic_without_note)

        rejected = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="DRY_RUN",
                title="Rejected",
                status="pending_expired",
                message="expired",
                fields={"checks_completed": "expiration"},
            )
        )
        self.assertIn("LPFS DRY RUN - SETUP SKIPPED", rejected)
        self.assertIn("Reason: pending_expired", rejected)
        self.assertIn("Detail: expired", rejected)
        self.assertIn("Checks: expiration", rejected)

        rejected_without_detail = format_notification_message(
            NotificationEvent(kind="setup_rejected", mode="DRY_RUN", title="Rejected")
        )
        self.assertIn("Reason: rejected", rejected_without_detail)
        self.assertNotIn("Detail:", rejected_without_detail)
        self.assertNotIn("Checks:", rejected_without_detail)

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

    def test_live_trade_messages_are_trader_facing(self) -> None:
        started = format_notification_message(
            NotificationEvent(
                kind="runner_started",
                mode="LIVE",
                title="Runner started",
                status="running",
                occurred_at_utc="2026-05-01T07:00:00+00:00",
                fields={
                    "requested_cycles": 100000000,
                    "sleep_seconds": 30,
                    "state_path": "data/live/lpfs_live_state.json",
                    "journal_path": "data/live/lpfs_live_journal.jsonl",
                },
            )
        )
        self.assertIn("LPFS LIVE | RUNNER STARTED", started)
        self.assertIn("Status: Running", started)
        self.assertIn("Sleep after cycle: 30s | Cycles 100000000", started)
        self.assertIn("Started: 2026-05-01 15:00 SGT", started)

        stopped = format_notification_message(
            NotificationEvent(
                kind="runner_stopped",
                mode="LIVE",
                title="Runner stopped",
                status="stopped_by_user",
                occurred_at_utc="2026-05-01T17:00:00+00:00",
                fields={
                    "requested_cycles": 100000000,
                    "completed_cycles": 1200,
                    "runtime_seconds": 36000,
                    "state_saved": True,
                },
            )
        )
        self.assertIn("LPFS LIVE | RUNNER STOPPED", stopped)
        self.assertIn("Reason: Stopped by user", stopped)
        self.assertIn("Cycles: 1200 / 100000000", stopped)
        self.assertIn("Runtime: 10h 0m", stopped)
        self.assertIn("State saved: yes", stopped)

        minimal_started = format_notification_message(
            NotificationEvent(kind="runner_started", mode="LIVE", title="Runner started")
        )
        self.assertIn("LPFS LIVE | RUNNER STARTED", minimal_started)
        self.assertNotIn("Cadence:", minimal_started)
        self.assertNotIn("Started:", minimal_started)
        self.assertNotIn("State:", minimal_started)
        self.assertNotIn("Journal:", minimal_started)

        minimal_stopped = format_notification_message(
            NotificationEvent(kind="runner_stopped", mode="LIVE", title="Runner stopped")
        )
        self.assertIn("Reason: Completed requested cycles", minimal_stopped)
        self.assertNotIn("Cycles:", minimal_stopped)
        self.assertNotIn("Runtime:", minimal_stopped)
        self.assertNotIn("Stopped:", minimal_stopped)
        self.assertNotIn("State saved:", minimal_stopped)

        order = format_notification_message(
            NotificationEvent(
                kind="order_sent",
                mode="LIVE",
                title="Live limit order placed",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                status="pending",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "order_ticket": 9001,
                    "order_type": "BUY_LIMIT",
                    "entry": 1.1,
                    "stop_loss": 1.095,
                    "take_profit": 1.105,
                    "actual_risk_pct": 0.01,
                    "target_risk_pct": 0.01,
                    "volume": 0.02,
                    "spread_risk_pct": 4.0,
                    "signal_closed_time_utc": "2026-01-01T04:00:00+00:00",
                    "placed_time_utc": "2026-01-01T06:36:00+00:00",
                    "placement_lag_seconds": 9360,
                    "max_entry_wait_bars": 6,
                    "broker_backstop_expiration_utc": "2026-01-12T04:00:00+00:00",
                    "comment": "placed",
                },
                message="closed-candle LPFS setup",
            )
        )
        self.assertIn("LPFS LIVE | ORDER PLACED", order)
        self.assertIn("EURUSD H4 LONG | BUY LIMIT #9001", order)
        self.assertIn("Signal: closed 2026-01-01 12:00 SGT | Placed 2026-01-01 14:36 SGT | Lag 2h 36m", order)
        self.assertIn("Plan: Entry 1.10000 | SL 1.09500 | TP 1.10500", order)
        self.assertIn("Risk: 0.0100% actual / 0.0100% target | Size 0.02 lots", order)
        self.assertIn("Spread: 4.0% of risk | Window 6 bars | Broker backstop 2026-01-12 12:00 SGT", order)
        self.assertIn("Why: Closed-candle LPFS setup", order)
        self.assertIn("Ref: EURUSD-H4-10-long", order)
        self.assertNotIn("Retcode:", order)
        self.assertNotIn("Broker:", order)

        timing_variants = [
            ({"placed_time_utc": "2026-01-01T06:36:00+00:00"}, "Signal: Placed 2026-01-01 14:36 SGT"),
            ({"placement_lag_seconds": 60}, "Signal: Lag 1m"),
            ({"signal_closed_time_utc": "2026-01-01T04:00:00+00:00"}, "Signal: closed 2026-01-01 12:00 SGT"),
        ]
        for fields, expected in timing_variants:
            with self.subTest(fields=fields):
                timing_only = format_notification_message(
                    NotificationEvent(kind="order_sent", mode="LIVE", title="Order", fields=fields)
                )
                self.assertIn(expected, timing_only)

        recovery = format_notification_message(
            NotificationEvent(
                kind="market_recovery_sent",
                mode="LIVE",
                title="Market recovery",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "position_id": 9201,
                    "deal_ticket": 9201,
                    "order_type": "BUY",
                    "original_entry": 1.1,
                    "fill_price": 1.0998,
                    "stop_loss": 1.095,
                    "take_profit": 1.1046,
                    "actual_risk_pct": 0.01,
                    "target_risk_pct": 0.01,
                    "volume": 0.02,
                    "spread_risk_pct": 2.1,
                    "max_spread_risk_fraction": 0.1,
                    "first_touch_time_utc": "2026-01-01T04:00:00+00:00",
                    "first_touch_high": 1.1004,
                    "first_touch_low": 1.0996,
                },
            )
        )
        self.assertIn("LPFS LIVE | MARKET RECOVERY", recovery)
        self.assertIn("EURUSD H4 LONG | BUY #9201", recovery)
        self.assertIn("Recovery: Original 1.10000 | Fill 1.09980", recovery)
        self.assertIn("Protection: SL 1.09500 | TP 1.10460", recovery)
        self.assertIn("Spread: 2.1% of risk | Limit 10.0%", recovery)
        self.assertIn("Touched: 2026-01-01 12:00 SGT | H/L 1.10040/1.09960", recovery)
        self.assertIn("Deal: #9201", recovery)

        minimal_recovery = format_notification_message(
            NotificationEvent(
                kind="market_recovery_sent",
                mode="LIVE",
                title="Market recovery",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                fields={
                    "position_id": 9202,
                    "order_type": "BUY",
                    "original_entry": 1.1,
                    "fill_price": 1.0999,
                    "stop_loss": 1.095,
                    "take_profit": 1.1048,
                    "actual_risk_pct": 0.01,
                    "target_risk_pct": 0.01,
                    "volume": 0.02,
                },
            )
        )
        self.assertIn("LPFS LIVE | MARKET RECOVERY", minimal_recovery)
        self.assertNotIn("Spread:", minimal_recovery)
        self.assertNotIn("Touched:", minimal_recovery)
        self.assertNotIn("Deal:", minimal_recovery)

        adopted = format_notification_message(
            NotificationEvent(
                kind="order_adopted",
                mode="LIVE",
                title="Adopted",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "order_ticket": 7777,
                    "order_type": "BUY_LIMIT",
                    "entry": 1.1,
                    "stop_loss": 1.095,
                    "take_profit": 1.105,
                    "actual_risk_pct": 0.01,
                    "target_risk_pct": 0.01,
                    "volume": 0.02,
                    "adoption_source": "pending order",
                },
                message="Existing MT5 pending order matched this LPFS setup; no new order sent.",
            )
        )
        self.assertIn("LPFS LIVE | ORDER ADOPTED", adopted)
        self.assertIn("Recovery: Existing MT5 pending order matched this LPFS setup", adopted)
        self.assertIn("Source: pending order", adopted)
        adopted_without_source = format_notification_message(
            NotificationEvent(kind="order_adopted", mode="LIVE", title="Adopted", message="Existing MT5 order matched.")
        )
        self.assertIn("LPFS LIVE | ORDER ADOPTED", adopted_without_source)
        self.assertNotIn("Source:", adopted_without_source)

        opened = format_notification_message(
            NotificationEvent(
                kind="position_opened",
                mode="LIVE",
                title="Opened",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "position_id": 7001,
                    "order_ticket": 9001,
                    "fill_price": 1.1,
                    "volume": 0.02,
                    "stop_loss": 1.095,
                    "take_profit": 1.105,
                    "actual_risk_pct": 0.01,
                    "target_risk_pct": 0.01,
                    "opened_utc": "2026-01-01T04:30:00+00:00",
                },
            )
        )
        self.assertIn("LPFS LIVE | ENTERED", opened)
        self.assertIn("EURUSD H4 LONG | Position #7001 | Order #9001", opened)
        self.assertIn("Fill: 1.10000 | Size 0.02 lots", opened)
        self.assertIn("Opened: 2026-01-01 12:30 SGT", opened)

        closed = format_notification_message(
            NotificationEvent(
                kind="take_profit_hit",
                mode="LIVE",
                title="TP",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "position_id": 7001,
                    "deal_ticket": 3001,
                    "entry": 1.1,
                    "close_price": 1.105,
                    "volume": 0.02,
                    "close_profit": 10.0,
                    "r_result": 1.0,
                    "opened_utc": "2026-01-01T04:30:00+00:00",
                    "closed_utc": "2026-01-01T08:00:00+00:00",
                },
            )
        )
        self.assertIn("LPFS LIVE | TAKE PROFIT", closed)
        self.assertIn("Exit: 1.10500 | PnL +10.00 | R +1.00R", closed)
        self.assertIn("Hold: 3h 30m | Closed 2026-01-01 16:00 SGT", closed)
        self.assertIn("Deal: #3001", closed)

        manual_closed = format_notification_message(
            NotificationEvent(
                kind="position_closed",
                mode="LIVE",
                title="Closed",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                fields={
                    "position_id": 7001,
                    "deal_ticket": 3002,
                    "entry": 1.1,
                    "close_price": 1.102,
                    "volume": 0.02,
                    "close_profit": 4.0,
                    "r_result": 0.4,
                    "opened_utc": "2026-01-01T04:30:00+00:00",
                    "closed_utc": "2026-01-01T07:00:00+00:00",
                    "close_reason": "manual",
                },
            )
        )
        self.assertIn("LPFS LIVE | TRADE CLOSED", manual_closed)
        self.assertIn("PnL +4.00 | R +0.40R", manual_closed)
        self.assertIn("Reason: Manual", manual_closed)

        cancelled = format_notification_message(
            NotificationEvent(
                kind="pending_cancelled",
                mode="LIVE",
                title="Cancelled",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                fields={"order_ticket": 9001, "retcode": 10009},
            )
        )
        self.assertIn("LPFS LIVE | CANCELLED", cancelled)
        self.assertIn("Order: #9001", cancelled)
        self.assertIn("Action: Removed from local pending tracking", cancelled)

        bare_order = format_notification_message(NotificationEvent(kind="order_sent", mode="LIVE", title="Order"))
        self.assertIn("n/a | LIMIT #n/a", bare_order)
        self.assertIn("Plan: Entry n/a | SL n/a | TP n/a", bare_order)
        self.assertNotIn("Signal:", bare_order)
        self.assertNotIn("Ref:", bare_order)

        bare_opened = format_notification_message(NotificationEvent(kind="position_opened", mode="LIVE", title="Opened"))
        self.assertIn("n/a | Position #n/a", bare_opened)
        self.assertIn("Fill: n/a | Size n/a lots", bare_opened)
        self.assertNotIn("Opened:", bare_opened)

        bare_closed = format_notification_message(NotificationEvent(kind="stop_loss_hit", mode="LIVE", title="SL"))
        self.assertIn("LPFS LIVE | STOP LOSS", bare_closed)
        self.assertIn("Exit: n/a | PnL n/a | R n/a", bare_closed)
        self.assertNotIn("Hold:", bare_closed)
        bare_manual = format_notification_message(NotificationEvent(kind="position_closed", mode="LIVE", title="Closed"))
        self.assertIn("LPFS LIVE | TRADE CLOSED", bare_manual)
        self.assertIn("Reason: Unknown", bare_manual)

        rejected = format_notification_message(NotificationEvent(kind="order_rejected", mode="LIVE", title="Rejected"))
        self.assertIn("LPFS LIVE | REJECTED", rejected)
        self.assertIn("Reason: Broker rejected the pending order", rejected)
        self.assertNotIn("Retcode:", rejected)
        market_rejected = format_notification_message(
            NotificationEvent(
                kind="order_rejected",
                mode="LIVE",
                title="Rejected",
                fields={"execution_type": "market_recovery", "retcode": 123},
            )
        )
        self.assertIn("Reason: Broker rejected the market recovery order", market_rejected)
        self.assertNotIn("Retcode:", market_rejected)

        expired = format_notification_message(
            NotificationEvent(kind="pending_expired", mode="LIVE", title="Expired", fields={"broker_comment": "expired"})
        )
        self.assertIn("LPFS LIVE | CANCELLED", expired)
        self.assertIn("Reason: Pending order expired", expired)
        self.assertNotIn("Broker:", expired)

        skipped = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Skipped",
                status="entry_already_touched_before_placement",
                signal_key="lpfs:AUDJPY:D1:299:short:c:2026-04-30T00:00:00Z",
                fields={
                    "original_entry": 114.3,
                    "first_touch_time_utc": "2026-04-29T21:00:00+00:00",
                    "first_touch_high": 114.321,
                    "first_touch_low": 114.111,
                },
            )
        )
        self.assertIn("LPFS LIVE | SKIPPED", skipped)
        self.assertIn("AUDJPY D1 SHORT", skipped)
        self.assertIn("Reason: Entry was already touched before placement", skipped)
        self.assertIn("Touched: 2026-04-30 05:00 SGT | Entry 114.300 | H/L 114.321/114.111", skipped)
        self.assertIn("Action: No order placed", skipped)

        touch_only = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Skipped",
                status="entry_already_touched_before_placement",
                signal_key="lpfs:AUDJPY:D1:299:short:c:2026-04-30T00:00:00Z",
                fields={"first_touch_time_utc": "2026-04-29T21:00:00+00:00"},
            )
        )
        self.assertIn("Touched: 2026-04-30 05:00 SGT", touch_only)
        self.assertNotIn(" | Entry ", touch_only)
        self.assertNotIn(" | H/L ", touch_only)

        spread_skip = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Skipped",
                status="spread_too_wide",
                signal_key="lpfs:NZDCHF:H4:299:long:c:2026-04-30T13:00:00Z",
                fields={"spread_risk_fraction": 0.1026, "max_spread_risk_fraction": 0.1},
            )
        )
        self.assertIn("LPFS LIVE | WAITING", spread_skip)
        self.assertIn("Spread: 10.3% of risk | Limit 10.0%", spread_skip)
        self.assertIn("Action: Will retry on future cycles until entry touch or expiry", spread_skip)

        recovery_spread_wait = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Recovery spread",
                status="market_recovery_spread_too_wide",
                signal_key="lpfs:NZDUSD:H8:299:short:c:2026-05-01T13:00:00Z",
                fields={"spread_risk_fraction": 0.125, "max_spread_risk_fraction": 0.1},
            )
        )
        self.assertIn("LPFS LIVE | WAITING", recovery_spread_wait)
        self.assertIn("Reason: Market recovery spread is too wide", recovery_spread_wait)
        self.assertIn("Action: Will retry market recovery while price remains better and inside the 6-bar window", recovery_spread_wait)

        market_closed_wait = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Market closed",
                status="market_closed",
                signal_key="lpfs:GBPUSD:D1:299:short:c:2026-05-06T21:00:00Z",
                fields={"retcode": 10018, "comment": "Market closed"},
            )
        )
        self.assertIn("LPFS LIVE | WAITING", market_closed_wait)
        self.assertIn("Reason: Broker market is closed", market_closed_wait)
        self.assertIn("Action: Will retry when broker session reopens while setup remains valid", market_closed_wait)

        recovery_price_wait = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Recovery price",
                status="market_recovery_not_better",
                signal_key="lpfs:CADCHF:H4:299:short:c:2026-05-04T17:00:00Z",
                fields={
                    "original_entry": 0.57567,
                    "fill_price": 0.57540,
                    "first_touch_time_utc": "2026-05-04T13:00:00+00:00",
                    "first_touch_high": 0.57571,
                    "first_touch_low": 0.57465,
                },
            )
        )
        self.assertIn("LPFS LIVE | WAITING", recovery_price_wait)
        self.assertIn("Reason: Current executable price is worse than the original entry", recovery_price_wait)
        self.assertIn("Touched: 2026-05-04 21:00 SGT | Entry 0.57567 | Fill 0.57540", recovery_price_wait)
        self.assertIn("Action: Will retry market recovery until price returns same-or-better", recovery_price_wait)

    def test_trader_formatting_helpers_are_compact_and_sgt_based(self) -> None:
        self.assertEqual(format_trader_price("AUDJPY", 114.31234), "114.312")
        self.assertEqual(format_trader_price("EURUSD", 1.1), "1.10000")
        self.assertEqual(format_trader_price("XAUUSD", 2300.123), "2300.12")
        self.assertEqual(format_trader_price("EURUSD", "bad"), "n/a")
        self.assertEqual(format_trader_price("EURUSD", 1.1, price_digits=2), "1.10")
        self.assertEqual(format_trader_percent(0.015, decimals=4), "0.0150%")
        self.assertEqual(format_trader_percent("bad", decimals=4), "n/a")
        self.assertEqual(format_trader_percent(4.828, decimals=1), "4.8%")
        self.assertEqual(format_trader_volume(0.0500), "0.05")
        self.assertEqual(format_trader_volume(1.0), "1")
        self.assertEqual(format_trader_volume("bad"), "n/a")
        self.assertEqual(format_trader_signed_number(-12.3), "-12.30")
        self.assertEqual(format_trader_signed_number("bad"), "n/a")
        self.assertEqual(notification_module.format_trader_r("bad"), "n/a")
        self.assertEqual(notification_module._format_seconds(None), "n/a")
        self.assertEqual(notification_module._format_seconds(-1), "0s")
        self.assertEqual(notification_module._format_seconds(90), "1m 30s")
        self.assertEqual(notification_module._format_seconds(120), "2m")
        self.assertEqual(notification_module._trim_path("C:/very/long/path/state.json", 20), ".../path/state.json")
        self.assertEqual(notification_module._trim_path("C:/very/long/path/state.json", 10), "C:/very...")
        self.assertEqual(notification_module._trim_path("averyverylongfilenamewithoutslashes", 16), "averyverylong...")
        self.assertEqual(notification_module._yes_no(True), "yes")
        self.assertEqual(notification_module._yes_no(False), "no")
        self.assertEqual(notification_module._yes_no("maybe"), "maybe")
        self.assertEqual(format_trader_timestamp("2026-05-01T14:10:30.123456+00:00"), "2026-05-01 22:10 SGT")
        self.assertEqual(format_trader_timestamp("2026-05-01T14:10:30Z"), "2026-05-01 22:10 SGT")
        self.assertEqual(format_trader_timestamp("2026-05-01T14:10:30"), "2026-05-01 22:10 SGT")
        self.assertEqual(format_trader_timestamp("bad"), "n/a")
        self.assertEqual(
            format_trader_hold_time("2026-05-01T14:10:00+00:00", "2026-05-01T22:25:00+00:00"),
            "8h 15m",
        )
        self.assertEqual(
            format_trader_hold_time("2026-05-01T14:10:00+00:00", "2026-05-03T16:25:00+00:00"),
            "2d 2h",
        )
        self.assertEqual(
            format_trader_hold_time("2026-05-01T14:10:00+00:00", "2026-05-01T14:25:00+00:00"),
            "15m",
        )
        self.assertEqual(format_trader_hold_time("", "2026-05-01T14:25:00+00:00"), "n/a")

        original_zone_info = notification_module.ZoneInfo
        try:
            notification_module.ZoneInfo = lambda name: (_ for _ in ()).throw(RuntimeError("missing zone"))  # type: ignore[assignment]
            self.assertEqual(format_trader_timestamp("2026-05-01T14:10:30+00:00"), "2026-05-01 22:10 SGT")
        finally:
            notification_module.ZoneInfo = original_zone_info  # type: ignore[assignment]

    def test_live_exception_card_reason_fallbacks_are_readable(self) -> None:
        cancel_failed = format_notification_message(
            NotificationEvent(
                kind="pending_cancelled",
                mode="LIVE",
                title="Cancel failed",
                status="cancel_failed",
                fields={"order_ticket": 9001},
            )
        )
        self.assertIn("Reason: Broker did not confirm pending-order cancellation", cancel_failed)
        self.assertIn("Action: Order kept in local state for next reconciliation", cancel_failed)

        expiry_cancel_failed = format_notification_message(
            NotificationEvent(
                kind="pending_expired",
                mode="LIVE",
                title="Expiry cancel failed",
                status="cancel_failed",
                fields={"order_ticket": 9001},
            )
        )
        self.assertIn("Reason: Pending order reached strategy expiry, but broker cancellation was not confirmed", expiry_cancel_failed)
        self.assertIn("Action: Order kept in local state for retry on next reconciliation", expiry_cancel_failed)

        no_limit_spread = format_notification_message(
            NotificationEvent(
                kind="setup_rejected",
                mode="LIVE",
                title="Spread",
                status="spread_too_wide",
                fields={"spread_risk_fraction": 0.051},
            )
        )
        self.assertIn("Spread: 5.1% of risk", no_limit_spread)

        unknown = format_notification_message(
            NotificationEvent(kind="setup_rejected", mode="LIVE", title="Unknown", status="custom_reason")
        )
        self.assertIn("Reason: Custom reason", unknown)

        blank_reason = format_notification_message(
            NotificationEvent(kind="order_sent", mode="LIVE", title="Order", message=" ")
        )
        self.assertNotIn("Why:", blank_reason)

        self.assertEqual(notification_module._telegram_message_id({"ok": True, "result": []}), None)
        self.assertEqual(notification_module._safe_float("bad"), None)
        self.assertEqual(notification_module._safe_int("bad"), None)
        self.assertEqual(
            notification_module._human_action(NotificationEvent(kind="executor_error", mode="LIVE", title="Error")),
            "Review journal for details",
        )

    def test_telegram_notifier_dry_run_success_and_failure_paths(self) -> None:
        event = NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal detected")
        dry_notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=True), FakeTelegramClient())
        dry = dry_notifier.send_event(event, reply_to_message_id=44)

        self.assertEqual(dry.status, "dry_run")
        self.assertFalse(dry.attempted)
        self.assertFalse(dry.sent)
        self.assertEqual(dry.reply_to_message_id, 44)
        self.assertEqual(dry.to_dict()["status"], "dry_run")

        client = FakeTelegramClient()
        live = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False, api_base_url="https://example.test", timeout_seconds=3), client)
        sent = live.send_event(event, reply_to_message_id=77)
        self.assertEqual(sent.status, "sent")
        self.assertTrue(sent.sent)
        self.assertEqual(sent.message_id, 1)
        self.assertEqual(sent.reply_to_message_id, 77)
        self.assertEqual(client.calls[0][0], "https://example.test/bottoken/sendMessage")
        self.assertEqual(client.calls[0][1]["chat_id"], "chat")
        self.assertEqual(client.calls[0][1]["reply_to_message_id"], 77)
        self.assertTrue(client.calls[0][1]["allow_sending_without_reply"])
        self.assertNotIn("parse_mode", client.calls[0][1])
        self.assertEqual(client.calls[0][2], 3)

        no_message_id = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            FakeTelegramClient(response={"ok": True, "result": {}}),
        ).send_event(event)
        self.assertTrue(no_message_id.sent)
        self.assertIsNone(no_message_id.message_id)

        reply_rejected_client = SequenceTelegramClient(
            [
                {"ok": False, "description": "reply message not found"},
                {"ok": True, "result": {"message_id": 88}},
            ]
        )
        reply_rejected = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            reply_rejected_client,
        ).send_event(event, reply_to_message_id=999)
        self.assertTrue(reply_rejected.sent)
        self.assertEqual(reply_rejected.message_id, 88)
        self.assertIsNone(reply_rejected.reply_to_message_id)
        self.assertEqual(reply_rejected_client.calls[0][1]["reply_to_message_id"], 999)
        self.assertNotIn("reply_to_message_id", reply_rejected_client.calls[1][1])

        reply_and_fallback_rejected = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            SequenceTelegramClient(
                [
                    {"ok": False, "description": "reply message not found"},
                    {"ok": False, "description": "chat not found"},
                ]
            ),
        ).send_event(event, reply_to_message_id=997)
        self.assertEqual(reply_and_fallback_rejected.status, "failed")
        self.assertEqual(reply_and_fallback_rejected.error, "reply message not found")
        self.assertEqual(reply_and_fallback_rejected.reply_to_message_id, 997)

        reply_exception_client = SequenceTelegramClient(
            [
                TelegramApiError("reply failed"),
                {"ok": True, "result": {"message_id": 89}},
            ]
        )
        reply_exception = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            reply_exception_client,
        ).send_event(event, reply_to_message_id=998)
        self.assertTrue(reply_exception.sent)
        self.assertEqual(reply_exception.message_id, 89)
        self.assertIsNone(reply_exception.reply_to_message_id)

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

    def test_urllib_telegram_client_uses_ssl_context_for_default_opener(self) -> None:
        calls = []

        def fake_urlopen(request, *, timeout, context):
            calls.append((request, timeout, context))
            return FakeResponse(b'{"ok": true}')

        ssl_context = object()
        with mock.patch.object(notification_module.urllib.request, "urlopen", fake_urlopen):
            response = UrllibTelegramHttpClient(ssl_context=ssl_context).post_json(
                "https://example.test/send",
                {"text": "hello"},
                timeout_seconds=7,
            )

        self.assertEqual(response, {"ok": True})
        self.assertEqual(calls[0][1], 7)
        self.assertIs(calls[0][2], ssl_context)

    def test_telegram_ssl_context_falls_back_without_certifi(self) -> None:
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "certifi":
                raise ImportError("certifi unavailable")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import), mock.patch.object(
            notification_module.ssl,
            "create_default_context",
            return_value="fallback_context",
        ) as create_default_context:
            context = notification_module._telegram_ssl_context()

        self.assertEqual(context, "fallback_context")
        create_default_context.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
