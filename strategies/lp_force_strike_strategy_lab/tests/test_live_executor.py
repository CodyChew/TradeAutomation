from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

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
    LIVE_SEND_ACK,
    LIVE_SEND_MODE,
    DynamicSpreadGate,
    LiveCloseEvent,
    LiveExecutorState,
    MarketRecoveryCheck,
    MissedEntryCheck,
    LiveSendExecutorConfig,
    LiveTrackedOrder,
    LiveTrackedPosition,
    LocalConfigError,
    OrderCheckOutcome,
    SkippedTrade,
    TelegramConfig,
    TelegramNotifier,
    broker_money_risk_per_lot,
    build_order_check_request,
    cancel_pending_order,
    current_strategy_orders,
    current_strategy_positions,
    dynamic_spread_gate,
    market_recovery_check,
    latest_close_for_position,
    live_execution_safety_from_config,
    live_risk_buckets_from_config,
    load_live_send_settings,
    load_live_state,
    missed_entry_before_placement,
    pending_order_bar_expiry_check,
    process_trade_setup_live_send,
    reconcile_live_state,
    run_live_send_cycle,
    save_live_state,
    run_market_order_check,
    send_pending_order,
    send_market_recovery_order,
    validate_live_send_settings,
)
from lp_force_strike_strategy_lab.execution_contract import ExecutionSafetyLimits, MT5MarketSnapshot, MT5OrderIntent, MT5SymbolExecutionSpec  # noqa: E402
import lp_force_strike_strategy_lab.live_executor as live_module  # noqa: E402


def _setup(
    *,
    side: str = "long",
    timeframe: str = "H4",
    entry: float = 1.1000,
    stop: float = 1.0950,
    target: float = 1.1050,
    metadata: dict | None = None,
) -> TradeSetup:
    return TradeSetup(
        setup_id="EURUSD_H4_long",
        side=side,  # type: ignore[arg-type]
        entry_index=11,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        symbol="EURUSD",
        timeframe=timeframe,
        signal_index=10,
        metadata={
            "candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
            "fs_signal_time_utc": "2026-01-01T00:00:00Z",
            **({} if metadata is None else metadata),
        },
    )


def _short_setup() -> TradeSetup:
    return _setup(side="short", entry=1.2000, stop=1.2100, target=1.1900)


def _config(tmpdir: str, **overrides) -> LiveSendExecutorConfig:
    values = {
        "execution_mode": LIVE_SEND_MODE,
        "live_send_enabled": True,
        "real_money_ack": LIVE_SEND_ACK,
        "symbols": ("EURUSD",),
        "timeframes": ("H4",),
        "broker_timezone": "UTC",
        "journal_path": str(Path(tmpdir) / "live.jsonl"),
        "state_path": str(Path(tmpdir) / "state.json"),
    }
    values.update(overrides)
    return LiveSendExecutorConfig(**values)


def _pending(**overrides) -> LiveTrackedOrder:
    values = {
        "signal_key": "lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
        "order_ticket": 9001,
        "symbol": "EURUSD",
        "timeframe": "H4",
        "side": "long",
        "order_type": "BUY_LIMIT",
        "volume": 0.02,
        "entry_price": 1.1,
        "stop_loss": 1.095,
        "take_profit": 1.105,
        "target_risk_pct": 0.01,
        "actual_risk_pct": 0.01,
        "expiration_time_utc": "2099-01-01T00:00:00+00:00",
        "magic": 131500,
        "comment": "LPFS H4 L 10",
        "setup_id": "setup",
        "placed_time_utc": "2026-01-01T04:00:00+00:00",
        "signal_time_utc": "2026-01-01T00:00:00+00:00",
        "max_entry_wait_bars": 6,
        "strategy_expiry_mode": "bar_count",
        "broker_backstop_expiration_time_utc": "2099-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return LiveTrackedOrder(**values)


def _rates_from_times(times: list[str]) -> list[dict]:
    return [
        {
            "time": int(pd.Timestamp(raw_time).timestamp()),
            "open": 1.1,
            "high": 1.2,
            "low": 1.0,
            "close": 1.15,
            "tick_volume": 10,
            "spread": 2,
        }
        for raw_time in times
    ]


def _active(**overrides) -> LiveTrackedPosition:
    values = {
        "signal_key": "lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
        "position_id": 7001,
        "order_ticket": 9001,
        "symbol": "EURUSD",
        "timeframe": "H4",
        "side": "long",
        "volume": 0.02,
        "entry_price": 1.1,
        "stop_loss": 1.095,
        "take_profit": 1.105,
        "target_risk_pct": 0.01,
        "actual_risk_pct": 0.01,
        "opened_time_utc": "2026-01-01T04:30:00+00:00",
        "magic": 131500,
        "comment": "LPFS H4 L 10",
        "setup_id": "setup",
    }
    values.update(overrides)
    return LiveTrackedPosition(**values)


class FakeNotifierClient:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def post_json(self, url: str, payload: dict, *, timeout_seconds: float) -> dict:
        self.payloads.append(payload)
        return {"ok": True, "result": {"message_id": len(self.payloads)}}


class FakeMT5:
    TIMEFRAME_H4 = 240
    TIMEFRAME_H8 = 480
    TIMEFRAME_H12 = 720
    TIMEFRAME_D1 = 1440
    TIMEFRAME_W1 = 10080
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    ORDER_TIME_GTC = 0
    ORDER_TIME_SPECIFIED = 2
    ORDER_TIME_SPECIFIED_DAY = 3
    SYMBOL_EXPIRATION_GTC = 1
    SYMBOL_EXPIRATION_DAY = 2
    SYMBOL_EXPIRATION_SPECIFIED = 4
    SYMBOL_EXPIRATION_SPECIFIED_DAY = 8
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_INVALID_FILL = 10030
    TRADE_RETCODE_CLIENT_DISABLES_AT = 10027
    TRADE_RETCODE_MARKET_CLOSED = 10018
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5

    def __init__(self) -> None:
        self.account = SimpleNamespace(login=123, server="Real", equity=100_000.0, currency="USD")
        self.info = SimpleNamespace(
            digits=5,
            point=0.0001,
            trade_tick_value=10.0,
            trade_tick_size=0.0001,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=0,
            trade_freeze_level=0,
            filling_mode=3,
            visible=True,
            trade_allowed=True,
        )
        self.tick = SimpleNamespace(
            bid=1.1018,
            ask=1.1020,
            time_msc=int(pd.Timestamp("2026-01-01T04:01:00Z").timestamp() * 1000),
            time=0,
        )
        self.rates = [
            {
                "time": int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "tick_volume": 10,
                "spread": 2,
            },
            {
                "time": int(pd.Timestamp("2026-01-01T04:00:00Z").timestamp()),
                "open": 1.1,
                "high": 1.2,
                "low": 1.1005,
                "close": 1.15,
                "tick_volume": 11,
                "spread": 3,
            },
        ]
        self.order_check_result = SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="check ok")
        self.order_send_result = SimpleNamespace(retcode=self.TRADE_RETCODE_PLACED, comment="placed", order=9001, deal=0)
        self.order_check_requests: list[dict] = []
        self.order_send_requests: list[dict] = []
        self.orders: list[SimpleNamespace] | None = []
        self.positions: list[SimpleNamespace] | None = []
        self.deals: list[SimpleNamespace] | None = []
        self.history_orders: list[SimpleNamespace] | None = []
        self.direct_deals: list[SimpleNamespace] | None = None
        self.direct_deals_type_error = False
        self.calc_profit_result: float | None = -500.0
        self.auto_create_market_position = True

    def account_info(self):
        return self.account

    def symbol_info(self, symbol: str):
        return self.info

    def symbol_select(self, symbol: str, visible: bool) -> bool:
        return True

    def symbol_info_tick(self, symbol: str):
        return self.tick

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, count: int):
        return self.rates

    def order_calc_profit(self, order_type: int, symbol: str, volume: float, entry: float, stop: float):
        self.last_calc_profit = (order_type, symbol, volume, entry, stop)
        return self.calc_profit_result

    def order_check(self, request: dict):
        self.order_check_requests.append(request)
        if isinstance(self.order_check_result, list):
            if not self.order_check_result:
                return None
            return self.order_check_result.pop(0)
        return self.order_check_result

    def order_send(self, request: dict):
        self.order_send_requests.append(request)
        if (
            self.auto_create_market_position
            and request.get("action") == self.TRADE_ACTION_DEAL
            and self.order_send_result is not None
            and int(getattr(self.order_send_result, "retcode", 0) or 0) == self.TRADE_RETCODE_DONE
        ):
            order_ticket = int(getattr(self.order_send_result, "order", 0) or 0) or 9101
            deal_ticket = int(getattr(self.order_send_result, "deal", 0) or 0) or order_ticket
            self.positions = [
                SimpleNamespace(
                    identifier=deal_ticket,
                    ticket=order_ticket,
                    symbol=request["symbol"],
                    magic=request["magic"],
                    type=request["type"],
                    comment=request["comment"],
                    volume=request["volume"],
                    price_open=request["price"],
                    sl=request["sl"],
                    tp=request["tp"],
                    time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                    time=0,
                )
            ]
        return self.order_send_result

    def orders_get(self, *, symbol: str):
        return self.orders

    def positions_get(self, *, symbol: str):
        return self.positions

    def history_deals_get(self, *args, **kwargs):
        if "position" in kwargs:
            if self.direct_deals_type_error:
                raise TypeError("position keyword unsupported")
            return self.direct_deals
        return self.deals

    def history_orders_get(self, *args, **kwargs):
        return self.history_orders


