from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    WORKSPACE_ROOT,
    WORKSPACE_ROOT / "scripts",
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import (  # noqa: E402
    LEGACY_HELSINKI_RELOCALIZED_V1,
    MT5_EPOCH_UTC_V2,
    LiveCloseEvent,
    LiveExecutorState,
    LiveOrderSendOutcome,
    LiveSendExecutorConfig,
    LiveTrackedOrder,
    LiveTrackedPosition,
    NotificationEvent,
    TimestampSemanticsError,
    build_closed_trade_summaries,
    canonical_and_legacy_signal_keys,
    load_live_state,
    mt5_epoch_to_utc,
    format_notification_message,
    normalize_recorded_timestamp,
    parse_signal_key,
    reconcile_only_live_state,
    save_live_state,
    validated_broker_snapshot,
)
from lp_force_strike_strategy_lab import live_executor as live_module  # noqa: E402
from lp_force_strike_strategy_lab import timestamp_semantics as semantics_module  # noqa: E402
from scripts.export_lpfs_mt5_evidence import EvidenceExportError, export_evidence  # noqa: E402
from scripts.normalize_lpfs_c01_evidence import C01NormalizationError, normalize_journal, normalize_row  # noqa: E402
from scripts import run_lp_force_strike_live_executor as runner_module  # noqa: E402
from scripts.build_lpfs_live_weekly_performance import live_state_counts  # noqa: E402


CANONICAL_KEY = "lpfs:EURUSD:H4:10:long:candidate:2026-06-01T12:34:56+00:00"
ARCHIVED_BACKSTOP_MODIFY_ROW = {
    "event": "pending_broker_backstop_modify_attempt",
    "modified": False,
    "new_broker_backstop_expiration_utc": "2026-05-12T13:00:00+00:00",
    "occurred_at_utc": "2026-05-03T07:26:53.038672+00:00",
    "old_expiration_utc": "2026-05-02T13:00:00+00:00",
    "order_ticket": 257048012,
    "symbol": "EURNZD",
    "timeframe": "H8",
}
ARCHIVED_ORDER_SENT_ROW = {
    "event": "order_sent",
    "event_key": "order_sent:263759666",
    "notification_event": {
        "fields": {
            "broker_backstop_expiration_utc": "2026-06-09T05:00:00+00:00",
            "expiration_utc": "2026-06-09T05:00:00+00:00",
            "placed_time_utc": "2026-05-28T05:01:12.800577+00:00",
            "signal_closed_time_utc": "2026-05-28T05:00:00+00:00",
            "signal_time_utc": "2026-05-27T21:00:00+00:00",
        },
    },
    "occurred_at_utc": "2026-05-28T05:01:13.503664+00:00",
}
ARCHIVED_SPACE_EVENT_KEY_ROW = {
    "event": "setup_rejected",
    "event_key": (
        "setup_rejected:lpfs:AUDJPY:D1:299:short:"
        "signal_zone_0p5_pullback__fs_structure__1r:2026-04-28 21:00:00+00:00:missed_entry"
    ),
    "notification_event": {
        "fields": {"first_touch_time_utc": "2026-04-29T21:00:00+00:00"},
        "signal_key": (
            "lpfs:AUDJPY:D1:299:short:"
            "signal_zone_0p5_pullback__fs_structure__1r:2026-04-28 21:00:00+00:00"
        ),
    },
    "occurred_at_utc": "2026-04-30T19:48:15.118083+00:00",
    "signal_key": (
        "lpfs:AUDJPY:D1:299:short:"
        "signal_zone_0p5_pullback__fs_structure__1r:2026-04-28 21:00:00+00:00"
    ),
}
ARCHIVED_STARTUP_ROW = {
    "event": "vps_startup_alert",
    "occurred_at_utc": "2026-05-06T06:24:39.584841+00:00",
    "startup_snapshot": {
        "boot_time_utc": "2026-05-06T03:44:19.5000000Z",
        "detected_at_utc": "2026-05-06T06:24:37.381338+00:00",
        "restart_event_time_utc": "2026-05-06T03:44:23.9462830Z",
    },
}


def _pending(**overrides) -> LiveTrackedOrder:
    values = {
        "signal_key": CANONICAL_KEY,
        "order_ticket": 9001,
        "symbol": "EURUSD",
        "timeframe": "H4",
        "side": "long",
        "order_type": "BUY_LIMIT",
        "volume": 0.01,
        "entry_price": 1.1,
        "stop_loss": 1.09,
        "take_profit": 1.11,
        "target_risk_pct": 0.01,
        "actual_risk_pct": 0.01,
        "expiration_time_utc": "2026-06-03T00:00:00+00:00",
        "magic": 131500,
        "comment": "LPFS",
        "setup_id": "setup",
        "placed_time_utc": "2026-06-01T13:00:00+00:00",
    }
    values.update(overrides)
    return LiveTrackedOrder(**values)


def _config(tmpdir: str) -> LiveSendExecutorConfig:
    return LiveSendExecutorConfig(
        execution_mode="LIVE_SEND",
        live_send_enabled=True,
        real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS",
        symbols=("EURUSD",),
        timeframes=("H4",),
        journal_path=str(Path(tmpdir) / "journal.jsonl"),
        state_path=str(Path(tmpdir) / "state.json"),
        market_recovery_mode="disabled",
    )


