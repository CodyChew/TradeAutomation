from __future__ import annotations

import sys
import unittest
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
    ExistingStrategyExposure,
    ExecutionSafetyLimits,
    MT5AccountSnapshot,
    MT5MarketSnapshot,
    MT5SymbolExecutionSpec,
    broker_backstop_expiration_time_utc,
    build_mt5_order_intent,
    money_risk_per_lot,
    pending_expiration_time_utc,
    risk_pct_for_timeframe,
    signal_key_for_setup,
    timeframe_delta,
)


def _setup(
    *,
    side: str = "long",
    symbol: str = "EURUSD",
    timeframe: str = "H4",
    entry: float = 1.1000,
    stop: float = 1.0950,
    target: float = 1.1050,
    metadata: dict | None = None,
    signal_index: int | None = 10,
) -> TradeSetup:
    return TradeSetup(
        setup_id=f"{symbol}_{timeframe}_{side}",
        side=side,  # type: ignore[arg-type]
        entry_index=11,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        symbol=symbol,
        timeframe=timeframe,
        signal_index=signal_index,
        metadata={
            "candidate_id": "lp_pivot_3__signal_zone_0p5_pullback__fs_structure__1r",
            "fs_signal_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"),
            **(metadata or {}),
        },
    )


def _short_setup(**kwargs) -> TradeSetup:
    defaults = {
        "side": "short",
        "entry": 1.2000,
        "stop": 1.2100,
        "target": 1.1900,
        "timeframe": "W1",
    }
    defaults.update(kwargs)
    return _setup(**defaults)


def _spec(**overrides) -> MT5SymbolExecutionSpec:
    values = {
        "symbol": "EURUSD",
        "digits": 5,
        "point": 0.0001,
        "trade_tick_value": 10.0,
        "trade_tick_size": 0.0001,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "trade_stops_level_points": 5,
        "trade_freeze_level_points": 0,
        "visible": True,
        "trade_allowed": True,
    }
    values.update(overrides)
    return MT5SymbolExecutionSpec(**values)


def _account(equity: float = 100_000.0) -> MT5AccountSnapshot:
    return MT5AccountSnapshot(equity=equity, currency="USD")