class LiveExecutorTests(unittest.TestCase):
    def test_live_settings_are_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {"expected_login": "123", "expected_server": "Real"},
                        "telegram": {"enabled": True, "bot_token": "token", "chat_id": "chat", "dry_run": False},
                        "dry_run": {"symbols": ["EURUSD", "GBPUSD"], "timeframes": ["H4"], "broker_timezone": "UTC"},
                        "live_send": {
                            "execution_mode": LIVE_SEND_MODE,
                            "live_send_enabled": True,
                            "real_money_ack": LIVE_SEND_ACK,
                            "symbols": ["EURUSD"],
                            "max_lots_per_order": "0.5",
                            "max_risk_pct_per_trade": "1.5",
                            "risk_buckets_pct": {"H4": 0.25, "H8": 0.25},
                            "risk_bucket_scale": 0.05,
                            "strategy_magic": 231500,
                            "order_comment_prefix": "LPFSIC",
                            "max_open_risk_pct": 0.65,
                            "max_spread_risk_fraction": 0.1,
                            "require_lp_pivot_before_fs_mother": False,
                            "journal_path": str(Path(tmpdir) / "absolute_journal.jsonl"),
                            "state_path": "live/state.json",
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = load_live_send_settings(config_path, env={})
            self.assertEqual(settings.executor.symbols, ("EURUSD",))
            self.assertEqual(settings.executor.timeframes, ("H4",))
            self.assertTrue(Path(settings.executor.journal_path).is_absolute())
            self.assertEqual(settings.executor.max_lots_per_order, 0.5)
            self.assertEqual(settings.executor.max_risk_pct_per_trade, 1.5)
            self.assertEqual(settings.executor.risk_buckets_pct, {"H4": 0.25, "H8": 0.25})
            self.assertEqual(settings.executor.strategy_magic, 231500)
            self.assertEqual(settings.executor.order_comment_prefix, "LPFSIC")
            self.assertEqual(settings.executor.market_recovery_mode, "better_than_entry_only")
            self.assertEqual(settings.executor.market_recovery_deviation_points, 0)
            self.assertFalse(settings.executor.require_lp_pivot_before_fs_mother)
            self.assertFalse(live_module._dry_compatible_config(settings.executor).require_lp_pivot_before_fs_mother)
            self.assertNotIn("'token'", str(settings.safe_dict()))
            validate_live_send_settings(settings)

            bad_values = [
                {"execution_mode": "DRY_RUN"},
                {"live_send_enabled": False},
                {"real_money_ack": ""},
                {"risk_bucket_scale": 0},
                {"max_open_risk_pct": 0},
                {"max_spread_risk_fraction": 0},
                {"max_spread_risk_fraction": 1.5},
                {"market_recovery_mode": "always"},
                {"market_recovery_deviation_points": -1},
            ]
            for overrides in bad_values:
                with self.subTest(overrides=overrides), self.assertRaises(LocalConfigError):
                    validate_live_send_settings(type(settings)(settings.local, type(settings.executor)(**{**settings.executor.safe_dict(), **overrides})))

            fallback = load_live_send_settings(Path(tmpdir) / "missing.json", env={"MT5_EXPECTED_LOGIN": "1", "MT5_EXPECTED_SERVER": "Real"})
            self.assertEqual(fallback.executor.risk_bucket_scale, 0.05)
            self.assertTrue(fallback.executor.require_lp_pivot_before_fs_mother)
            self.assertTrue(live_module._optional_bool(None, default=True))
            self.assertFalse(live_module._optional_bool("off", default=True))
            with self.assertRaisesRegex(LocalConfigError, "execution_mode"):
                validate_live_send_settings(fallback)

            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {"expected_login": "123", "expected_server": "Real"},
                        "live_send": {"symbols": "EURUSD"},
                    }
                ),
                encoding="utf-8",
            )
            string_symbol = load_live_send_settings(config_path, env={})
            self.assertEqual(string_symbol.executor.symbols, ("EURUSD",))

            config_path.write_text(json.dumps({"live_send": {"risk_buckets_pct": ["H4", 0.25]}}), encoding="utf-8")
            with self.assertRaisesRegex(LocalConfigError, "risk_buckets_pct must be an object"):
                load_live_send_settings(config_path, env={})

    def test_live_settings_accept_powershell_utf8_bom_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {"expected_login": "123", "expected_server": "Real"},
                        "live_send": {
                            "execution_mode": LIVE_SEND_MODE,
                            "live_send_enabled": True,
                            "real_money_ack": LIVE_SEND_ACK,
                            "symbols": ["EURUSD"],
                            "timeframes": ["H4"],
                        },
                    }
                ),
                encoding="utf-8-sig",
            )

            settings = load_live_send_settings(config_path, env={})

            self.assertEqual(settings.local.expected_login, "123")
            self.assertEqual(settings.executor.symbols, ("EURUSD",))
            validate_live_send_settings(settings)

    def test_order_signal_timing_fields_handle_missing_and_invalid_values(self) -> None:
        complete = live_module._order_signal_timing_fields(
            _pending(
                placed_time_utc="2026-01-01T05:00:00+00:00",
                signal_time_utc="2026-01-01T00:00:00+00:00",
                timeframe="H4",
            )
        )
        self.assertEqual(complete["signal_closed_time_utc"], "2026-01-01T04:00:00+00:00")
        self.assertEqual(complete["latest_closed_candle_time_utc"], "2026-01-01T04:00:00+00:00")
        self.assertEqual(complete["placement_lag_seconds"], 3600)

        missing = live_module._order_signal_timing_fields(_pending(signal_time_utc=None))
        self.assertEqual(missing, {"placed_time_utc": "2026-01-01T04:00:00+00:00"})

        invalid_signal = live_module._order_signal_timing_fields(_pending(signal_time_utc="not-a-time"))
        self.assertEqual(invalid_signal, {"placed_time_utc": "2026-01-01T04:00:00+00:00"})

        invalid_placed = live_module._order_signal_timing_fields(
            _pending(placed_time_utc="not-a-time", signal_time_utc="2026-01-01T00:00:00+00:00")
        )
        self.assertIn("signal_closed_time_utc", invalid_placed)
        self.assertNotIn("placement_lag_seconds", invalid_placed)

    def test_state_round_trip_and_config_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            self.assertEqual(load_live_state(path), LiveExecutorState())
            state = LiveExecutorState(
                processed_signal_keys=("a",),
                order_checked_signal_keys=("b",),
                pending_orders=(_pending(),),
                active_positions=(_active(),),
                notified_event_keys=("n",),
                last_seen_close_ticket=1,
                last_seen_close_time_utc="2026-01-01T00:00:00+00:00",
                telegram_message_ids={"order:9001": 12},
            )
            save_live_state(path, state)
            loaded = load_live_state(path)
            self.assertEqual(loaded, state)
            self.assertEqual(loaded.pending_orders[0].to_dict()["order_ticket"], 9001)
            self.assertEqual(loaded.active_positions[0].to_dict()["position_id"], 7001)

            old_payload = state.to_dict()
            old_payload.pop("telegram_message_ids")
            path.write_text(json.dumps(old_payload), encoding="utf-8")
            self.assertEqual(load_live_state(path).telegram_message_ids, {})

            config = _config(tmpdir, max_lots_per_order=0.5, risk_buckets_pct={"H4": 0.25})
            safety = live_execution_safety_from_config(config)
            self.assertEqual(safety.max_open_risk_pct, 0.65)
            self.assertEqual(safety.max_lots_per_order, 0.5)
            self.assertEqual(safety.max_risk_pct_per_trade, 0.75)
            self.assertEqual(safety.order_comment_prefix, "LPFS")
            buckets = live_risk_buckets_from_config(config)
            self.assertAlmostEqual(buckets["H4"], 0.0125)
            self.assertAlmostEqual(buckets["W1"], 0.0375)
            with self.assertRaisesRegex(ValueError, "risk_bucket_scale"):
                live_risk_buckets_from_config(_config(tmpdir, risk_bucket_scale=0))
            with self.assertRaisesRegex(ValueError, "unsupported timeframe"):
                live_risk_buckets_from_config(_config(tmpdir, risk_buckets_pct={"M30": 0.10}))
            with self.assertRaisesRegex(ValueError, "risk_buckets_pct values"):
                live_risk_buckets_from_config(_config(tmpdir, risk_buckets_pct={"H4": 0.0}))

    def test_atomic_live_state_save_preserves_previous_file_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            original = LiveExecutorState(processed_signal_keys=("original",))
            updated = LiveExecutorState(processed_signal_keys=("updated",))
            save_live_state(path, original)

            with mock.patch.object(live_module.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    save_live_state(path, updated)

            self.assertEqual(load_live_state(path), original)

    def test_live_state_save_falls_back_when_replace_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            original = LiveExecutorState(processed_signal_keys=("original",))
            updated = LiveExecutorState(processed_signal_keys=("updated",))
            save_live_state(path, original)

            with (
                mock.patch.object(live_module.os, "replace", side_effect=PermissionError("access denied")),
                mock.patch.object(live_module.time, "sleep"),
            ):
                save_live_state(path, updated)

            self.assertEqual(load_live_state(path), updated)
            self.assertEqual(list(Path(tmpdir).glob(".state.json.*.tmp")), [])

    def test_live_state_save_fallback_ignores_temp_cleanup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            updated = LiveExecutorState(processed_signal_keys=("updated",))

            with (
                mock.patch.object(live_module.os, "replace", side_effect=PermissionError("access denied")),
                mock.patch.object(live_module.time, "sleep"),
                mock.patch.object(live_module.Path, "unlink", side_effect=OSError("locked temp")),
            ):
                save_live_state(path, updated)

            self.assertEqual(load_live_state(path), updated)

    def test_dynamic_spread_gate_and_broker_risk_sizing_inputs(self) -> None:
        spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.01)
        market = MT5MarketSnapshot(bid=1.1018, ask=1.1020)
        gate = dynamic_spread_gate(_setup(), spec, market, max_spread_risk_fraction=0.10)
        self.assertIsInstance(gate, DynamicSpreadGate)
        self.assertTrue(gate.passed)
        self.assertAlmostEqual(gate.spread_points or 0, 2.0)
        self.assertAlmostEqual(gate.spread_risk_fraction, 0.04)

        wide = dynamic_spread_gate(_setup(), spec, MT5MarketSnapshot(bid=1.1000, ask=1.1020), max_spread_risk_fraction=0.10)
        self.assertFalse(wide.passed)
        invalid = dynamic_spread_gate(_setup(entry=1.1, stop=1.1), spec, market, max_spread_risk_fraction=0.10)
        self.assertFalse(invalid.passed)
        no_points = dynamic_spread_gate(_setup(), MT5SymbolExecutionSpec("EURUSD", 5, 0.0, 10.0, 0.0001, 0.01, 1.0, 0.01), market, max_spread_risk_fraction=0.10)
        self.assertIsNone(no_points.spread_points)

        mt5 = FakeMT5()
        self.assertEqual(broker_money_risk_per_lot(mt5, _setup()), 500.0)
        self.assertEqual(mt5.last_calc_profit[0], mt5.ORDER_TYPE_BUY)
        self.assertEqual(broker_money_risk_per_lot(mt5, _short_setup()), 500.0)
        self.assertEqual(mt5.last_calc_profit[0], mt5.ORDER_TYPE_SELL)
        mt5.calc_profit_result = None
        with self.assertRaisesRegex(RuntimeError, "order_calc_profit failed"):
            broker_money_risk_per_lot(mt5, _setup())
        mt5.calc_profit_result = 0.0
        with self.assertRaisesRegex(RuntimeError, "non-positive risk"):
            broker_money_risk_per_lot(mt5, _setup())

    def test_missed_entry_check_blocks_late_live_order_placement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            clean = missed_entry_before_placement(
                mt5,
                _setup(),
                config=config,
                placed_time_utc="2026-01-01 04:01:00",
            )
            self.assertIsInstance(clean, MissedEntryCheck)
            self.assertTrue(clean.checked)
            self.assertFalse(clean.missed)
            self.assertEqual(clean.to_dict()["bars_checked"], 1)

            mt5.rates[-1]["high"] = 1.1990
            short_clean = missed_entry_before_placement(
                mt5,
                _short_setup(),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertTrue(short_clean.checked)
            self.assertFalse(short_clean.missed)
            mt5.rates[-1]["high"] = 1.2050
            short_missed = missed_entry_before_placement(
                mt5,
                _short_setup(),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertTrue(short_missed.missed)

            mt5.rates[-1]["low"] = 1.0
            missed = missed_entry_before_placement(
                mt5,
                _setup(),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertTrue(missed.checked)
            self.assertTrue(missed.missed)
            self.assertEqual(missed.first_touch_time_utc, "2026-01-01T04:00:00+00:00")

            price_wait = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState())
            self.assertEqual(price_wait.status, "blocked")
            self.assertEqual(mt5.order_check_requests, [])
            self.assertEqual(mt5.order_send_requests, [])
            self.assertNotIn(price_wait.signal_key, price_wait.state.processed_signal_keys)

            missing_meta = missed_entry_before_placement(
                mt5,
                _setup(metadata={"fs_signal_time_utc": None}),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertFalse(missing_meta.checked)

            mt5.rates = None
            no_rates = missed_entry_before_placement(
                mt5,
                _setup(),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertFalse(no_rates.checked)

            no_rates_rejected = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "no_rates.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(no_rates_rejected.status, "rejected")
            self.assertEqual(mt5.order_check_requests, [])

            mt5.rates = []
            empty_rates = missed_entry_before_placement(
                mt5,
                _setup(),
                config=config,
                placed_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertFalse(empty_rates.checked)

    def test_market_recovery_check_requires_better_price_clear_path_and_tight_spread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.01)
            missed = MissedEntryCheck(
                checked=True,
                missed=True,
                bars_checked=1,
                first_touch_time_utc="2026-01-01T04:00:00+00:00",
                first_touch_high=1.1004,
                first_touch_low=1.0996,
            )
            mt5.rates = [
                {**mt5.rates[0], "high": 1.1000, "low": 1.0990},
                {**mt5.rates[1], "high": 1.1004, "low": 1.0996},
            ]
            market = MT5MarketSnapshot(bid=1.0997, ask=1.0998, time_utc="2026-01-01T04:01:00Z")
            check = market_recovery_check(mt5, _setup(), config=config, market=market, missed_entry=missed, symbol_spec=spec)
            self.assertIsInstance(check, MarketRecoveryCheck)
            self.assertTrue(check.recoverable)
            self.assertEqual(check.status, "market_recovery_ready")
            self.assertAlmostEqual(check.recalculated_take_profit or 0.0, 1.1046)
            self.assertLess(check.spread_risk_fraction or 1.0, 0.10)

            worse_long = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.1001, ask=1.1002, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=missed,
                symbol_spec=spec,
            )
            self.assertFalse(worse_long.recoverable)
            self.assertEqual(worse_long.status, "market_recovery_not_better")

            mt5.rates[-1]["low"] = 1.0949
            stop_touched = market_recovery_check(mt5, _setup(), config=config, market=market, missed_entry=missed, symbol_spec=spec)
            self.assertFalse(stop_touched.recoverable)
            self.assertEqual(stop_touched.status, "market_recovery_stop_touched")
            mt5.rates[-1]["low"] = 1.0996
            mt5.rates[-1]["high"] = 1.1051
            target_touched = market_recovery_check(mt5, _setup(), config=config, market=market, missed_entry=missed, symbol_spec=spec)
            self.assertFalse(target_touched.recoverable)
            self.assertEqual(target_touched.status, "market_recovery_target_touched")

            mt5.rates = [
                {**mt5.rates[0], "high": 1.1000, "low": 1.0990},
                {
                    "time": int(pd.Timestamp("2026-01-01T04:00:00Z").timestamp()),
                    "open": 1.1020,
                    "high": 1.1051,
                    "low": 1.1010,
                    "close": 1.1040,
                    "tick_volume": 10,
                    "spread": 2,
                },
                {
                    "time": int(pd.Timestamp("2026-01-01T08:00:00Z").timestamp()),
                    "open": 1.1003,
                    "high": 1.1004,
                    "low": 1.0996,
                    "close": 1.1001,
                    "tick_volume": 10,
                    "spread": 2,
                },
            ]
            later_touch = MissedEntryCheck(
                checked=True,
                missed=True,
                bars_checked=2,
                first_touch_time_utc="2026-01-01T08:00:00+00:00",
                first_touch_high=1.1004,
                first_touch_low=1.0996,
            )
            pre_touch_target = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.0997, ask=1.0998, time_utc="2026-01-01T08:01:00Z"),
                missed_entry=later_touch,
                symbol_spec=spec,
            )
            self.assertTrue(pre_touch_target.recoverable)
            self.assertEqual(pre_touch_target.status, "market_recovery_ready")

            mt5.rates = [
                {
                    "time": int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()),
                    "open": 1.1000,
                    "high": 1.1000,
                    "low": 1.0990,
                    "close": 1.0995,
                    "tick_volume": 10,
                    "spread": 2,
                },
                {
                    "time": int(pd.Timestamp("2026-01-01T04:00:00Z").timestamp()),
                    "open": 1.1003,
                    "high": 1.1004,
                    "low": 1.0996,
                    "close": 1.1001,
                    "tick_volume": 10,
                    "spread": 2,
                },
            ]
            mt5.rates[-1]["high"] = 1.1004
            wide = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.0988, ask=1.0998, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=missed,
                symbol_spec=spec,
            )
            self.assertFalse(wide.recoverable)
            self.assertEqual(wide.status, "market_recovery_spread_too_wide")
            self.assertGreater(wide.spread_risk_fraction or 0.0, 0.10)

            short_missed = MissedEntryCheck(
                checked=True,
                missed=True,
                bars_checked=1,
                first_touch_time_utc="2026-01-01T04:00:00+00:00",
                first_touch_high=1.2005,
                first_touch_low=1.1990,
            )
            mt5.rates = [
                {**mt5.rates[0], "high": 1.1990, "low": 1.1980},
                {**mt5.rates[1], "high": 1.2005, "low": 1.1990},
            ]
            short_check = market_recovery_check(
                mt5,
                _short_setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.2002, ask=1.2003, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=short_missed,
                symbol_spec=spec,
            )
            self.assertTrue(short_check.recoverable)
            self.assertAlmostEqual(short_check.recalculated_take_profit or 0.0, 1.1904)
            short_worse = market_recovery_check(
                mt5,
                _short_setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.1998, ask=1.1999, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=short_missed,
                symbol_spec=spec,
            )
            self.assertFalse(short_worse.recoverable)
            self.assertEqual(short_worse.status, "market_recovery_not_better")

    def test_market_recovery_check_rejects_invalid_stop_and_unavailable_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.01)
            missed = MissedEntryCheck(checked=True, missed=True, first_touch_time_utc="2026-01-01T04:00:00+00:00")

            invalid_price = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.0997, ask=float("nan"), time_utc="2026-01-01T04:01:00Z"),
                missed_entry=missed,
                symbol_spec=spec,
            )
            self.assertEqual(invalid_price.status, "market_recovery_invalid_price")

            invalid_stop = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.0947, ask=1.0948, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=missed,
                symbol_spec=spec,
            )
            self.assertEqual(invalid_stop.status, "market_recovery_invalid_stop_distance")

            mt5.rates = None
            path_unavailable = market_recovery_check(
                mt5,
                _setup(),
                config=config,
                market=MT5MarketSnapshot(bid=1.0997, ask=1.0998, time_utc="2026-01-01T04:01:00Z"),
                missed_entry=missed,
                symbol_spec=spec,
            )
            self.assertFalse(path_unavailable.checked)
            self.assertEqual(path_unavailable.status, "market_recovery_path_unavailable")

            mt5.rates = []
            empty_path = live_module._market_recovery_path_block(
                mt5,
                _setup(),
                config=config,
                until_time_utc="2026-01-01T04:01:00Z",
            )
            self.assertEqual(empty_path["status"], "path_unavailable")

            mt5.rates = [
                {
                    "time": int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()),
                    "open": 1.1,
                    "high": 1.1,
                    "low": 1.099,
                    "close": 1.0995,
                    "tick_volume": 10,
                    "spread": 2,
                }
            ]
            clear_path = live_module._market_recovery_path_block(
                mt5,
                _setup(),
                config=config,
                until_time_utc="2026-01-01T00:00:00Z",
            )
            self.assertEqual(clear_path["status"], "clear")
            clear_after_first_touch_filter = live_module._market_recovery_path_block(
                mt5,
                _setup(),
                config=config,
                until_time_utc="2026-01-01T00:00:00Z",
                from_time_utc="2026-01-01T04:00:00Z",
            )
            self.assertEqual(clear_after_first_touch_filter["status"], "clear")

    def test_market_recovery_intent_rejects_safety_edges(self) -> None:
        def ready_check(**overrides) -> MarketRecoveryCheck:
            values = {
                "checked": True,
                "recoverable": True,
                "status": "market_recovery_ready",
                "original_entry": 1.1,
                "fill_price": 1.0998,
                "stop_loss": 1.095,
                "original_take_profit": 1.105,
                "recalculated_take_profit": 1.1046,
                "spread_risk_fraction": 0.04,
                "max_spread_risk_fraction": 0.10,
            }
            values.update(overrides)
            return MarketRecoveryCheck(**values)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.01)
            account = SimpleNamespace(equity=100_000.0)

            _, _, missing_price = live_module._build_market_recovery_intent(
                mt5,
                _setup(),
                config=config,
                state=LiveExecutorState(),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(fill_price=None),
            )
            self.assertEqual(missing_price.status, "market_recovery_missing_price")

            mt5.calc_profit_result = None
            _, _, invalid_symbol = live_module._build_market_recovery_intent(
                mt5,
                _setup(),
                config=config,
                state=LiveExecutorState(),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(invalid_symbol.status, "market_recovery_invalid_symbol_value")
            mt5.calc_profit_result = -500.0

            _, _, missing_bucket = live_module._build_market_recovery_intent(
                mt5,
                _setup(timeframe="M15"),
                config=config,
                state=LiveExecutorState(),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(missing_bucket.status, "missing_risk_bucket")

            _, _, risk_limit = live_module._build_market_recovery_intent(
                mt5,
                _setup(),
                config=_config(tmpdir, risk_bucket_scale=10.0, journal_path=str(Path(tmpdir) / "risk.jsonl")),
                state=LiveExecutorState(),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(risk_limit.status, "market_recovery_risk_pct_limit")

            bad_spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.0)
            _, _, volume_error = live_module._build_market_recovery_intent(
                mt5,
                _setup(),
                config=config,
                state=LiveExecutorState(),
                account=account,
                symbol_spec=bad_spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(volume_error.status, "market_recovery_invalid_volume_spec")

            volume_spec = live_module._market_recovery_sized_volume(
                account=account,
                symbol_spec=bad_spec,
                limits=ExecutionSafetyLimits(),
                target_risk_pct=0.2,
                risk_per_lot=500.0,
            )
            self.assertEqual(volume_spec["error"], "market_recovery_invalid_volume_spec")

            invalid_risk = live_module._market_recovery_sized_volume(
                account=account,
                symbol_spec=spec,
                limits=ExecutionSafetyLimits(),
                target_risk_pct=0.2,
                risk_per_lot=0.0,
            )
            self.assertEqual(invalid_risk["error"], "market_recovery_invalid_symbol_value")

            invalid_equity = live_module._market_recovery_sized_volume(
                account=SimpleNamespace(equity=0.0),
                symbol_spec=spec,
                limits=ExecutionSafetyLimits(),
                target_risk_pct=0.2,
                risk_per_lot=500.0,
            )
            self.assertEqual(invalid_equity["error"], "market_recovery_invalid_account_equity")

            capped = live_module._market_recovery_sized_volume(
                account=account,
                symbol_spec=spec,
                limits=ExecutionSafetyLimits(max_lots_per_order=0.1),
                target_risk_pct=0.2,
                risk_per_lot=500.0,
            )
            self.assertEqual(capped["volume"], 0.1)

            below_min = live_module._market_recovery_sized_volume(
                account=SimpleNamespace(equity=1_000.0),
                symbol_spec=spec,
                limits=ExecutionSafetyLimits(),
                target_risk_pct=0.01,
                risk_per_lot=100_000.0,
            )
            self.assertEqual(below_min["error"], "market_recovery_volume_below_min")

            _, _, max_open_risk = live_module._build_market_recovery_intent(
                mt5,
                _setup(),
                config=config,
                state=LiveExecutorState(active_positions=(_active(actual_risk_pct=5.9),)),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(max_open_risk.status, "market_recovery_max_open_risk")

            _, _, expiration_failed = live_module._build_market_recovery_intent(
                mt5,
                _setup(metadata={"fs_signal_time_utc": None}),
                config=config,
                state=LiveExecutorState(),
                account=account,
                symbol_spec=spec,
                recovery_check=ready_check(),
            )
            self.assertEqual(expiration_failed.status, "market_recovery_expiration_failed")

    def test_send_and_cancel_pending_order_outcomes(self) -> None:
        mt5 = FakeMT5()
        intent = MT5OrderIntent(
            signal_key="lpfs:EURUSD:H4:10:long",
            symbol="EURUSD",
            timeframe="H4",
            side="long",
            order_type="BUY_LIMIT",
            volume=0.02,
            entry_price=1.1,
            stop_loss=1.095,
            take_profit=1.105,
            target_risk_pct=0.01,
            actual_risk_pct=0.01,
            expiration_time_utc=pd.Timestamp("2026-01-02T04:00:00Z"),
            magic=131500,
            comment="LPFS H4 L 10",
            setup_id="setup",
        )

        sent = send_pending_order(mt5, intent)
        self.assertTrue(sent.sent)
        self.assertEqual(sent.order_ticket, 9001)
        self.assertEqual(mt5.order_send_requests[0]["action"], mt5.TRADE_ACTION_PENDING)

        mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="done", order=0, deal=0)
        no_ticket = send_pending_order(mt5, intent)
        self.assertFalse(no_ticket.sent)
        self.assertIsNone(no_ticket.order_ticket)
        mt5.order_send_result = SimpleNamespace(retcode=123, comment="bad", order=9002, deal=0)
        rejected = send_pending_order(mt5, intent)
        self.assertFalse(rejected.sent)
        mt5.order_send_result = None
        none_result = send_pending_order(mt5, intent)
        self.assertFalse(none_result.sent)
        self.assertEqual(none_result.comment, "order_send returned None")

        mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="removed", order=0, deal=0)
        cancelled = cancel_pending_order(mt5, _pending())
        self.assertTrue(cancelled.sent)
        self.assertEqual(mt5.order_send_requests[-1]["action"], mt5.TRADE_ACTION_REMOVE)

        market_intent = MT5OrderIntent(
            signal_key="lpfs:EURUSD:H4:10:long",
            symbol="EURUSD",
            timeframe="H4",
            side="long",
            order_type="BUY",
            volume=0.02,
            entry_price=1.0998,
            stop_loss=1.095,
            take_profit=1.1046,
            target_risk_pct=0.01,
            actual_risk_pct=0.01,
            expiration_time_utc=pd.Timestamp("2026-01-12T04:00:00Z"),
            magic=131500,
            comment="LPFS H4 L 10",
            setup_id="setup",
        )
        mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="market done", order=9101, deal=9201)
        market_check = run_market_order_check(mt5, market_intent, deviation_points=0)
        self.assertTrue(market_check.passed)
        self.assertEqual(market_check.request["action"], mt5.TRADE_ACTION_DEAL)
        self.assertEqual(market_check.request["type_filling"], mt5.ORDER_FILLING_IOC)
        sent_market = send_market_recovery_order(mt5, market_intent, deviation_points=0)
        self.assertTrue(sent_market.sent)
        self.assertEqual(sent_market.deal_ticket, 9201)
        self.assertEqual(mt5.order_send_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)
        self.assertEqual(mt5.order_send_requests[-1]["type_filling"], mt5.ORDER_FILLING_IOC)

        mt5.order_check_result = [
            SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode"),
            SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="check ok"),
        ]
        recovered_check = run_market_order_check(mt5, market_intent, deviation_points=0)
        self.assertTrue(recovered_check.passed)
        self.assertEqual(
            [request["type_filling"] for request in mt5.order_check_requests[-2:]],
            [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK],
        )
        sent_with_checked_mode = send_market_recovery_order(
            mt5,
            market_intent,
            deviation_points=0,
            checked_request=recovered_check.request,
        )
        self.assertTrue(sent_with_checked_mode.sent)
        self.assertEqual(mt5.order_send_requests[-1]["type_filling"], mt5.ORDER_FILLING_FOK)

        mt5.order_check_result = [
            SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode"),
            SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode"),
            SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode"),
        ]
        all_modes_failed = run_market_order_check(mt5, market_intent, deviation_points=0)
        self.assertFalse(all_modes_failed.passed)
        self.assertEqual(all_modes_failed.retcode, mt5.TRADE_RETCODE_INVALID_FILL)
        self.assertEqual(all_modes_failed.request["type_filling"], mt5.ORDER_FILLING_RETURN)

        malformed_mt5 = FakeMT5()
        malformed_mt5.info.filling_mode = "not-an-int"
        malformed_modes = live_module._market_order_filling_candidates(malformed_mt5, "EURUSD")
        self.assertEqual(malformed_modes, [malformed_mt5.ORDER_FILLING_IOC, malformed_mt5.ORDER_FILLING_FOK, malformed_mt5.ORDER_FILLING_RETURN])
        self.assertEqual(live_module._dedupe_filling_modes([None, "bad", 1, 1, 2]), [1, 2])
        malformed_retcode = OrderCheckOutcome(
            passed=False,
            request={},
            retcode="not-an-int",
            comment="invalid fill",
        )
        self.assertTrue(live_module._unsupported_filling_mode(malformed_mt5, malformed_retcode))

        with self.assertRaisesRegex(ValueError, "pending order intents"):
            build_order_check_request(mt5, market_intent)
        with self.assertRaisesRegex(ValueError, "Pending order type expected"):
            live_module._mt5_pending_order_type(mt5, market_intent)
        minimal_mt5 = SimpleNamespace(
            TRADE_ACTION_DEAL=mt5.TRADE_ACTION_DEAL,
            ORDER_TYPE_BUY=mt5.ORDER_TYPE_BUY,
            ORDER_TYPE_SELL=mt5.ORDER_TYPE_SELL,
        )
        minimal_request = live_module.build_market_order_request(minimal_mt5, market_intent)
        self.assertNotIn("type_filling", minimal_request)

        mt5.order_send_result = SimpleNamespace(retcode=999, comment="bad market", order=0, deal=0)
        rejected_market = send_market_recovery_order(mt5, market_intent, deviation_points=0)
        self.assertFalse(rejected_market.sent)

    def test_pending_expiry_counts_actual_bars_across_weekend_gaps_for_all_timeframes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            cases = {
                "H4": (
                    "2026-05-01T00:00:00Z",
                    [
                        "2026-05-01T00:00:00Z",
                        "2026-05-01T04:00:00Z",
                        "2026-05-01T08:00:00Z",
                        "2026-05-01T12:00:00Z",
                        "2026-05-01T16:00:00Z",
                        "2026-05-01T20:00:00Z",
                        "2026-05-04T00:00:00Z",
                    ],
                    "2026-05-04T04:00:00Z",
                ),
                "H8": (
                    "2026-05-01T00:00:00Z",
                    [
                        "2026-05-01T00:00:00Z",
                        "2026-05-01T08:00:00Z",
                        "2026-05-01T16:00:00Z",
                        "2026-05-04T00:00:00Z",
                        "2026-05-04T08:00:00Z",
                        "2026-05-04T16:00:00Z",
                        "2026-05-05T00:00:00Z",
                    ],
                    "2026-05-05T08:00:00Z",
                ),
                "H12": (
                    "2026-05-01T00:00:00Z",
                    [
                        "2026-05-01T00:00:00Z",
                        "2026-05-01T12:00:00Z",
                        "2026-05-04T00:00:00Z",
                        "2026-05-04T12:00:00Z",
                        "2026-05-05T00:00:00Z",
                        "2026-05-05T12:00:00Z",
                        "2026-05-06T00:00:00Z",
                    ],
                    "2026-05-06T12:00:00Z",
                ),
                "D1": (
                    "2026-05-01T00:00:00Z",
                    [
                        "2026-05-01T00:00:00Z",
                        "2026-05-04T00:00:00Z",
                        "2026-05-05T00:00:00Z",
                        "2026-05-06T00:00:00Z",
                        "2026-05-07T00:00:00Z",
                        "2026-05-08T00:00:00Z",
                        "2026-05-11T00:00:00Z",
                    ],
                    "2026-05-12T00:00:00Z",
                ),
                "W1": (
                    "2026-01-02T00:00:00Z",
                    [
                        "2026-01-02T00:00:00Z",
                        "2026-01-09T00:00:00Z",
                        "2026-01-16T00:00:00Z",
                        "2026-01-23T00:00:00Z",
                        "2026-01-30T00:00:00Z",
                        "2026-02-06T00:00:00Z",
                        "2026-02-13T00:00:00Z",
                    ],
                    "2026-02-20T00:00:00Z",
                ),
            }

            for timeframe, (signal_time, valid_window_times, first_expired_time) in cases.items():
                pending = _pending(
                    timeframe=timeframe,
                    signal_key=f"lpfs:EURUSD:{timeframe}:10:long:c:{signal_time}",
                    signal_time_utc=signal_time,
                )
                mt5.rates = _rates_from_times(valid_window_times)
                valid = pending_order_bar_expiry_check(mt5, pending, config)
                self.assertTrue(valid.checked, timeframe)
                self.assertFalse(valid.expired, timeframe)
                self.assertEqual(valid.bars_after_signal, 6)

                mt5.rates = _rates_from_times([*valid_window_times, first_expired_time])
                expired = pending_order_bar_expiry_check(mt5, pending, config)
                self.assertTrue(expired.checked, timeframe)
                self.assertTrue(expired.expired, timeframe)
                self.assertEqual(expired.bars_after_signal, 7)
                self.assertEqual(expired.first_expired_bar_time_utc, pd.Timestamp(first_expired_time).isoformat())

    def test_pending_bar_expiry_edge_paths_are_fail_closed_or_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()

            missing_setup_time = live_module.setup_bar_expiry_check(
                mt5,
                _setup(metadata={"fs_signal_time_utc": None}),
                config,
            )
            self.assertFalse(missing_setup_time.checked)
            self.assertIn("fs_signal_time_utc", missing_setup_time.detail)

            missing_pending_time = pending_order_bar_expiry_check(
                mt5,
                _pending(signal_key="manual", signal_time_utc=None, expiration_time_utc="bad"),
                config,
            )
            self.assertFalse(missing_pending_time.checked)
            self.assertEqual(missing_pending_time.detail, "missing signal_time_utc")

            mt5.rates = None
            fetch_failed = pending_order_bar_expiry_check(mt5, _pending(), config)
            self.assertFalse(fetch_failed.checked)
            self.assertIn("copy_rates_from_pos failed", fetch_failed.detail)

            mt5.rates = []
            empty = pending_order_bar_expiry_check(mt5, _pending(), config)
            self.assertFalse(empty.checked)
            self.assertIn("no rows", empty.detail)

            zero_wait = live_module.setup_bar_expiry_check(mt5, _setup(), _config(tmpdir, max_entry_wait_bars=0))
            self.assertFalse(zero_wait.checked)
            self.assertIn("max_entry_wait_bars", zero_wait.detail)

            legacy_key_pending = _pending(
                signal_time_utc=None,
                signal_key="lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
            )
            mt5.rates = _rates_from_times(["2026-01-01T00:00:00Z", "2026-01-01T04:00:00Z"])
            parsed = pending_order_bar_expiry_check(mt5, legacy_key_pending, config)
            self.assertTrue(parsed.checked)
            self.assertEqual(parsed.signal_time_utc, "2026-01-01T00:00:00+00:00")

            legacy_expiry_pending = _pending(
                signal_time_utc=None,
                signal_key="manual",
                expiration_time_utc="2026-01-02T04:00:00+00:00",
                broker_backstop_expiration_time_utc=None,
            )
            inferred = pending_order_bar_expiry_check(mt5, legacy_expiry_pending, config)
            self.assertTrue(inferred.checked)
            self.assertEqual(inferred.signal_time_utc, "2026-01-01T00:00:00+00:00")
            self.assertFalse(live_module._broker_backstop_elapsed(legacy_expiry_pending))
            self.assertTrue(
                live_module._broker_backstop_elapsed(
                    _pending(broker_backstop_expiration_time_utc="2000-01-01T00:00:00+00:00")
                )
            )

            event = live_module._pending_cancelled_event(
                _pending(),
                live_module.LiveOrderSendOutcome(sent=True, request={}, retcode=0, comment="removed"),
                expired=False,
            )
            self.assertEqual(event.kind, "pending_cancelled")
            self.assertNotIn("bars_after_signal", event.fields)

    def test_process_live_setup_rejects_unavailable_or_expired_bar_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            unchecked = live_module.PendingBarExpiryCheck(checked=False, expired=False, detail="rates unavailable")
            with mock.patch.object(live_module, "setup_bar_expiry_check", return_value=unchecked):
                unavailable = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState())
            self.assertEqual(unavailable.status, "rejected")

            expired_check = live_module.PendingBarExpiryCheck(
                checked=True,
                expired=True,
                bars_after_signal=7,
                max_entry_wait_bars=6,
                signal_time_utc="2026-01-01T00:00:00+00:00",
                first_expired_bar_time_utc="2026-01-02T04:00:00+00:00",
            )
            with mock.patch.object(live_module, "setup_bar_expiry_check", return_value=expired_check):
                expired = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState())
            self.assertEqual(expired.status, "rejected")

    def test_process_live_setup_sends_and_handles_rejection_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            notifier_client = FakeNotifierClient()
            notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False), notifier_client)
            mt5 = FakeMT5()

            result = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState(), notifier=notifier)
            self.assertEqual(result.status, "order_sent")
            self.assertEqual(result.order_send.order_ticket if result.order_send else None, 9001)
            self.assertEqual(result.order_send.to_dict()["order_ticket"] if result.order_send else None, 9001)
            self.assertEqual(len(result.state.pending_orders), 1)
            self.assertIn("LPFS LIVE | ORDER PLACED", notifier_client.payloads[0]["text"])
            self.assertIn("EURUSD H4 LONG | BUY LIMIT #9001", notifier_client.payloads[0]["text"])
            self.assertIn("Signal: closed 2026-01-01 12:00 SGT | Placed", notifier_client.payloads[0]["text"])
            self.assertIn("Lag", notifier_client.payloads[0]["text"])
            self.assertIn("Why: Closed-candle LP + Force Strike setup", notifier_client.payloads[0]["text"])
            self.assertNotIn("Why: Why:", notifier_client.payloads[0]["text"])
            self.assertEqual(result.state.telegram_message_ids["order:9001"], 1)
            self.assertAlmostEqual(result.state.pending_orders[0].volume, 0.02)
            self.assertEqual(result.state.pending_orders[0].price_digits, 5)
            loaded_state = load_live_state(config.state_path)
            self.assertEqual(len(loaded_state.pending_orders), 1)
            self.assertEqual(loaded_state.pending_orders[0].order_ticket, 9001)

            journal_row = json.loads(Path(config.journal_path).read_text(encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual(journal_row["notification_event"]["kind"], "order_sent")
            event_fields = journal_row["notification_event"]["fields"]
            self.assertEqual(event_fields["signal_closed_time_utc"], "2026-01-01T04:00:00+00:00")
            self.assertEqual(event_fields["latest_closed_candle_time_utc"], "2026-01-01T04:00:00+00:00")
            self.assertIn("placed_time_utc", event_fields)
            self.assertGreaterEqual(event_fields["placement_lag_seconds"], 0)
            self.assertEqual(journal_row["telegram_message_id"], 1)

            duplicate = process_trade_setup_live_send(mt5, _setup(), config=config, state=result.state)
            self.assertEqual(duplicate.status, "already_processed")

            wide = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, max_spread_risk_fraction=0.01, journal_path=str(Path(tmpdir) / "wide.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(wide.status, "blocked")
            self.assertEqual(wide.state.processed_signal_keys, ())
            self.assertIn("setup_blocked:", wide.state.notified_event_keys[0])
            self.assertFalse(mt5.order_check_requests[-1:] and mt5.order_check_requests[-1].get("comment") == "wide")

            retried_after_spread_improved = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "wide_retried.jsonl")),
                state=wide.state,
            )
            self.assertEqual(retried_after_spread_improved.status, "order_sent")

            mt5.rates[-1]["low"] = 1.1040
            rejected_decision = process_trade_setup_live_send(
                mt5,
                _setup(entry=1.1030, stop=1.0950, target=1.1100),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "decision.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(rejected_decision.status, "rejected")
            mt5.rates[-1]["low"] = 1.1005

            mt5.order_check_result = SimpleNamespace(retcode=123, comment="no")
            failed_check = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "check.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(failed_check.status, "order_check_failed")

            mt5_market_check = FakeMT5()
            mt5_market_check.order_check_result = SimpleNamespace(retcode=mt5_market_check.TRADE_RETCODE_MARKET_CLOSED, comment="Market closed")
            market_closed_check = process_trade_setup_live_send(
                mt5_market_check,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_closed_check.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(market_closed_check.status, "blocked")
            self.assertNotIn(market_closed_check.signal_key, market_closed_check.state.processed_signal_keys)
            self.assertIn(f"setup_blocked:{market_closed_check.signal_key}:market_closed", market_closed_check.state.notified_event_keys)

            mt5_market_check.order_check_result = SimpleNamespace(retcode=mt5_market_check.TRADE_RETCODE_DONE, comment="ok")
            mt5_market_check.order_send_result = SimpleNamespace(retcode=mt5_market_check.TRADE_RETCODE_PLACED, comment="placed", order=9003, deal=0)
            retried_after_market_open_check = process_trade_setup_live_send(
                mt5_market_check,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_closed_check_retried.jsonl")),
                state=market_closed_check.state,
            )
            self.assertEqual(retried_after_market_open_check.status, "order_sent")

            mt5.order_check_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="ok")
            mt5.tick = SimpleNamespace(bid=1.1000, ask=1.1020, time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000), time=0)
            final_spread = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "final_spread.jsonl")),
                state=LiveExecutorState(),
                market=MT5MarketSnapshot(bid=1.1018, ask=1.1020, time_utc="2026-01-01T04:00:00Z"),
            )
            self.assertEqual(final_spread.status, "blocked")
            self.assertNotIn(final_spread.signal_key, final_spread.state.processed_signal_keys)

            mt5.tick = SimpleNamespace(bid=1.1018, ask=1.1020, time_msc=int(pd.Timestamp("2026-01-01T04:03:00Z").timestamp() * 1000), time=0)
            mt5.order_send_result = SimpleNamespace(retcode=123, comment="send rejected", order=0, deal=0)
            rejected_send = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "send.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(rejected_send.status, "order_rejected")
            self.assertIn(rejected_send.signal_key, rejected_send.state.processed_signal_keys)

            mt5_market_send = FakeMT5()
            mt5_market_send.order_send_result = SimpleNamespace(retcode=123, comment="Market closed by broker", order=0, deal=0)
            market_closed_send = process_trade_setup_live_send(
                mt5_market_send,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_closed_send.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(market_closed_send.status, "blocked")
            self.assertNotIn(market_closed_send.signal_key, market_closed_send.state.processed_signal_keys)
            self.assertIn(f"setup_blocked:{market_closed_send.signal_key}:market_closed", market_closed_send.state.notified_event_keys)

            mt5_market_send.order_send_result = SimpleNamespace(retcode=mt5_market_send.TRADE_RETCODE_PLACED, comment="placed", order=9004, deal=0)
            retried_after_market_open_send = process_trade_setup_live_send(
                mt5_market_send,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_closed_send_retried.jsonl")),
                state=market_closed_send.state,
            )
            self.assertEqual(retried_after_market_open_send.status, "order_sent")

            mt5.order_send_result = SimpleNamespace(
                retcode=mt5.TRADE_RETCODE_CLIENT_DISABLES_AT,
                comment="AutoTrading disabled by client",
                order=0,
                deal=0,
            )
            operator_blocked = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "autotrading_disabled.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(operator_blocked.status, "blocked")
            self.assertNotIn(operator_blocked.signal_key, operator_blocked.state.processed_signal_keys)
            self.assertIn("setup_blocked:", operator_blocked.state.notified_event_keys[0])

            mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_PLACED, comment="placed", order=9002, deal=0)
            retried_after_operator_fix = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "autotrading_retried.jsonl")),
                state=operator_blocked.state,
            )
            self.assertEqual(retried_after_operator_fix.status, "order_sent")

    def test_process_live_setup_market_recovery_sends_market_order_and_tracks_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            notifier_client = FakeNotifierClient()
            notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False), notifier_client)
            mt5 = FakeMT5()
            mt5.rates[-1]["low"] = 1.0996
            mt5.rates[-1]["high"] = 1.1004
            mt5.tick = SimpleNamespace(
                bid=1.0997,
                ask=1.0998,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="market done", order=9101, deal=9201)

            recovered = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState(), notifier=notifier)

            self.assertEqual(recovered.status, "market_recovery_sent")
            self.assertEqual(mt5.order_check_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)
            self.assertEqual(mt5.order_send_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)
            self.assertEqual(mt5.order_send_requests[-1]["deviation"], 0)
            self.assertEqual(len(recovered.state.pending_orders), 0)
            self.assertEqual(len(recovered.state.active_positions), 1)
            self.assertIn(recovered.signal_key, recovered.state.processed_signal_keys)
            active = recovered.state.active_positions[0]
            self.assertEqual(active.position_id, 9201)
            self.assertAlmostEqual(active.entry_price, 1.0998)
            self.assertAlmostEqual(active.stop_loss, 1.095)
            self.assertAlmostEqual(active.take_profit, 1.1046)
            self.assertIn("LPFS LIVE | MARKET RECOVERY", notifier_client.payloads[0]["text"])
            self.assertIn("Original 1.10000 | Fill 1.09980", notifier_client.payloads[0]["text"])
            self.assertIn("Touched: 2026-01-01 12:00 SGT | H/L 1.10040/1.09960", notifier_client.payloads[0]["text"])

            rows = [json.loads(line) for line in Path(config.journal_path).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[-1]["event"], "market_recovery_sent")
            self.assertEqual(rows[-1]["notification_event"]["fields"]["deal_ticket"], 9201)
            loaded = load_live_state(config.state_path)
            self.assertEqual(len(loaded.active_positions), 1)

    def test_process_live_setup_market_recovery_blocks_and_rejects_edge_paths(self) -> None:
        def recoverable_mt5() -> FakeMT5:
            mt5 = FakeMT5()
            mt5.rates[-1]["low"] = 1.0996
            mt5.rates[-1]["high"] = 1.1004
            mt5.tick = SimpleNamespace(
                bid=1.0997,
                ask=1.0998,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="market done", order=9101, deal=9201)
            return mt5

        with tempfile.TemporaryDirectory() as tmpdir:
            disabled = process_trade_setup_live_send(
                recoverable_mt5(),
                _setup(),
                config=_config(tmpdir, market_recovery_mode="disabled", journal_path=str(Path(tmpdir) / "disabled.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(disabled.status, "rejected")
            self.assertIn(disabled.signal_key, disabled.state.processed_signal_keys)

            mt5 = recoverable_mt5()
            mt5.order_check_result = SimpleNamespace(retcode=123, comment="market check rejected")
            failed_check = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_check.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(failed_check.status, "order_check_failed")
            self.assertEqual(mt5.order_check_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)

            mt5 = recoverable_mt5()
            mt5.order_check_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_MARKET_CLOSED, comment="Market closed")
            market_closed_check = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_recovery_closed_check.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(market_closed_check.status, "blocked")
            self.assertNotIn(market_closed_check.signal_key, market_closed_check.state.processed_signal_keys)
            self.assertEqual(mt5.order_check_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)

            mt5 = recoverable_mt5()
            mt5.order_check_result = [
                SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_FILL, comment="Unsupported filling mode"),
                SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="ok"),
            ]
            recovered_after_fill_fallback = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_fill_fallback.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(recovered_after_fill_fallback.status, "market_recovery_sent")
            self.assertEqual(
                [request["type_filling"] for request in mt5.order_check_requests[-2:]],
                [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK],
            )
            self.assertEqual(mt5.order_send_requests[-1]["type_filling"], mt5.ORDER_FILLING_FOK)

            mt5 = recoverable_mt5()
            mt5.rates = None
            path_failed = live_module._process_market_recovery_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_path.jsonl")),
                state=LiveExecutorState(),
                account=mt5.account,
                symbol_spec=live_module.symbol_spec_from_mt5(mt5, "EURUSD"),
                missed_entry=MissedEntryCheck(checked=True, missed=True, first_touch_time_utc="2026-01-01T04:00:00+00:00"),
                bar_expiry=live_module.PendingBarExpiryCheck(checked=True, expired=False),
                notifier=None,
            )
            self.assertEqual(path_failed.status, "rejected")
            self.assertIn(path_failed.signal_key, path_failed.state.processed_signal_keys)

            mt5 = recoverable_mt5()
            mt5.rates[-1]["low"] = 1.0949
            stop_touched = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_stop_touched.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(stop_touched.status, "rejected")
            self.assertEqual(mt5.order_check_requests, [])
            self.assertIn(stop_touched.signal_key, stop_touched.state.processed_signal_keys)

            ready_check = MarketRecoveryCheck(
                checked=True,
                recoverable=True,
                status="market_recovery_ready",
                original_entry=1.1,
                fill_price=1.0998,
                stop_loss=1.095,
                original_take_profit=1.105,
                recalculated_take_profit=1.1046,
                spread_risk_fraction=0.04,
                max_spread_risk_fraction=0.10,
            )
            with mock.patch.object(live_module, "market_recovery_check", return_value=ready_check):
                with mock.patch.object(live_module, "_build_market_recovery_intent", return_value=(None, None, None)):
                    intent_failed = live_module._process_market_recovery_live_send(
                        recoverable_mt5(),
                        _setup(),
                        config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_intent.jsonl")),
                        state=LiveExecutorState(),
                        account=mt5.account,
                        symbol_spec=live_module.symbol_spec_from_mt5(recoverable_mt5(), "EURUSD"),
                        missed_entry=MissedEntryCheck(checked=True, missed=True, first_touch_time_utc="2026-01-01T04:00:00+00:00"),
                        bar_expiry=live_module.PendingBarExpiryCheck(checked=True, expired=False),
                        notifier=None,
                    )
            self.assertEqual(intent_failed.status, "rejected")

            mt5 = recoverable_mt5()
            mt5.order_send_result = SimpleNamespace(
                retcode=mt5.TRADE_RETCODE_CLIENT_DISABLES_AT,
                comment="AutoTrading disabled by client",
                order=0,
                deal=0,
            )
            operator_blocked = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_autotrading.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(operator_blocked.status, "blocked")
            self.assertNotIn(operator_blocked.signal_key, operator_blocked.state.processed_signal_keys)

            mt5 = recoverable_mt5()
            mt5.order_send_result = SimpleNamespace(
                retcode=mt5.TRADE_RETCODE_MARKET_CLOSED,
                comment="Market closed",
                order=0,
                deal=0,
            )
            market_closed_send = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_recovery_closed_send.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(market_closed_send.status, "blocked")
            self.assertNotIn(market_closed_send.signal_key, market_closed_send.state.processed_signal_keys)

            mt5 = recoverable_mt5()
            mt5.order_send_result = SimpleNamespace(retcode=123, comment="market rejected", order=0, deal=0)
            send_rejected = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_rejected.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(send_rejected.status, "order_rejected")
            self.assertIn(send_rejected.signal_key, send_rejected.state.processed_signal_keys)

            mt5 = recoverable_mt5()
            mt5.auto_create_market_position = False
            fallback = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(
                    tmpdir,
                    journal_path=str(Path(tmpdir) / "market_fallback.jsonl"),
                    state_path=str(Path(tmpdir) / "market_fallback_state.json"),
                ),
                state=LiveExecutorState(),
            )
            self.assertEqual(fallback.status, "market_recovery_sent")
            self.assertEqual(fallback.state.active_positions[0].position_id, 9101)

            mt5 = recoverable_mt5()
            mt5.tick = SimpleNamespace(
                bid=1.0988,
                ask=1.0998,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            spread_blocked = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "market_spread.jsonl")),
                state=LiveExecutorState(),
            )
            self.assertEqual(spread_blocked.status, "blocked")
            self.assertEqual(mt5.order_check_requests, [])
            self.assertNotIn(spread_blocked.signal_key, spread_blocked.state.processed_signal_keys)

            price_wait_config = _config(
                tmpdir,
                journal_path=str(Path(tmpdir) / "market_not_better.jsonl"),
                state_path=str(Path(tmpdir) / "market_not_better_state.json"),
            )
            mt5 = recoverable_mt5()
            mt5.tick = SimpleNamespace(
                bid=1.1001,
                ask=1.1002,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            price_blocked = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=price_wait_config,
                state=LiveExecutorState(),
            )
            self.assertEqual(price_blocked.status, "blocked")
            self.assertEqual(mt5.order_check_requests, [])
            self.assertEqual(mt5.order_send_requests, [])
            self.assertNotIn(price_blocked.signal_key, price_blocked.state.processed_signal_keys)
            self.assertIn(
                f"setup_blocked:{price_blocked.signal_key}:market_recovery_price",
                price_blocked.state.notified_event_keys,
            )

            mt5.tick = SimpleNamespace(
                bid=1.0997,
                ask=1.0998,
                time_msc=int(pd.Timestamp("2026-01-01T04:03:00Z").timestamp() * 1000),
                time=0,
            )
            recovered_after_wait = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=price_wait_config,
                state=price_blocked.state,
            )
            self.assertEqual(recovered_after_wait.status, "market_recovery_sent")
            self.assertIn(recovered_after_wait.signal_key, recovered_after_wait.state.processed_signal_keys)
            self.assertEqual(mt5.order_check_requests[-1]["action"], mt5.TRADE_ACTION_DEAL)

            short_mt5 = recoverable_mt5()
            short_mt5.rates = [
                {**short_mt5.rates[0], "high": 1.1990, "low": 1.1980},
                {**short_mt5.rates[1], "high": 1.2005, "low": 1.1990},
            ]
            short_mt5.tick = SimpleNamespace(
                bid=1.1998,
                ask=1.1999,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            short_blocked = process_trade_setup_live_send(
                short_mt5,
                _short_setup(),
                config=_config(
                    tmpdir,
                    journal_path=str(Path(tmpdir) / "market_short_not_better.jsonl"),
                    state_path=str(Path(tmpdir) / "market_short_not_better_state.json"),
                ),
                state=LiveExecutorState(),
            )
            self.assertEqual(short_blocked.status, "blocked")
            self.assertEqual(short_mt5.order_check_requests, [])
            self.assertEqual(short_mt5.order_send_requests, [])
            self.assertNotIn(short_blocked.signal_key, short_blocked.state.processed_signal_keys)

            expiry_wait_config = _config(
                tmpdir,
                journal_path=str(Path(tmpdir) / "market_not_better_expired.jsonl"),
                state_path=str(Path(tmpdir) / "market_not_better_expired_state.json"),
            )
            mt5 = recoverable_mt5()
            mt5.tick = SimpleNamespace(
                bid=1.1001,
                ask=1.1002,
                time_msc=int(pd.Timestamp("2026-01-01T04:02:00Z").timestamp() * 1000),
                time=0,
            )
            initially_waiting = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=expiry_wait_config,
                state=LiveExecutorState(),
            )
            self.assertEqual(initially_waiting.status, "blocked")
            expired_check = live_module.PendingBarExpiryCheck(
                checked=True,
                expired=True,
                bars_after_signal=7,
                max_entry_wait_bars=6,
                signal_time_utc="2026-01-01T00:00:00+00:00",
                first_expired_bar_time_utc="2026-01-02T04:00:00+00:00",
            )
            with mock.patch.object(live_module, "setup_bar_expiry_check", return_value=expired_check):
                expired = process_trade_setup_live_send(
                    recoverable_mt5(),
                    _setup(),
                    config=expiry_wait_config,
                    state=initially_waiting.state,
                )
            self.assertEqual(expired.status, "rejected")
            self.assertIn(expired.signal_key, expired.state.processed_signal_keys)

    def test_successful_order_send_persists_state_before_notification_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            with mock.patch.object(live_module, "_record_event_once", side_effect=RuntimeError("notification failed")):
                with self.assertRaisesRegex(RuntimeError, "notification failed"):
                    process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState())

            loaded = load_live_state(config.state_path)
            self.assertEqual(len(loaded.pending_orders), 1)
            self.assertEqual(loaded.pending_orders[0].order_ticket, 9001)
            self.assertIn(live_module.signal_key_for_setup(_setup()), loaded.processed_signal_keys)

    def test_process_live_setup_adopts_existing_broker_order_without_resending(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            mt5.orders = [
                SimpleNamespace(
                    ticket=7777,
                    symbol="EURUSD",
                    magic=131500,
                    type=mt5.ORDER_TYPE_BUY_LIMIT,
                    comment="LPFS H4 L 10",
                    volume_initial=0.02,
                    price_open=1.1,
                    sl=1.095,
                    tp=1.105,
                )
            ]
            notifier_client = FakeNotifierClient()
            notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False), notifier_client)

            adopted = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState(), notifier=notifier)

            self.assertEqual(adopted.status, "order_adopted")
            self.assertEqual(mt5.order_send_requests, [])
            self.assertEqual(adopted.state.pending_orders[0].order_ticket, 7777)
            self.assertIn("LPFS LIVE | ORDER ADOPTED", notifier_client.payloads[0]["text"])
            self.assertIn("no new order sent", notifier_client.payloads[0]["text"])
            row = json.loads(Path(config.journal_path).read_text(encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual(row["notification_event"]["kind"], "order_adopted")

            position_config = _config(
                tmpdir,
                journal_path=str(Path(tmpdir) / "adopt_position.jsonl"),
                state_path=str(Path(tmpdir) / "adopt_position_state.json"),
            )
            mt5.orders = []
            mt5.positions = [
                SimpleNamespace(
                    identifier=8888,
                    ticket=0,
                    symbol="EURUSD",
                    magic=131500,
                    type=mt5.ORDER_TYPE_BUY,
                    comment="LPFS H4 L 10",
                    volume=0.02,
                    price_open=1.1,
                    sl=1.095,
                    tp=1.105,
                    time_msc=int(pd.Timestamp("2026-01-01T04:30:00Z").timestamp() * 1000),
                    time=0,
                )
            ]
            mt5.order_send_requests.clear()
            adopted_position = process_trade_setup_live_send(
                mt5,
                _setup(),
                config=position_config,
                state=LiveExecutorState(),
            )
            self.assertEqual(adopted_position.status, "order_adopted")
            self.assertEqual(mt5.order_send_requests, [])
            self.assertEqual(adopted_position.state.active_positions[0].position_id, 8888)
            self.assertEqual(adopted_position.state.active_positions[0].order_ticket, 8888)

    def test_process_live_setup_does_not_adopt_mismatched_broker_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            mt5.orders = [
                SimpleNamespace(
                    ticket=7777,
                    symbol="EURUSD",
                    magic=131500,
                    type=mt5.ORDER_TYPE_BUY_LIMIT,
                    comment="LPFS H4 L 10",
                    volume_initial=0.02,
                    price_open=1.1,
                    sl=1.096,
                    tp=1.105,
                )
            ]

            result = process_trade_setup_live_send(mt5, _setup(), config=config, state=LiveExecutorState())

            self.assertEqual(result.status, "order_sent")
            self.assertEqual(len(mt5.order_send_requests), 1)
            self.assertEqual(result.state.pending_orders[0].order_ticket, 9001)

    def test_lifecycle_notifications_reply_to_order_thread_and_enrich_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            notifier_client = FakeNotifierClient()
            notifier = TelegramNotifier(TelegramConfig("token", "chat", dry_run=False), notifier_client)

            mt5.orders = []
            mt5.positions = [
                SimpleNamespace(
                    identifier=7001,
                    ticket=7001,
                    symbol="EURUSD",
                    magic=131500,
                    comment="LPFS H4 L 10",
                    volume=0.02,
                    price_open=1.1,
                    sl=1.095,
                    tp=1.105,
                    time_msc=int(pd.Timestamp("2026-01-01T04:30:00Z").timestamp() * 1000),
                    time=0,
                )
            ]
            filled = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(pending_orders=(_pending(),), telegram_message_ids={"order:9001": 44}),
                notifier=notifier,
            )
            self.assertEqual(filled.pending_orders, ())
            self.assertEqual(notifier_client.payloads[-1]["reply_to_message_id"], 44)
            self.assertIn("LPFS LIVE | ENTERED", notifier_client.payloads[-1]["text"])

            mt5.positions = []
            mt5.deals = [
                SimpleNamespace(
                    ticket=3001,
                    position_id=7001,
                    entry=mt5.DEAL_ENTRY_OUT,
                    reason=mt5.DEAL_REASON_TP,
                    time_msc=int(pd.Timestamp("2026-01-01T08:00:00Z").timestamp() * 1000),
                    price=1.105,
                    profit=10.0,
                    comment="[tp 1.105]",
                )
            ]
            closed = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(active_positions=(_active(),), telegram_message_ids={"order:9001": 44}),
                notifier=notifier,
            )
            self.assertEqual(closed.active_positions, ())
            self.assertEqual(notifier_client.payloads[-1]["reply_to_message_id"], 44)
            self.assertIn("LPFS LIVE | TAKE PROFIT", notifier_client.payloads[-1]["text"])

            mt5.deals = []
            mt5.history_orders = []
            cancelled = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(pending_orders=(_pending(order_ticket=9002),), telegram_message_ids={"order:9002": 55}),
                notifier=notifier,
            )
            self.assertEqual(cancelled.pending_orders, ())
            self.assertEqual(notifier_client.payloads[-1]["reply_to_message_id"], 55)
            self.assertIn("LPFS LIVE | CANCELLED", notifier_client.payloads[-1]["text"])

            rows = [json.loads(line) for line in Path(config.journal_path).read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all("notification_event" in row for row in rows))
            self.assertEqual(rows[0]["reply_to_message_id"], 44)
            self.assertEqual(rows[1]["notification_event"]["kind"], "take_profit_hit")
            self.assertEqual(rows[2]["reply_thread_key"], "order:9002")

    def test_reconcile_live_state_pending_and_active_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()

            mt5.orders = [SimpleNamespace(ticket=9001, magic=131500, symbol="EURUSD")]
            kept = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(),)))
            self.assertEqual(len(kept.pending_orders), 1)

            expired_order = _pending()
            mt5.rates = _rates_from_times(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T04:00:00Z",
                    "2026-01-01T08:00:00Z",
                    "2026-01-01T12:00:00Z",
                    "2026-01-01T16:00:00Z",
                    "2026-01-01T20:00:00Z",
                    "2026-01-02T00:00:00Z",
                    "2026-01-02T04:00:00Z",
                ]
            )
            mt5.order_send_result = SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="removed", order=0, deal=0)
            expired = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(expired_order,)))
            self.assertEqual(expired.pending_orders, ())
            self.assertEqual(mt5.order_send_requests[-1]["action"], mt5.TRADE_ACTION_REMOVE)

            mt5.order_send_result = SimpleNamespace(retcode=123, comment="remove failed", order=0, deal=0)
            still_tracked = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(expired_order,)))
            self.assertEqual(len(still_tracked.pending_orders), 1)

            mt5.orders = []
            mt5.positions = [
                SimpleNamespace(
                    identifier=7001,
                    ticket=7001,
                    symbol="EURUSD",
                    magic=131500,
                    comment="LPFS H4 L 10",
                    volume=0.02,
                    price_open=1.1,
                    sl=1.095,
                    tp=1.105,
                    time_msc=int(pd.Timestamp("2026-01-01T04:30:00Z").timestamp() * 1000),
                    time=0,
                )
            ]
            filled = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(),)))
            self.assertEqual(filled.pending_orders, ())
            self.assertEqual(len(filled.active_positions), 1)

            mt5.positions = [
                SimpleNamespace(identifier=1, ticket=1, symbol="GBPUSD", magic=131500, comment="LPFS H4 L 10", volume=0.02),
                SimpleNamespace(identifier=2, ticket=2, symbol="EURUSD", magic=999, comment="LPFS H4 L 10", volume=0.02),
                SimpleNamespace(identifier=3, ticket=3, symbol="EURUSD", magic=131500, comment="manual", volume=0.03),
                SimpleNamespace(
                    identifier=7002,
                    ticket=7002,
                    symbol="EURUSD",
                    magic=131500,
                    comment="manual",
                    volume=0.02,
                    price_open=1.1,
                    sl=1.095,
                    tp=1.105,
                    time=int(pd.Timestamp("2026-01-01T04:31:00Z").timestamp()),
                    time_msc=0,
                ),
            ]
            volume_only_not_matched = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9010),)))
            self.assertEqual(volume_only_not_matched.active_positions, ())

            mt5.history_orders = [SimpleNamespace(ticket=9010, magic=131500, symbol="EURUSD", position_id=7002)]
            history_linked = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9010),)))
            self.assertEqual(history_linked.active_positions[0].position_id, 7002)

            mt5.history_orders = [SimpleNamespace(ticket=9013, magic=131500, symbol="EURUSD", position_id=0, position_by_id=7002)]
            position_by_linked = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9013),)))
            self.assertEqual(position_by_linked.active_positions[0].position_id, 7002)

            mt5.history_orders = []
            mt5.deals = [SimpleNamespace(order=9011, position_id=0), SimpleNamespace(order=9011, position_id=7002)]
            deal_linked = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9011),)))
            self.assertEqual(deal_linked.active_positions[0].position_id, 7002)

            mt5.history_orders = [SimpleNamespace(ticket=9012, magic=131500, symbol="EURUSD", position_id=9999)]
            mt5.deals = []
            not_linked = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9012),)))
            self.assertEqual(not_linked.active_positions, ())

            mt5.positions = []
            mt5.history_orders = [SimpleNamespace(ticket=9002, magic=131500, symbol="EURUSD", comment="cancelled in mt5")]
            missing = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9002),)))
            self.assertEqual(missing.pending_orders, ())
            mt5.history_orders = [
                SimpleNamespace(ticket=9999, magic=131500, symbol="EURUSD", comment="wrong ticket"),
                SimpleNamespace(ticket=9003, magic=999, symbol="EURUSD", comment="wrong magic"),
                SimpleNamespace(ticket=9003, magic=131500, symbol="GBPUSD", comment="wrong symbol"),
            ]
            history_miss = reconcile_live_state(mt5, config=config, state=LiveExecutorState(pending_orders=(_pending(order_ticket=9003),)))
            self.assertEqual(history_miss.pending_orders, ())
            mt5.history_orders = []
            duplicate_notice = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(
                    pending_orders=(_pending(order_ticket=9002),),
                    notified_event_keys=("pending_cancelled:9002",),
                ),
            )
            self.assertEqual(duplicate_notice.notified_event_keys, ("pending_cancelled:9002",))

            active = _active()
            mt5.deals = [
                SimpleNamespace(
                    ticket=3001,
                    position_id=7001,
                    entry=mt5.DEAL_ENTRY_OUT,
                    reason=mt5.DEAL_REASON_TP,
                    time_msc=int(pd.Timestamp("2026-01-01T08:00:00Z").timestamp() * 1000),
                    price=1.105,
                    profit=10.0,
                    comment="[tp 1.105]",
                )
            ]
            closed = reconcile_live_state(mt5, config=config, state=LiveExecutorState(active_positions=(active,)))
            self.assertEqual(closed.active_positions, ())
            self.assertEqual(closed.last_seen_close_ticket, 3001)
            self.assertEqual(latest_close_for_position(mt5, active, config).to_dict()["ticket"], 3001)

            short_active = _active(side="short", entry_price=1.2, stop_loss=1.21, take_profit=1.19)
            mt5.deals = [
                SimpleNamespace(
                    ticket=3002,
                    position_id=7001,
                    entry=mt5.DEAL_ENTRY_OUT,
                    reason=mt5.DEAL_REASON_SL,
                    time_msc=int(pd.Timestamp("2026-01-01T08:30:00Z").timestamp() * 1000),
                    price=1.21,
                    profit=-10.0,
                    comment="[sl 1.21]",
                )
            ]
            short_closed = reconcile_live_state(mt5, config=config, state=LiveExecutorState(active_positions=(short_active,)))
            self.assertEqual(short_closed.active_positions, ())

            mt5.deals = []
            still_unknown = reconcile_live_state(mt5, config=config, state=LiveExecutorState(active_positions=(active,)))
            self.assertEqual(len(still_unknown.active_positions), 1)

            mt5.deals = [
                SimpleNamespace(
                    ticket=3000,
                    position_id=7001,
                    entry=mt5.DEAL_ENTRY_OUT,
                    reason=mt5.DEAL_REASON_SL,
                    time_msc=int(pd.Timestamp("2026-01-01T07:00:00Z").timestamp() * 1000),
                    price=1.095,
                    profit=-10.0,
                    comment="[sl 1.095]",
                )
            ]
            old = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(
                    active_positions=(active,),
                    last_seen_close_ticket=3001,
                    last_seen_close_time_utc="2026-01-01T08:00:00+00:00",
                ),
            )
            self.assertEqual(old.active_positions, ())

            mt5.deals = [
                SimpleNamespace(
                    ticket=3003,
                    position_id=7001,
                    entry=mt5.DEAL_ENTRY_OUT,
                    reason=0,
                    time_msc=int(pd.Timestamp("2026-01-01T08:00:00Z").timestamp() * 1000),
                    price=1.1,
                    profit=0.0,
                    comment="manual close",
                )
            ]
            equal_old = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(
                    active_positions=(active,),
                    last_seen_close_ticket=3003,
                    last_seen_close_time_utc="2026-01-01T08:00:00+00:00",
                ),
            )
            self.assertEqual(equal_old.active_positions, ())

            newer_than_last = reconcile_live_state(
                mt5,
                config=config,
                state=LiveExecutorState(
                    active_positions=(active,),
                    last_seen_close_ticket=1000,
                    last_seen_close_time_utc="2026-01-01T07:00:00+00:00",
                ),
            )
            self.assertEqual(newer_than_last.active_positions, ())

            close_payload = LiveCloseEvent(
                ticket=1,
                position_id=1,
                close_reason="manual",
                close_time_utc="2026-01-01T00:00:00+00:00",
                close_price=1.1,
                close_profit=0.0,
                close_comment="manual",
            ).to_dict()
            self.assertEqual(close_payload["close_reason"], "manual")
            manual_event = live_module._close_event(_active(), LiveCloseEvent(**close_payload))
            self.assertEqual(manual_event.kind, "position_closed")
            self.assertEqual(manual_event.fields["close_reason"], "manual")

    def test_reconciliation_helpers_filter_and_read_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            mt5.orders = None
            mt5.positions = None
            self.assertEqual(current_strategy_orders(mt5, config), ())
            self.assertEqual(current_strategy_positions(mt5, config), ())

            mt5.orders = [SimpleNamespace(ticket=1, magic=131500), SimpleNamespace(ticket=2, magic=999)]
            mt5.positions = [SimpleNamespace(ticket=3, magic=131500), SimpleNamespace(ticket=4, magic=999)]
            self.assertEqual([order.ticket for order in current_strategy_orders(mt5, config)], [1])
            self.assertEqual([position.ticket for position in current_strategy_positions(mt5, config)], [3])

            active = _active()
            mt5.direct_deals = [
                SimpleNamespace(ticket=1, position_id=7001, entry=0, reason=0, time_msc=1, price=1.1, profit=0, comment="open"),
                SimpleNamespace(ticket=2, position_id=7001, entry=mt5.DEAL_ENTRY_OUT, reason=mt5.DEAL_REASON_SL, time_msc=2, price=1.095, profit=-10, comment="[sl]"),
            ]
            close = latest_close_for_position(mt5, active, config)
            self.assertIsNotNone(close)
            assert close is not None
            self.assertEqual(close.close_reason, "sl")

            mt5.direct_deals = None
            mt5.direct_deals_type_error = True
            mt5.deals = [
                SimpleNamespace(ticket=3, position_id=7001, entry=mt5.DEAL_ENTRY_INOUT, reason=mt5.DEAL_REASON_TP, time=1, time_msc=0, price=1.105, profit=10, comment="take profit")
            ]
            fallback = latest_close_for_position(mt5, active, config)
            self.assertIsNotNone(fallback)
            assert fallback is not None
            self.assertEqual(fallback.close_reason, "tp")

            mt5.deals = [SimpleNamespace(ticket=4, position_id=9999, entry=mt5.DEAL_ENTRY_OUT, reason=0, time_msc=1, price=1, profit=0, comment="manual")]
            self.assertIsNone(latest_close_for_position(mt5, active, config))

            mt5.deals = None
            self.assertIsNone(latest_close_for_position(mt5, active, config))

            self.assertIsNone(
                live_module._matching_position_for_order(
                    mt5,
                    _pending(),
                    [SimpleNamespace(symbol="EURUSD", magic=999, comment="manual", volume=0.03)],
                    config,
                )
            )

            no_constant_mt5 = SimpleNamespace(
                TRADE_ACTION_PENDING=5,
                ORDER_TYPE_BUY_LIMIT=2,
                ORDER_TYPE_SELL_LIMIT=3,
                ORDER_TIME_SPECIFIED=2,
                ORDER_FILLING_RETURN=2,
                order_send=lambda request: SimpleNamespace(retcode=0, comment="placed", order=1, deal=0),
            )
            intent = MT5OrderIntent(
                signal_key="lpfs:EURUSD:H4:10:long",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                order_type="BUY_LIMIT",
                volume=0.01,
                entry_price=1.1,
                stop_loss=1.095,
                take_profit=1.105,
                target_risk_pct=0.01,
                actual_risk_pct=0.01,
                expiration_time_utc=pd.Timestamp("2026-01-02T04:00:00Z"),
                magic=131500,
                comment="LPFS H4 L 10",
                setup_id="setup",
            )
            self.assertTrue(send_pending_order(no_constant_mt5, intent).sent)
            remove_mt5 = SimpleNamespace(
                TRADE_ACTION_REMOVE=8,
                order_send=lambda request: SimpleNamespace(retcode=0, comment="removed"),
            )
            self.assertTrue(cancel_pending_order(remove_mt5, _pending()).sent)

    def test_broker_adoption_matchers_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()
            spec = MT5SymbolExecutionSpec("EURUSD", 5, 0.0001, 10.0, 0.0001, 0.01, 100.0, 0.01)
            intent = MT5OrderIntent(
                signal_key="lpfs:EURUSD:H4:10:long",
                symbol="EURUSD",
                timeframe="H4",
                side="long",
                order_type="BUY_LIMIT",
                volume=0.02,
                entry_price=1.1,
                stop_loss=1.095,
                take_profit=1.105,
                target_risk_pct=0.01,
                actual_risk_pct=0.01,
                expiration_time_utc=pd.Timestamp("2026-01-02T04:00:00Z"),
                magic=131500,
                comment="LPFS H4 L 10",
                setup_id="setup",
            )

            mt5.orders = [
                SimpleNamespace(ticket=1, symbol="GBPUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=2, symbol="EURUSD", magic=999, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=3, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_SELL_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=4, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="manual", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=5, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.03, price_open=1.1, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=6, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.101, sl=1.095, tp=1.105),
                SimpleNamespace(ticket=7, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.106),
                SimpleNamespace(ticket=8, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105),
            ]
            self.assertEqual(live_module._matching_broker_order_for_intent(mt5, intent, config, spec).ticket, 8)

            mt5.positions = [
                SimpleNamespace(identifier=1, symbol="GBPUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.02, sl=1.095, tp=1.105),
                SimpleNamespace(identifier=2, symbol="EURUSD", magic=999, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.02, sl=1.095, tp=1.105),
                SimpleNamespace(identifier=3, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_SELL, comment="LPFS H4 L 10", volume=0.02, sl=1.095, tp=1.105),
                SimpleNamespace(identifier=4, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="manual", volume=0.02, sl=1.095, tp=1.105),
                SimpleNamespace(identifier=5, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.03, sl=1.095, tp=1.105),
                SimpleNamespace(identifier=6, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.02, sl=1.096, tp=1.105),
                SimpleNamespace(identifier=7, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.02, sl=1.095, tp=1.106),
                SimpleNamespace(identifier=8, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY, comment="LPFS H4 L 10", volume=0.02, sl=1.095, tp=1.105),
            ]
            self.assertEqual(live_module._matching_broker_position_for_intent(mt5, intent, config, spec).identifier, 8)

            self.assertFalse(live_module._any_volume_matches(SimpleNamespace(volume_initial=None, volume_current="", volume=0.03), 0.02, spec))
            self.assertFalse(live_module._price_attr_matches(SimpleNamespace(price_open=None, price="", sl=1.096), ("price_open", "price", "sl"), 1.1, spec))

            mt5.orders = [SimpleNamespace(ticket=0, symbol="EURUSD", magic=131500, type=mt5.ORDER_TYPE_BUY_LIMIT, comment="LPFS H4 L 10", volume_initial=0.02, price_open=1.1, sl=1.095, tp=1.105)]
            self.assertIsNone(live_module._adopt_existing_broker_item(mt5, intent, config=config, state=LiveExecutorState(), symbol_spec=spec))

    def test_run_live_send_cycle_reconciles_processes_and_saves_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = _config(tmpdir)
            mt5 = FakeMT5()

            def provider(frame, symbol, timeframe, run_config):
                self.assertEqual((symbol, timeframe), ("EURUSD", "H4"))
                self.assertEqual(run_config.risk_bucket_scale, 0.05)
                return [_setup()]

            result = run_live_send_cycle(mt5, config=config, state=LiveExecutorState(), setup_provider=provider)
            self.assertEqual(result.frames_processed, 1)
            self.assertEqual(result.orders_sent, 1)
            self.assertEqual(result.setups_rejected, 0)
            self.assertEqual(result.setups_blocked, 0)
            self.assertTrue(Path(config.state_path).exists())

            skipped = run_live_send_cycle(
                mt5,
                config=_config(tmpdir, journal_path=str(Path(tmpdir) / "skip.jsonl"), state_path=str(Path(tmpdir) / "skip_state.json")),
                state=LiveExecutorState(),
                setup_provider=lambda frame, symbol, timeframe, run_config: [
                    SkippedTrade(
                        candidate_id="c",
                        symbol=symbol,
                        timeframe=timeframe,
                        side="bullish",
                        signal_index=1,
                        signal_time_utc=pd.Timestamp("2026-01-01T00:00:00Z"),
                        reason="skip",
                    )
                ],
            )
            self.assertEqual(skipped.orders_sent, 0)
            self.assertEqual(skipped.setups_rejected, 1)
            self.assertEqual(skipped.setups_blocked, 0)

            blocked = run_live_send_cycle(
                mt5,
                config=_config(
                    tmpdir,
                    max_spread_risk_fraction=0.01,
                    journal_path=str(Path(tmpdir) / "blocked.jsonl"),
                    state_path=str(Path(tmpdir) / "blocked_state.json"),
                ),
                state=LiveExecutorState(),
                setup_provider=lambda frame, symbol, timeframe, run_config: [_setup()],
            )
            self.assertEqual(blocked.orders_sent, 0)
            self.assertEqual(blocked.setups_rejected, 0)
            self.assertEqual(blocked.setups_blocked, 1)
            self.assertEqual(blocked.state.processed_signal_keys, ())


if __name__ == "__main__":
    unittest.main()