def _active(**overrides) -> LiveTrackedPosition:
    values = {
        "signal_key": CANONICAL_KEY,
        "position_id": 7001,
        "order_ticket": 9001,
        "symbol": "EURUSD",
        "timeframe": "H4",
        "side": "long",
        "volume": 0.01,
        "entry_price": 1.1,
        "stop_loss": 1.09,
        "take_profit": 1.11,
        "target_risk_pct": 0.01,
        "actual_risk_pct": 0.01,
        "opened_time_utc": "2026-06-01T13:00:00+00:00",
        "magic": 131500,
        "comment": "LPFS",
        "setup_id": "setup",
    }
    values.update(overrides)
    return LiveTrackedPosition(**values)


class SnapshotMT5:
    ORDER_STATE_CANCELED = 2
    ORDER_STATE_EXPIRED = 3
    ORDER_STATE_REJECTED = 4
    ORDER_REASON_CLIENT = 0
    ORDER_REASON_MOBILE = 1
    ORDER_REASON_WEB = 2

    def __init__(self) -> None:
        self.orders = []
        self.positions = []
        self.history_orders = []
        self.history_deals = []
        self.calls: list[str] = []

    def account_info(self):
        return SimpleNamespace(login=123, server="Real")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def orders_get(self, **kwargs):
        self.calls.append("orders_get")
        return self.orders

    def positions_get(self, **kwargs):
        self.calls.append("positions_get")
        return self.positions

    def history_orders_get(self, *args):
        self.calls.append("history_orders_get")
        return self.history_orders

    def history_deals_get(self, *args, **kwargs):
        self.calls.append("history_deals_get")
        return self.history_deals

    def last_error(self):
        return (0, "ok")