class ExecutionContractTests(unittest.TestCase):
    def test_v15_risk_buckets_and_pending_expiration_are_explicit(self) -> None:
        self.assertEqual(risk_pct_for_timeframe("h4"), 0.20)
        self.assertEqual(risk_pct_for_timeframe("H8"), 0.20)
        self.assertEqual(risk_pct_for_timeframe("H12"), 0.30)
        self.assertEqual(risk_pct_for_timeframe("D1"), 0.30)
        self.assertEqual(risk_pct_for_timeframe("W1"), 0.75)
        self.assertEqual(risk_pct_for_timeframe("M15", {"M15": 0.01}), 0.01)
        with self.assertRaisesRegex(ValueError, "No execution risk bucket"):
            risk_pct_for_timeframe("M15")

        self.assertEqual(timeframe_delta("H4"), pd.Timedelta(hours=4))
        self.assertEqual(timeframe_delta("H8"), pd.Timedelta(hours=8))
        self.assertEqual(timeframe_delta("H12"), pd.Timedelta(hours=12))
        self.assertEqual(timeframe_delta("D1"), pd.Timedelta(days=1))
        self.assertEqual(timeframe_delta("W1"), pd.Timedelta(days=7))
        with self.assertRaisesRegex(ValueError, "Unsupported execution timeframe"):
            timeframe_delta("M30")

        self.assertEqual(
            pending_expiration_time_utc(_setup(), max_entry_wait_bars=6),
            pd.Timestamp("2026-01-02T04:00:00Z"),
        )
        self.assertEqual(
            broker_backstop_expiration_time_utc(_setup(), max_entry_wait_bars=6),
            pd.Timestamp("2026-01-12T04:00:00Z"),
        )
        naive = _setup(metadata={"fs_signal_time_utc": "2026-01-01 00:00:00"})
        self.assertEqual(
            pending_expiration_time_utc(naive, max_entry_wait_bars=1),
            pd.Timestamp("2026-01-01T08:00:00Z"),
        )
        with self.assertRaisesRegex(ValueError, "max_entry_wait_bars"):
            pending_expiration_time_utc(_setup(), max_entry_wait_bars=0)
        with self.assertRaisesRegex(ValueError, "missing fs_signal_time_utc"):
            pending_expiration_time_utc(_setup(metadata={"fs_signal_time_utc": None}))
        with self.assertRaisesRegex(ValueError, "Unsupported execution timeframe"):
            broker_backstop_expiration_time_utc(_setup(timeframe="M30"))

    def test_ready_long_order_intent_uses_limit_order_and_v15_risk(self) -> None:
        decision = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020, time_utc=pd.Timestamp("2026-01-01T04:00:00Z")),
        )

        self.assertTrue(decision.ready)
        self.assertEqual(decision.status, "ready")
        self.assertIn("expiration", decision.checks)
        assert decision.intent is not None
        self.assertEqual(decision.intent.order_type, "BUY_LIMIT")
        self.assertEqual(decision.intent.volume, 0.4)
        self.assertAlmostEqual(decision.intent.actual_risk_pct, 0.20)
        self.assertEqual(decision.intent.target_risk_pct, 0.20)
        self.assertEqual(decision.intent.entry_price, 1.1)
        self.assertEqual(decision.intent.stop_loss, 1.095)
        self.assertEqual(decision.intent.take_profit, 1.105)
        self.assertEqual(decision.intent.magic, 131500)
        self.assertEqual(decision.intent.comment, "LPFS H4 L 10")
        self.assertIn("lpfs:EURUSD:H4:10:long", decision.intent.signal_key)
        self.assertEqual(decision.intent.to_dict()["expiration_time_utc"], "2026-01-12T04:00:00+00:00")
        self.assertEqual(decision.intent.to_dict()["signal_time_utc"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(decision.intent.to_dict()["max_entry_wait_bars"], 6)
        self.assertEqual(decision.intent.to_dict()["strategy_expiry_mode"], "bar_count")
        self.assertEqual(decision.intent.to_dict()["broker_backstop_expiration_time_utc"], "2026-01-12T04:00:00+00:00")
        self.assertEqual(decision.to_dict()["status"], "ready")

        ic_decision = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020, time_utc=pd.Timestamp("2026-01-01T04:00:00Z")),
            safety=ExecutionSafetyLimits(strategy_magic=231500, order_comment_prefix="LPFSIC"),
        )
        assert ic_decision.intent is not None
        self.assertEqual(ic_decision.intent.magic, 231500)
        self.assertEqual(ic_decision.intent.comment, "LPFSIC H4 L 10")

        legacy_intent = decision.intent.__class__(
            signal_key="manual",
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
        self.assertNotIn("signal_time_utc", legacy_intent.to_dict())
        self.assertNotIn("broker_backstop_expiration_time_utc", legacy_intent.to_dict())

    def test_rejects_pending_orders_after_expiration_time(self) -> None:
        expired = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020, time_utc="2026-01-12 04:00:00"),
        )

        self.assertFalse(expired.ready)
        self.assertEqual(expired.rejection_reason, "pending_expired")
        self.assertIn("expiration", expired.checks)
        self.assertIn("broker_backstop_expiration_time_utc=2026-01-12T04:00:00+00:00", expired.detail)
        self.assertIn("market_time_utc=2026-01-12T04:00:00+00:00", expired.detail)

    def test_short_order_caps_volume_and_allows_open_risk_equality(self) -> None:
        decision = build_mt5_order_intent(
            _short_setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1980, ask=1.1982, spread_points=2.0),
            safety=ExecutionSafetyLimits(max_lots_per_order=0.10),
            exposure=ExistingStrategyExposure(open_risk_pct=5.9, same_symbol_positions=3, total_strategy_positions=16),
        )

        self.assertTrue(decision.ready)
        assert decision.intent is not None
        self.assertEqual(decision.intent.order_type, "SELL_LIMIT")
        self.assertAlmostEqual(decision.intent.volume, 0.10)
        self.assertAlmostEqual(decision.intent.actual_risk_pct, 0.10)
        self.assertEqual(decision.intent.target_risk_pct, 0.75)
        self.assertEqual(decision.intent.expiration_time_utc, pd.Timestamp("2026-03-12T00:00:00Z"))

    def test_signal_keys_and_money_risk_are_deterministic(self) -> None:
        setup = _setup(signal_index=None, metadata={"candidate_id": "c1", "fs_signal_time_utc": "2026-01-01T00:00:00Z"})

        self.assertAlmostEqual(money_risk_per_lot(setup, _spec()), 500.0)
        self.assertEqual(signal_key_for_setup(setup), "lpfs:EURUSD:H4:None:long:c1:2026-01-01T00:00:00Z")
        fallback_key = signal_key_for_setup(_setup(metadata={"candidate_id": None, "fs_signal_time_utc": None}))
        self.assertIn("None:None", fallback_key)
        with self.assertRaisesRegex(ValueError, "tick value and tick size"):
            money_risk_per_lot(setup, _spec(trade_tick_value=0.0))

    def test_rejects_duplicate_and_exposure_limits_before_sending(self) -> None:
        setup = _setup()
        duplicate = build_mt5_order_intent(
            setup,
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            exposure=ExistingStrategyExposure(existing_signal_keys=(signal_key_for_setup(setup),)),
        )
        self.assertFalse(duplicate.ready)
        self.assertEqual(duplicate.rejection_reason, "duplicate_signal")
        self.assertEqual(duplicate.to_dict()["rejection_reason"], "duplicate_signal")

        same_symbol = build_mt5_order_intent(
            setup,
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            exposure=ExistingStrategyExposure(same_symbol_positions=4),
        )
        self.assertEqual(same_symbol.rejection_reason, "same_symbol_stack_limit")

        concurrent = build_mt5_order_intent(
            setup,
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            exposure=ExistingStrategyExposure(total_strategy_positions=17),
        )
        self.assertEqual(concurrent.rejection_reason, "concurrent_trade_limit")

        open_risk = build_mt5_order_intent(
            _short_setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1980, ask=1.1982),
            safety=ExecutionSafetyLimits(max_lots_per_order=0.10),
            exposure=ExistingStrategyExposure(open_risk_pct=5.91),
        )
        self.assertEqual(open_risk.rejection_reason, "max_open_risk")

    def test_rejects_basic_market_and_geometry_problems(self) -> None:
        cases = [
            ("symbol_mismatch", _setup(symbol="GBPUSD"), _spec(), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("unsupported_side", _setup(side="flat"), _spec(), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("symbol_not_tradeable", _setup(), _spec(visible=False), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("symbol_not_tradeable", _setup(), _spec(trade_allowed=False), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("invalid_account_equity", _setup(), _spec(), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(0.0), ExecutionSafetyLimits()),
            ("non_finite_price", _setup(entry=float("nan")), _spec(), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("invalid_market", _setup(), _spec(), MT5MarketSnapshot(bid=1.1020, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("spread_too_wide", _setup(), _spec(), MT5MarketSnapshot(bid=1.1000, ask=1.1020), _account(), ExecutionSafetyLimits(max_spread_points=10)),
            ("invalid_trade_geometry", _setup(stop=1.1000), _spec(), MT5MarketSnapshot(bid=1.1018, ask=1.1020), _account(), ExecutionSafetyLimits()),
            ("invalid_trade_geometry", _short_setup(target=1.2000), _spec(), MT5MarketSnapshot(bid=1.1980, ask=1.1982), _account(), ExecutionSafetyLimits()),
        ]
        for reason, setup, spec, market, account, safety in cases:
            with self.subTest(reason=reason):
                decision = build_mt5_order_intent(
                    setup,
                    account=account,
                    symbol_spec=spec,
                    market=market,
                    safety=safety,
                )
                self.assertEqual(decision.rejection_reason, reason)

    def test_rejects_pending_direction_and_broker_distance_problems(self) -> None:
        long_marketable = build_mt5_order_intent(
            _setup(entry=1.1030, stop=1.0950, target=1.1100),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(long_marketable.rejection_reason, "entry_not_pending_pullback")

        short_marketable = build_mt5_order_intent(
            _short_setup(entry=1.1970, stop=1.2100, target=1.1900),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1980, ask=1.1982),
        )
        self.assertEqual(short_marketable.rejection_reason, "entry_not_pending_pullback")

        no_min_distance = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(trade_stops_level_points=0, trade_freeze_level_points=0),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertTrue(no_min_distance.ready)

        pending_too_close = build_mt5_order_intent(
            _setup(entry=1.1018, stop=1.0950, target=1.1050),
            account=_account(),
            symbol_spec=_spec(trade_stops_level_points=5),
            market=MT5MarketSnapshot(bid=1.1017, ask=1.1020),
        )
        self.assertEqual(pending_too_close.rejection_reason, "pending_too_close")

        sl_tp_too_close = build_mt5_order_intent(
            _setup(entry=1.1000, stop=1.0998, target=1.1002),
            account=_account(),
            symbol_spec=_spec(trade_stops_level_points=5),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(sl_tp_too_close.rejection_reason, "sl_tp_too_close")

    def test_rejects_risk_and_volume_problems(self) -> None:
        missing_bucket = build_mt5_order_intent(
            _setup(timeframe="M30"),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(missing_bucket.rejection_reason, "missing_risk_bucket")

        zero_risk = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            risk_buckets={"H4": 0.0},
        )
        self.assertEqual(zero_risk.rejection_reason, "risk_pct_limit")

        high_risk = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            safety=ExecutionSafetyLimits(max_risk_pct_per_trade=0.10),
        )
        self.assertEqual(high_risk.rejection_reason, "risk_pct_limit")

        invalid_volume_spec = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(volume_step=0.0),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(invalid_volume_spec.rejection_reason, "invalid_volume_spec")

        invalid_symbol_value = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(trade_tick_size=0.0),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(invalid_symbol_value.rejection_reason, "invalid_symbol_value")

        zero_distance = build_mt5_order_intent(
            _setup(entry=1.1000, stop=1.1000, target=1.1050),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            risk_buckets={"H4": 0.01},
        )
        self.assertEqual(zero_distance.rejection_reason, "invalid_trade_geometry")

        volume_below_min = build_mt5_order_intent(
            _setup(),
            account=_account(equity=100.0),
            symbol_spec=_spec(volume_min=0.10),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
        )
        self.assertEqual(volume_below_min.rejection_reason, "volume_below_min")

    def test_broker_risk_override_drives_live_volume_sizing(self) -> None:
        decision = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(trade_tick_value=999.0),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            risk_buckets={"H4": 0.01},
            money_risk_per_lot_override=500.0,
        )

        self.assertTrue(decision.ready)
        assert decision.intent is not None
        self.assertAlmostEqual(decision.intent.volume, 0.02)
        self.assertAlmostEqual(decision.intent.actual_risk_pct, 0.01)

        bad_override = build_mt5_order_intent(
            _setup(),
            account=_account(),
            symbol_spec=_spec(),
            market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            money_risk_per_lot_override=0.0,
        )
        self.assertEqual(bad_override.rejection_reason, "invalid_symbol_value")


if __name__ == "__main__":
    unittest.main()