class C01LiveSafetyTests(unittest.TestCase):
    def test_mt5_epoch_direct_utc_seconds_milliseconds_and_dst_boundaries(self) -> None:
        for raw in (
            "2026-01-15T12:00:00Z",
            "2026-06-15T12:00:00Z",
            "2026-03-29T00:59:59Z",
            "2026-03-29T01:00:00Z",
            "2026-10-25T00:59:59Z",
            "2026-10-25T01:00:00Z",
        ):
            timestamp = pd.Timestamp(raw)
            self.assertEqual(mt5_epoch_to_utc(int(timestamp.timestamp())), timestamp)
            self.assertEqual(mt5_epoch_to_utc(int(timestamp.timestamp() * 1000), unit="ms"), timestamp)

    def test_signal_key_parser_preserves_iso_remainder_and_legacy_equivalence(self) -> None:
        canonical, legacy = canonical_and_legacy_signal_keys(CANONICAL_KEY)
        self.assertEqual(parse_signal_key(canonical).signal_time_utc, pd.Timestamp("2026-06-01T12:34:56Z"))
        self.assertEqual(
            normalize_recorded_timestamp(
                parse_signal_key(legacy).signal_time_utc,
                LEGACY_HELSINKI_RELOCALIZED_V1,
            ),
            pd.Timestamp("2026-06-01T12:34:56Z"),
        )
        with self.assertRaises(TimestampSemanticsError):
            parse_signal_key("lpfs:EURUSD:H4:bad")

    def test_timestamp_helpers_fail_closed_for_malformed_values_and_structural_mismatch(self) -> None:
        self.assertEqual(semantics_module.as_utc_timestamp("2026-06-01T12:00:00"), pd.Timestamp("2026-06-01T12:00:00Z"))
        for value in ("not-a-time", pd.NaT):
            with self.subTest(value=value), self.assertRaises(TimestampSemanticsError):
                semantics_module.as_utc_timestamp(value)
        for raw_key in (
            "lpfs::H4:10:long:candidate:2026-06-01T12:34:56+00:00",
            "lpfs:EURUSD:H4:not-an-index:long:candidate:2026-06-01T12:34:56+00:00",
        ):
            with self.subTest(raw_key=raw_key), self.assertRaises(TimestampSemanticsError):
                parse_signal_key(raw_key)
        other_symbol = CANONICAL_KEY.replace("EURUSD", "GBPUSD")
        self.assertFalse(live_module.signal_key_matches_canonical(other_symbol, CANONICAL_KEY))
        self.assertTrue(live_module.signal_key_matches_canonical(CANONICAL_KEY, CANONICAL_KEY))

    def test_v2_envelope_trips_legacy_loader_and_refuses_future_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            save_live_state(path, LiveExecutorState(processed_signal_keys=(CANONICAL_KEY,)))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["state_schema_version"], 2)
            self.assertIsNone(payload["processed_signal_keys"])
            with self.assertRaises(TypeError):
                tuple(payload.get("processed_signal_keys", ()))
            path.write_text(json.dumps({"state_schema_version": 3, "state": {}}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Unsupported LPFS live state schema"):
                load_live_state(path)
            path.write_text(
                json.dumps(
                    {
                        "state_schema_version": 2,
                        "minimum_reader_schema_version": 3,
                        "state": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "requires reader schema 3"):
                load_live_state(path)

    def test_mixed_close_cursors_normalize_and_use_ticket_ordering(self) -> None:
        canonical = pd.Timestamp("2026-06-01T12:00:00Z")
        legacy = canonical.tz_localize(None).tz_localize("Europe/Helsinki").tz_convert("UTC")
        close_v2 = LiveCloseEvent(8, 1, "tp", canonical.isoformat(), 1.1, 1.0, "tp")
        self.assertTrue(
            live_module._close_is_old(
                LiveExecutorState(
                    last_seen_close_ticket=8,
                    last_seen_close_time_utc=legacy.isoformat(),
                    last_seen_close_timestamp_semantics_version=LEGACY_HELSINKI_RELOCALIZED_V1,
                ),
                close_v2,
            )
        )
        close_legacy = LiveCloseEvent(
            9,
            1,
            "tp",
            legacy.isoformat(),
            1.1,
            1.0,
            "tp",
            timestamp_semantics_version=LEGACY_HELSINKI_RELOCALIZED_V1,
        )
        self.assertFalse(
            live_module._close_is_old(
                LiveExecutorState(
                    last_seen_close_ticket=8,
                    last_seen_close_time_utc=canonical.isoformat(),
                    last_seen_close_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
                ),
                close_legacy,
            )
        )
        with self.assertRaises(TimestampSemanticsError):
            live_module._close_is_old(
                LiveExecutorState(
                    last_seen_close_time_utc=canonical.isoformat(),
                    last_seen_close_timestamp_semantics_version="unknown",
                ),
                close_v2,
            )

    def test_atomic_state_failure_activates_kill_switch_and_journals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            kill = Path(tmpdir) / "KILL_SWITCH"
            journal = Path(tmpdir) / "journal.jsonl"
            with mock.patch.object(live_module.os, "replace", side_effect=PermissionError("denied")):
                with self.assertRaises(live_module.LiveStateAtomicReplaceError):
                    save_live_state(path, LiveExecutorState(), kill_switch_path=kill, journal_path=journal)
            self.assertTrue(kill.exists())
            self.assertIn("live_state_atomic_replace_failed", journal.read_text(encoding="utf-8"))

    def test_atomic_state_failure_preserves_existing_kill_switch_when_cleanup_and_journal_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            kill = Path(tmpdir) / "KILL_SWITCH"
            kill.write_text("operator hold\n", encoding="utf-8")
            with (
                mock.patch.object(live_module.os, "replace", side_effect=PermissionError("denied")),
                mock.patch.object(live_module, "append_audit_event", side_effect=OSError("journal unavailable")),
                mock.patch.object(live_module.Path, "unlink", side_effect=OSError("temp locked")),
            ):
                with self.assertRaises(live_module.LiveStateAtomicReplaceError):
                    save_live_state(path, LiveExecutorState(), kill_switch_path=kill, journal_path=Path(tmpdir) / "journal.jsonl")
            self.assertEqual(kill.read_text(encoding="utf-8"), "operator hold\n")

    def test_snapshot_reads_fail_closed_for_every_required_broker_read(self) -> None:
        for attribute in ("orders", "positions", "history_orders", "history_deals"):
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory() as tmpdir:
                mt5 = SnapshotMT5()
                setattr(mt5, attribute, None)
                with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                    validated_broker_snapshot(mt5, _config(tmpdir))
        with tempfile.TemporaryDirectory() as tmpdir:
            mt5 = SnapshotMT5()
            mt5.account_info = lambda: None
            with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                validated_broker_snapshot(mt5, _config(tmpdir))

    def test_broker_read_helpers_fail_closed_and_preserve_error_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = SnapshotMT5()
            mt5.history_deals = None
            with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                live_module._history_deals_for_order_ticket(mt5, 9001, config)
            with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                live_module._history_deals_for_position(mt5, 7001, config)

            class TypeErrorMT5(SnapshotMT5):
                def history_deals_get(self, *args, **kwargs):
                    if kwargs:
                        raise TypeError("position keyword unsupported")
                    return None

            with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                live_module._history_deals_for_position(TypeErrorMT5(), 7001, config)

            mt5 = SnapshotMT5()
            mt5.history_orders = None
            with self.assertRaises(live_module.BrokerSnapshotUnavailable):
                live_module._history_order_for_ticket(mt5, _pending(), config)

            mt5 = SnapshotMT5()
            mt5.last_error = mock.Mock(side_effect=RuntimeError("unavailable"))
            self.assertIn("last_error='unavailable'", live_module._broker_read_error(mt5, "orders_get"))

    def test_inferred_market_fill_time_is_explicitly_not_broker_time(self) -> None:
        intent = SimpleNamespace(
            side="long",
            symbol="EURUSD",
            magic=131500,
            comment="LPFS",
            volume=0.01,
            entry_price=1.1,
            stop_loss=1.09,
            take_profit=1.11,
        )
        outcome = SimpleNamespace(order_ticket=9001, deal_ticket=None)
        item = live_module._fallback_market_recovery_position(SimpleNamespace(ORDER_TYPE_BUY=0), intent, outcome, _config("."))
        fields = live_module._broker_timestamp_fields(item, _config("."), label="position")
        self.assertEqual(fields["provenance"], "inferred_local_send_time")
        self.assertIsNone(fields["raw_time"])
        self.assertIsNone(fields["raw_time_msc"])
        with self.assertRaises(live_module.BrokerSnapshotUnavailable):
            live_module._fallback_market_recovery_position(
                SimpleNamespace(ORDER_TYPE_BUY=0),
                intent,
                SimpleNamespace(order_ticket=None, deal_ticket=None),
                _config("."),
            )

    def test_broker_timestamp_fields_use_mt5_seconds_and_reject_missing_time(self) -> None:
        raw = int(pd.Timestamp("2026-06-01T12:00:00Z").timestamp())
        fields = live_module._broker_timestamp_fields(SimpleNamespace(time=raw), _config("."), label="position")
        self.assertEqual(fields["provenance"], "mt5_time")
        self.assertEqual(fields["normalized_utc"], "2026-06-01T12:00:00+00:00")
        self.assertEqual(live_module._deal_time_utc(SimpleNamespace(time=raw), _config(".")), fields["normalized_utc"])
        with self.assertRaises(live_module.BrokerSnapshotUnavailable):
            live_module._broker_timestamp_fields(SimpleNamespace(), _config("."), label="position")

    def test_reconcile_only_is_proof_bound_canonical_and_retry_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mt5 = SnapshotMT5()
            config = _config(tmpdir)
            _, legacy = canonical_and_legacy_signal_keys(CANONICAL_KEY)
            mt5.history_orders = [
                SimpleNamespace(
                    ticket=9001,
                    state=mt5.ORDER_STATE_CANCELED,
                    reason=mt5.ORDER_REASON_CLIENT,
                    comment="client cancel",
                )
            ]
            state = LiveExecutorState(
                processed_signal_keys=(legacy,),
                processed_signal_key_semantics={legacy: LEGACY_HELSINKI_RELOCALIZED_V1},
                pending_orders=(
                    _pending(
                        signal_key=legacy,
                        signal_key_timestamp_semantics_version=LEGACY_HELSINKI_RELOCALIZED_V1,
                    ),
                ),
            )
            result = reconcile_only_live_state(mt5, config=config, state=state)
            self.assertEqual(result.state.pending_orders, ())
            self.assertIn(CANONICAL_KEY, result.state.processed_signal_keys)
            self.assertTrue(result.operation_id)
            journal = Path(config.journal_path)
            self.assertIn("reconciliation_only_complete", journal.read_text(encoding="utf-8"))

            journal.unlink()
            replay = reconcile_only_live_state(mt5, config=config, state=result.state)
            self.assertGreater(replay.journal_rows_backfilled, 0)
            self.assertIn("reconciliation_only_complete", journal.read_text(encoding="utf-8"))
            self.assertNotIn("order_send", mt5.calls)

    def test_reconcile_only_preserves_state_when_outcome_is_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mt5 = SnapshotMT5()
            config = _config(tmpdir)
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                reconcile_only_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(),)))
            self.assertFalse(Path(config.state_path).exists())

    def test_reconcile_only_rejects_broker_orders_and_inventory_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = SnapshotMT5()
            mt5.orders = [SimpleNamespace(ticket=9001, magic=config.strategy_magic)]
            with self.assertRaisesRegex(RuntimeError, "zero LPFS broker pending orders"):
                reconcile_only_live_state(mt5, config=config, state=LiveExecutorState())

            mt5.orders = []
            with self.assertRaisesRegex(RuntimeError, "active-position mismatch"):
                reconcile_only_live_state(mt5, config=config, state=LiveExecutorState(active_positions=(_active(),)))

    def test_reconciliation_classification_requires_specific_proof(self) -> None:
        mt5 = SnapshotMT5()

        def classify(*, history_order=None, history_deals=(), active_ids=None):
            snapshot = live_module.ValidatedBrokerSnapshot("123", "Real", (), (), tuple(() if history_order is None else (history_order,)), tuple(history_deals))
            return live_module._classify_stale_pending_for_reconciliation(
                mt5,
                _pending(),
                snapshot=snapshot,
                active_position_ids=set() if active_ids is None else set(active_ids),
            )

        deal = SimpleNamespace(order=9001, position_id=7001)
        self.assertEqual(classify(history_deals=(deal,), active_ids=(7001,))["status"], "filled_confirmed")
        self.assertEqual(classify(history_deals=(deal,))["status"], "unresolved")
        self.assertEqual(classify(history_order=SimpleNamespace(ticket=9001, state=mt5.ORDER_STATE_EXPIRED))["status"], "expired_confirmed")
        self.assertEqual(classify(history_order=SimpleNamespace(ticket=9001, state=mt5.ORDER_STATE_REJECTED))["status"], "rejected_confirmed")
        self.assertEqual(classify()["reason"], "missing_manual_cancel_proof")

    def test_reconciliation_journal_backfill_is_idempotent_and_skips_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            operation_id = "op-id"
            journal = Path(config.journal_path)
            journal.write_text(
                f'{{"reconciliation_operation_id":"{operation_id}","reconciliation_row_id":"{operation_id}:0"}}\n'
                f'{{"reconciliation_operation_id":"{operation_id}"}}\n'
                f"{operation_id} malformed json\n"
                '{"event":"unrelated"}\n',
                encoding="utf-8",
            )
            receipt = {
                "operation_id": operation_id,
                "state_schema_version": 2,
                "active_position_ids": [],
                "classifications": [{"order_ticket": 9001, "status": "manual_broker_cancel_confirmed"}],
            }
            self.assertEqual(live_module._append_missing_reconciliation_rows(config, receipt), 1)
            self.assertEqual(live_module._append_missing_reconciliation_rows(config, receipt), 0)

    def test_malformed_operational_key_is_audited_and_blocks_new_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            with self.assertRaises(TimestampSemanticsError):
                live_module._validate_operational_signal_keys(
                    LiveExecutorState(processed_signal_keys=("malformed",)),
                    journal_path=config.journal_path,
                )
            with self.assertRaises(TimestampSemanticsError):
                live_module._validate_operational_signal_keys(LiveExecutorState(processed_signal_keys=("malformed",)))
            self.assertIn("malformed_operational_signal_key", Path(config.journal_path).read_text(encoding="utf-8"))

            setup = SimpleNamespace(
                setup_id="setup",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                signal_index=10,
                entry_index=11,
                entry_price=1.1,
                stop_price=1.09,
                target_price=1.11,
                metadata={"candidate_id": "candidate", "fs_signal_time_utc": "2026-06-01T12:34:56Z"},
            )
            result = live_module.process_trade_setup_live_send(
                SnapshotMT5(),
                setup,
                config=config,
                state=LiveExecutorState(processed_signal_keys=("malformed",)),
            )
            self.assertEqual(result.status, "blocked")

    def test_canonicalization_covers_checked_pending_and_active_legacy_keys(self) -> None:
        _, legacy = canonical_and_legacy_signal_keys(CANONICAL_KEY)
        state = LiveExecutorState(
            order_checked_signal_keys=(legacy,),
            order_checked_signal_key_semantics={legacy: LEGACY_HELSINKI_RELOCALIZED_V1},
            pending_orders=(_pending(signal_key=legacy),),
            active_positions=(_active(signal_key=legacy),),
        )
        canonical = live_module._canonicalize_live_state_signal_keys(state, _config("."))
        self.assertEqual(canonical.order_checked_signal_keys, (CANONICAL_KEY,))
        self.assertEqual(canonical.pending_orders[0].legacy_signal_key, legacy)
        self.assertEqual(canonical.active_positions[0].legacy_signal_key, legacy)

    def test_signal_key_expansion_and_notification_dedupe_cover_legacy_and_malformed_paths(self) -> None:
        _, legacy = canonical_and_legacy_signal_keys(CANONICAL_KEY)
        expanded = live_module._expanded_existing_signal_keys(
            LiveExecutorState(
                processed_signal_keys=(CANONICAL_KEY, legacy),
                processed_signal_key_semantics={
                    CANONICAL_KEY: MT5_EPOCH_UTC_V2,
                    legacy: "unknown",
                },
            )
        )
        self.assertIn(CANONICAL_KEY, expanded)
        self.assertIn(legacy, expanded)
        event = NotificationEvent(kind="setup_rejected", mode="LIVE", title="Blocked", signal_key=CANONICAL_KEY)
        self.assertTrue(
            live_module._notification_event_already_recorded(
                LiveExecutorState(notified_event_keys=(f"setup_blocked:{legacy}",)),
                f"setup_blocked:{CANONICAL_KEY}",
                event,
            )
        )
        self.assertTrue(
            live_module._notification_event_already_recorded(
                LiveExecutorState(notified_event_keys=("exact",)),
                "exact",
                event,
            )
        )
        self.assertFalse(
            live_module._notification_event_already_recorded(
                LiveExecutorState(),
                "setup_blocked:not-a-key",
                NotificationEvent(kind="setup_rejected", mode="LIVE", title="Blocked", signal_key="not-a-key"),
            )
        )

    def test_close_cursor_newer_time_record_once_and_retryable_send_helpers(self) -> None:
        self.assertFalse(
            live_module._close_is_old(
                LiveExecutorState(
                    last_seen_close_time_utc="2026-06-01T12:00:00Z",
                    last_seen_close_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
                ),
                LiveCloseEvent(1, 1, "tp", "2026-06-01T13:00:00Z", 1.1, 1.0, "tp"),
            )
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            event = NotificationEvent(kind="setup_rejected", mode="LIVE", title="Blocked")
            state = LiveExecutorState(notified_event_keys=("exact",))
            self.assertIs(live_module._record_event_once(config, state, None, "exact", event), state)
        malformed = LiveOrderSendOutcome(False, {}, "not-an-int", "market closed")
        self.assertEqual(live_module._retryable_order_send_block_status(malformed), "market_closed")
        self.assertFalse(live_module._is_market_closed_block("not-an-int", "other"))

    def test_snapshot_hash_is_order_stable_and_serializes_supported_broker_items(self) -> None:
        BrokerTuple = namedtuple("BrokerTuple", "ticket")
        first = live_module.ValidatedBrokerSnapshot("123", "Real", (SimpleNamespace(ticket=2), BrokerTuple(1), 3), (), (), ())
        second = live_module.ValidatedBrokerSnapshot("123", "Real", (3, BrokerTuple(1), SimpleNamespace(ticket=2)), (), (), ())
        self.assertEqual(first.stable_hash(), second.stable_hash())

    def test_legacy_normalizer_changes_only_allowlisted_fields(self) -> None:
        raw = {
            "occurred_at_utc": "2026-06-01T12:00:00+00:00",
            "signal_key": canonical_and_legacy_signal_keys(CANONICAL_KEY)[1],
            "notification_event": {
                "fields": {"opened_utc": "2026-06-01T09:00:00+00:00"},
            },
        }
        normalized, provenance = normalize_row(raw, broker_timezone="Europe/Helsinki")
        self.assertEqual(normalized["occurred_at_utc"], raw["occurred_at_utc"])
        self.assertEqual(normalized["signal_key"], CANONICAL_KEY)
        self.assertEqual(normalized["notification_event"]["fields"]["opened_utc"], "2026-06-01T12:00:00+00:00")
        self.assertTrue(provenance["changes"])

    def test_legacy_open_and_v2_close_emit_canonical_one_hour_hold(self) -> None:
        canonical_open = pd.Timestamp("2026-06-01T12:00:00Z")
        legacy_open = canonical_open.tz_localize(None).tz_localize("Europe/Helsinki").tz_convert("UTC")
        event = live_module._close_event(
            _active(
                opened_time_utc=legacy_open.isoformat(),
                timestamp_semantics_version=LEGACY_HELSINKI_RELOCALIZED_V1,
                timestamp_provenance="legacy_state",
            ),
            LiveCloseEvent(8, 7001, "tp", "2026-06-01T13:00:00Z", 1.11, 1.0, "tp"),
        )
        self.assertEqual(event.fields["opened_utc"], "2026-06-01T12:00:00+00:00")
        self.assertEqual(event.fields["closed_utc"], "2026-06-01T13:00:00+00:00")
        self.assertEqual(event.fields["opened_timestamp_semantics_version"], MT5_EPOCH_UTC_V2)
        self.assertEqual(event.fields["opened_source_timestamp_semantics_version"], LEGACY_HELSINKI_RELOCALIZED_V1)
        self.assertEqual(event.fields["diagnostics"]["execution"]["fill_to_close_seconds"], 3600)
        self.assertIn("Hold: 1h", format_notification_message(event))
        summary = build_closed_trade_summaries([{"event": event.kind, "notification_event": event.to_dict()}])
        self.assertEqual(summary[0].opened_utc, "2026-06-01T12:00:00+00:00")
        self.assertEqual(summary[0].closed_utc, "2026-06-01T13:00:00+00:00")

    def test_position_open_event_emits_canonical_open_provenance(self) -> None:
        canonical_open = pd.Timestamp("2026-06-01T12:00:00Z")
        legacy_open = canonical_open.tz_localize(None).tz_localize("Europe/Helsinki").tz_convert("UTC")
        event = live_module._position_opened_event(
            _active(
                opened_time_utc=legacy_open.isoformat(),
                timestamp_semantics_version=LEGACY_HELSINKI_RELOCALIZED_V1,
                raw_mt5_time=123,
                raw_mt5_time_msc=456,
                timestamp_provenance="legacy_state",
            ),
            SimpleNamespace(comment="filled"),
        )
        self.assertEqual(event.fields["opened_utc"], "2026-06-01T12:00:00+00:00")
        self.assertEqual(event.fields["opened_raw_mt5_time"], 123)
        self.assertEqual(event.fields["opened_raw_mt5_time_msc"], 456)
        self.assertEqual(event.fields["opened_timestamp_provenance"], "legacy_state")

    def test_normalizer_preserves_v2_fields_rebuilds_keys_and_refuses_unknown_semantics(self) -> None:
        trade_key = "EURUSD|H4|long|10|candidate|2026-06-01T12:34:56+00:00"
        raw = {
            "signal_key": CANONICAL_KEY,
            "event_key": f"setup_blocked:{CANONICAL_KEY}:spread",
            "diagnostics": {
                "timestamp_semantics_version": MT5_EPOCH_UTC_V2,
                "backtest_join": {"trade_key": trade_key},
            },
            "notification_event": {
                "fields": {
                    "opened_utc": "2026-06-01T12:00:00+00:00",
                    "opened_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
                },
            },
        }
        normalized, provenance = normalize_row(raw, broker_timezone="Europe/Helsinki")
        self.assertEqual(normalized["signal_key"], CANONICAL_KEY)
        self.assertEqual(normalized["event_key"], raw["event_key"])
        self.assertEqual(normalized["notification_event"]["fields"]["opened_utc"], "2026-06-01T12:00:00+00:00")
        self.assertEqual(normalized["diagnostics"]["backtest_join"]["trade_key"], trade_key)
        self.assertEqual(provenance["changes"], [])

        unknown = {
            "notification_event": {
                "fields": {
                    "opened_utc": "2026-06-01T12:00:00+00:00",
                    "opened_timestamp_semantics_version": "unknown",
                },
            },
        }
        with self.assertRaises(C01NormalizationError):
            normalize_row(unknown, broker_timezone="Europe/Helsinki")

    def test_normalizer_prefers_raw_epoch_and_warns_for_unsupported_timestamp_paths(self) -> None:
        raw_epoch = int(pd.Timestamp("2026-06-01T12:00:00Z").timestamp())
        normalized, provenance = normalize_row(
            {
                "event": "market_snapshot",
                "market_time_utc": "2026-06-01T09:00:00+00:00",
                "raw_mt5_time": raw_epoch,
                "unexpected_utc": "2026-06-01T09:00:00+00:00",
            },
            broker_timezone="Europe/Helsinki",
        )
        self.assertEqual(normalized["market_time_utc"], "2026-06-01T12:00:00+00:00")
        self.assertIn("unresolved unsupported timestamp-bearing path", provenance["unresolved_warnings"][0])

    def test_normalizer_classifies_actual_archived_expiration_row_shapes(self) -> None:
        backstop, backstop_provenance = normalize_row(ARCHIVED_BACKSTOP_MODIFY_ROW, broker_timezone="Europe/Helsinki")
        self.assertEqual(backstop["old_expiration_utc"], "2026-05-02T16:00:00+00:00")
        self.assertEqual(backstop["new_broker_backstop_expiration_utc"], "2026-05-12T16:00:00+00:00")
        self.assertEqual(backstop["occurred_at_utc"], ARCHIVED_BACKSTOP_MODIFY_ROW["occurred_at_utc"])
        self.assertEqual(backstop_provenance["unresolved_warnings"], [])

        order_sent, order_sent_provenance = normalize_row(ARCHIVED_ORDER_SENT_ROW, broker_timezone="Europe/Helsinki")
        fields = order_sent["notification_event"]["fields"]
        self.assertEqual(fields["expiration_utc"], "2026-06-09T08:00:00+00:00")
        self.assertEqual(fields["broker_backstop_expiration_utc"], "2026-06-09T08:00:00+00:00")
        self.assertEqual(fields["placed_time_utc"], ARCHIVED_ORDER_SENT_ROW["notification_event"]["fields"]["placed_time_utc"])
        self.assertEqual(order_sent["occurred_at_utc"], ARCHIVED_ORDER_SENT_ROW["occurred_at_utc"])
        self.assertEqual(order_sent_provenance["unresolved_warnings"], [])

    def test_normalizer_preserves_actual_archived_startup_system_timestamps(self) -> None:
        normalized, provenance = normalize_row(ARCHIVED_STARTUP_ROW, broker_timezone="Europe/Helsinki")
        self.assertEqual(normalized["startup_snapshot"], ARCHIVED_STARTUP_ROW["startup_snapshot"])
        self.assertEqual(normalized["occurred_at_utc"], ARCHIVED_STARTUP_ROW["occurred_at_utc"])
        self.assertEqual(provenance["unresolved_warnings"], [])

    def test_normalizer_rebuilds_legacy_signal_event_and_trade_keys(self) -> None:
        _, legacy = canonical_and_legacy_signal_keys(CANONICAL_KEY)
        legacy_time = parse_signal_key(legacy).signal_time_utc.isoformat()
        raw = {
            "signal_key": legacy,
            "event_key": f"setup_blocked:{legacy}:spread",
            "diagnostics": {
                "backtest_join": {
                    "signal_key": legacy,
                    "trade_key": f"EURUSD|H4|long|10|candidate|{legacy_time}",
                },
            },
        }
        normalized, provenance = normalize_row(raw, broker_timezone="Europe/Helsinki")
        self.assertEqual(normalized["signal_key"], CANONICAL_KEY)
        self.assertEqual(normalized["event_key"], f"setup_blocked:{CANONICAL_KEY}:spread")
        self.assertEqual(
            normalized["diagnostics"]["backtest_join"]["trade_key"],
            "EURUSD|H4|long|10|candidate|2026-06-01T12:34:56+00:00",
        )
        self.assertGreaterEqual(len(provenance["changes"]), 3)

    def test_normalizer_rebuilds_actual_archived_space_separated_event_key(self) -> None:
        normalized, provenance = normalize_row(ARCHIVED_SPACE_EVENT_KEY_ROW, broker_timezone="Europe/Helsinki")
        self.assertEqual(
            normalized["event_key"],
            (
                "setup_rejected:lpfs:AUDJPY:D1:299:short:"
                "signal_zone_0p5_pullback__fs_structure__1r:2026-04-29T00:00:00+00:00:missed_entry"
            ),
        )
        self.assertEqual(
            normalized["signal_key"],
            (
                "lpfs:AUDJPY:D1:299:short:"
                "signal_zone_0p5_pullback__fs_structure__1r:2026-04-29T00:00:00+00:00"
            ),
        )
        self.assertTrue(provenance["changes"])

    def test_normalizer_refuses_malformed_embedded_lpfs_event_key(self) -> None:
        with self.assertRaises(C01NormalizationError):
            normalize_row({"event_key": "setup_rejected:lpfs:malformed"}, broker_timezone="Europe/Helsinki")

    def test_normalized_packet_manifest_blocks_unresolved_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "legacy.jsonl"
            source.write_text('{"unexpected_utc":"2026-06-01T09:00:00+00:00"}\n', encoding="utf-8")
            packet = normalize_journal(source, Path(tmpdir) / "normalized", broker_timezone="Europe/Helsinki")
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["warning_count"], 1)
            self.assertFalse(manifest["safe_for_strategy_analysis"])
            self.assertEqual(manifest["unresolved_warning_inventory"]["unexpected_utc: unresolved unsupported timestamp-bearing path"], 1)

    def test_read_only_evidence_export_is_atomic_and_manifested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mt5 = SnapshotMT5()
            packet = export_evidence(
                mt5,
                lane="FTMO",
                output_root=Path(tmpdir),
                history_start_utc=pd.Timestamp("2000-01-01T00:00:00Z").to_pydatetime(),
                history_end_utc=pd.Timestamp("2026-06-01T00:00:00Z").to_pydatetime(),
            )
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["orders"], 0)
            self.assertTrue(manifest["read_only_contract"])
            mt5.history_deals = None
            with self.assertRaises(EvidenceExportError):
                export_evidence(
                    mt5,
                    lane="FTMO",
                    output_root=Path(tmpdir),
                    history_start_utc=pd.Timestamp("2000-01-01T00:00:00Z").to_pydatetime(),
                    history_end_utc=pd.Timestamp("2026-06-01T00:00:00Z").to_pydatetime(),
                )

    def test_status_tool_distinguishes_unknown_from_zero(self) -> None:
        script = (WORKSPACE_ROOT / "scripts" / "Get-LpfsDualVpsStatus.ps1").read_text(encoding="utf-8")
        self.assertIn("account_info=ERROR/UNKNOWN", script)
        self.assertIn("terminal_info=ERROR/UNKNOWN", script)
        self.assertIn("orders_get=ERROR/UNKNOWN", script)
        self.assertIn("positions_get=ERROR/UNKNOWN", script)
        self.assertNotIn("orders = mt5.orders_get() or ()", script)

    def test_weekly_reader_understands_v1_and_v2_state(self) -> None:
        flat = {"pending_orders": [1], "active_positions": [1, 2], "processed_signal_keys": [1, 2, 3]}
        self.assertEqual(live_state_counts(flat), {"pending_orders": 1, "active_positions": 2, "processed_signal_keys": 3})
        self.assertEqual(
            live_state_counts({"state_schema_version": 2, "state": flat}),
            {"pending_orders": 1, "active_positions": 2, "processed_signal_keys": 3},
        )

    def test_reconcile_only_cli_branch_requires_kill_switch_and_never_runs_normal_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            kill = Path(tmpdir) / "KILL_SWITCH"
            heartbeat = Path(tmpdir) / "heartbeat.json"
            settings = SimpleNamespace(executor=config, local=SimpleNamespace())
            self.assertEqual(
                runner_module._run_reconcile_only(
                    settings=settings,
                    config_path="config.local.json",
                    kill_switch_path=kill,
                    heartbeat_path=heartbeat,
                ),
                runner_module.KILL_SWITCH_EXIT_CODE,
            )

            kill.write_text("operator hold\n", encoding="utf-8")
            fake_mt5 = SimpleNamespace(shutdown=mock.Mock())
            fake_result = SimpleNamespace(
                operation_id="op",
                classifications=(),
                journal_rows_backfilled=0,
            )
            with (
                mock.patch.dict(sys.modules, {"MetaTrader5": fake_mt5}),
                mock.patch.object(runner_module, "initialize_mt5_session"),
                mock.patch.object(runner_module, "load_live_state", return_value=LiveExecutorState()),
                mock.patch.object(runner_module, "reconcile_only_live_state", return_value=fake_result),
                mock.patch.object(runner_module, "_mt5_account_fields", return_value={}),
                mock.patch.object(runner_module, "run_live_send_cycle") as run_cycle,
            ):
                code = runner_module._run_reconcile_only(
                    settings=settings,
                    config_path="config.local.json",
                    kill_switch_path=kill,
                    heartbeat_path=heartbeat,
                )
            self.assertEqual(code, 0)
            run_cycle.assert_not_called()
            fake_mt5.shutdown.assert_called_once()

    def test_one_cycle_canary_requires_exact_acknowledgment_and_single_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {"expected_login": "123", "expected_server": "Real"},
                        "live_send": {
                            "execution_mode": "LIVE_SEND",
                            "live_send_enabled": True,
                            "real_money_ack": "I_UNDERSTAND_THIS_SENDS_REAL_ORDERS",
                            "market_recovery_mode": "disabled",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                sys,
                "argv",
                [
                    "run_lp_force_strike_live_executor.py",
                    "--config",
                    str(config_path),
                    "--one-cycle-canary",
                    "--cycles",
                    "2",
                    "--canary-exposure-ack",
                    runner_module.ONE_CYCLE_CANARY_ACK,
                ],
            ):
                self.assertEqual(runner_module.main(), 2)


if __name__ == "__main__":
    unittest.main()
