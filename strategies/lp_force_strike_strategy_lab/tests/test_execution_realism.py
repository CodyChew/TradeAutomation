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

from backtest_engine_lab import CostConfig, TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    ExecutionRealismVariant,
    LPForceStrikeSignal,
    SkippedTrade,
    TradeModelCandidate,
    build_bid_ask_trade_setup,
    point_from_row,
    run_lp_force_strike_execution_realism_on_frame,
    simulate_bid_ask_bracket_trade_on_normalized_frame,
    spread_points_from_row,
    spread_price_from_row,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row.get("open", 100.0),
                "high": row["high"],
                "low": row["low"],
                "close": row.get("close", row["low"] + (row["high"] - row["low"]) / 2.0),
                "spread_points": row.get("spread_points", 0.0),
                "point": row.get("point", 0.1),
            }
            for index, row in enumerate(rows)
        ]
    )


def _signal(side: str = "bullish") -> LPForceStrikeSignal:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=10, freq="h", tz="UTC")
    return LPForceStrikeSignal(
        side=side,  # type: ignore[arg-type]
        scenario="force_bottom" if side == "bullish" else "force_top",
        lp_price=95.0 if side == "bullish" else 105.0,
        lp_break_index=3,
        lp_break_time_utc=times[3],
        lp_pivot_index=1,
        lp_pivot_time_utc=times[1],
        fs_mother_index=4,
        fs_signal_index=6,
        fs_mother_time_utc=times[4],
        fs_signal_time_utc=times[6],
        bars_from_lp_break=4,
        fs_total_bars=3,
    )


class ExecutionRealismTests(unittest.TestCase):
    def test_spread_price_uses_row_point_and_fallbacks(self) -> None:
        row = pd.Series({"spread_points": "bad", "point": 0.01})
        self.assertAlmostEqual(spread_price_from_row(row, CostConfig(fallback_spread_points=3.0)), 0.03)

        missing_point = pd.Series({"spread_points": 4.0, "point": 0.0})
        self.assertAlmostEqual(spread_price_from_row(missing_point, CostConfig(point=0.1)), 0.4)
        self.assertAlmostEqual(point_from_row(missing_point, CostConfig(point=0.1)), 0.1)
        self.assertAlmostEqual(spread_points_from_row(missing_point, CostConfig(point=0.1)), 4.0)
        self.assertAlmostEqual(point_from_row(pd.Series({"point": "bad"}), CostConfig(point=0.1)), 0.1)
        self.assertAlmostEqual(spread_points_from_row(pd.Series({"spread_points": -1}), CostConfig(fallback_spread_points=2.0)), 2.0)

        disabled = pd.Series({"spread_points": 50.0, "point": 0.01})
        self.assertAlmostEqual(
            spread_price_from_row(disabled, CostConfig(use_candle_spread=False, fallback_spread_points=2.0)),
            0.02,
        )

    def test_long_buy_limit_requires_ask_low_to_reach_entry(self) -> None:
        frame = _frame(
            [
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 104, "low": 96},
                {"high": 103, "low": 97},
                {"high": 106, "low": 94},
                {"high": 105, "low": 99.5, "spread_points": 10, "point": 0.1},
                {"high": 105, "low": 99.0, "spread_points": 10, "point": 0.1},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        setup = build_bid_ask_trade_setup(
            frame,
            _signal("bullish"),
            candidate,
            symbol="TEST",
            timeframe="H1",
            atr_period=1,
            max_entry_wait_bars=2,
        )

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.entry_index, 8)
        self.assertEqual(setup.entry_price, 100.0)

    def test_short_sell_limit_uses_bid_high_for_entry(self) -> None:
        frame = _frame(
            [
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 104, "low": 96},
                {"high": 103, "low": 97},
                {"high": 106, "low": 94},
                {"high": 100.0, "low": 95, "spread_points": 10, "point": 0.1},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        setup = build_bid_ask_trade_setup(frame, _signal("bearish"), candidate, symbol="TEST", timeframe="H1", atr_period=1)

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.entry_index, 7)
        self.assertEqual(setup.entry_price, 100.0)

    def test_short_stop_can_hit_by_ask_without_bid_touching_stop(self) -> None:
        frame = _frame(
            [
                {"high": 100.4, "low": 99.2, "spread_points": 10, "point": 0.1},
                {"high": 100.9, "low": 99.4, "spread_points": 10, "point": 0.1},
            ]
        )
        setup = TradeSetup(
            setup_id="short",
            side="short",
            entry_index=0,
            entry_price=100.0,
            stop_price=101.5,
            target_price=98.5,
            symbol="TEST",
            timeframe="H1",
        )

        trade = simulate_bid_ask_bracket_trade_on_normalized_frame(frame, setup, costs=CostConfig())

        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit_index, 1)
        self.assertEqual(trade.net_r, -1.0)

    def test_same_bar_stop_and_target_remains_stop_first(self) -> None:
        frame = _frame([{"high": 100.9, "low": 98.0, "spread_points": 10, "point": 0.1}])
        setup = TradeSetup(
            setup_id="short",
            side="short",
            entry_index=0,
            entry_price=100.0,
            stop_price=101.5,
            target_price=99.2,
            symbol="TEST",
            timeframe="H1",
        )

        trade = simulate_bid_ask_bracket_trade_on_normalized_frame(frame, setup, costs=CostConfig())

        self.assertEqual(trade.exit_reason, "same_bar_stop_priority")
        self.assertEqual(trade.net_r, -1.0)

    def test_stop_buffer_expands_structure_stop_and_recalculates_target(self) -> None:
        frame = _frame(
            [
                {"high": 101, "low": 99, "spread_points": 0},
                {"high": 101, "low": 99, "spread_points": 0},
                {"high": 101, "low": 99, "spread_points": 0},
                {"high": 101, "low": 99, "spread_points": 0},
                {"high": 104, "low": 96, "spread_points": 0},
                {"high": 103, "low": 97, "spread_points": 0},
                {"high": 106, "low": 94, "spread_points": 10, "point": 0.1},
                {"high": 105, "low": 99, "spread_points": 0},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        setup = build_bid_ask_trade_setup(
            frame,
            _signal("bullish"),
            candidate,
            symbol="TEST",
            timeframe="H1",
            atr_period=1,
            stop_buffer_spread_mult=1.5,
        )

        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.stop_price, 92.5)
        self.assertEqual(setup.target_price, 107.5)
        self.assertEqual(setup.metadata["stop_buffer_price"], 1.5)

    def test_build_setup_rejects_invalid_parameters_and_entry_cases(self) -> None:
        frame = _frame(
            [
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 104, "low": 96},
                {"high": 103, "low": 97},
                {"high": 106, "low": 94},
                {"high": 105, "low": 101},
            ]
        )
        candidate = TradeModelCandidate("mid", "signal_midpoint_pullback", "fs_structure", 1.0)

        with self.assertRaisesRegex(ValueError, "max_entry_wait_bars"):
            build_bid_ask_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="H1", max_entry_wait_bars=0)
        with self.assertRaisesRegex(ValueError, "stop_buffer_spread_mult"):
            build_bid_ask_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="H1", stop_buffer_spread_mult=-1)

        skipped = build_bid_ask_trade_setup(frame, _signal("bullish"), candidate, symbol="TEST", timeframe="H1", max_entry_wait_bars=1)
        self.assertIsInstance(skipped, SkippedTrade)
        assert isinstance(skipped, SkippedTrade)
        self.assertEqual(skipped.reason, "entry_not_reached")

        bad_range = frame.copy()
        bad_range.loc[6, "low"] = bad_range.loc[6, "high"]
        skipped_range = build_bid_ask_trade_setup(bad_range, _signal("bullish"), candidate, symbol="TEST", timeframe="H1")
        self.assertIsInstance(skipped_range, SkippedTrade)
        assert isinstance(skipped_range, SkippedTrade)
        self.assertEqual(skipped_range.reason, "invalid_entry_range")

        unsupported = TradeModelCandidate("bad", "bad_entry", "fs_structure", 1.0)  # type: ignore[arg-type]
        skipped_unsupported = build_bid_ask_trade_setup(frame, _signal("bullish"), unsupported, symbol="TEST", timeframe="H1")
        self.assertIsInstance(skipped_unsupported, SkippedTrade)
        assert isinstance(skipped_unsupported, SkippedTrade)
        self.assertEqual(skipped_unsupported.reason, "unsupported_entry_model")

    def test_next_open_and_atr_filter_rejection_paths(self) -> None:
        frame = _frame(
            [
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 101, "low": 99},
                {"high": 104, "low": 96},
                {"high": 103, "low": 97},
                {"high": 106, "low": 94},
                {"open": 100, "high": 102, "low": 98},
            ]
        )
        next_open = TradeModelCandidate("next", "next_open", "fs_structure", 1.0)
        setup = build_bid_ask_trade_setup(frame, _signal("bullish"), next_open, symbol="TEST", timeframe="H1", atr_period=1)
        self.assertNotIsInstance(setup, SkippedTrade)
        assert not isinstance(setup, SkippedTrade)
        self.assertEqual(setup.entry_index, 7)
        self.assertEqual(setup.entry_price, 100.0)

        invalid_short_frame = frame.copy()
        invalid_short_frame.loc[7, "open"] = 110.0
        invalid_stop = build_bid_ask_trade_setup(invalid_short_frame, _signal("bearish"), next_open, symbol="TEST", timeframe="H1", atr_period=1)
        self.assertIsInstance(invalid_stop, SkippedTrade)
        assert isinstance(invalid_stop, SkippedTrade)
        self.assertEqual(invalid_stop.reason, "invalid_stop")

        max_atr = TradeModelCandidate("max", "next_open", "fs_structure_max_atr", 1.0, max_risk_atr=0.01)
        risk_wide = build_bid_ask_trade_setup(frame, _signal("bullish"), max_atr, symbol="TEST", timeframe="H1", atr_period=1)
        self.assertIsInstance(risk_wide, SkippedTrade)
        assert isinstance(risk_wide, SkippedTrade)
        self.assertEqual(risk_wide.reason, "risk_too_wide")

        missing_atr = build_bid_ask_trade_setup(frame, _signal("bullish"), max_atr, symbol="TEST", timeframe="H1", atr_period=100)
        self.assertIsInstance(missing_atr, SkippedTrade)
        assert isinstance(missing_atr, SkippedTrade)
        self.assertEqual(missing_atr.reason, "missing_atr")

        max_atr_pass = TradeModelCandidate("max", "next_open", "fs_structure_max_atr", 1.0, max_risk_atr=10.0)
        max_atr_setup = build_bid_ask_trade_setup(frame, _signal("bullish"), max_atr_pass, symbol="TEST", timeframe="H1", atr_period=1)
        self.assertNotIsInstance(max_atr_setup, SkippedTrade)

        no_next = build_bid_ask_trade_setup(frame.iloc[:7], _signal("bullish"), next_open, symbol="TEST", timeframe="H1")
        self.assertIsInstance(no_next, SkippedTrade)
        assert isinstance(no_next, SkippedTrade)
        self.assertEqual(no_next.reason, "no_next_candle")

    def test_simulation_target_end_of_data_and_validation_paths(self) -> None:
        target_frame = _frame([{"high": 102.0, "low": 100.0, "spread_points": 0}])
        long_setup = TradeSetup(
            setup_id="long",
            side="long",
            entry_index=0,
            entry_price=100.0,
            stop_price=99.0,
            target_price=101.0,
            symbol="TEST",
            timeframe="H1",
        )
        target = simulate_bid_ask_bracket_trade_on_normalized_frame(target_frame, long_setup)
        self.assertEqual(target.exit_reason, "target")
        self.assertEqual(target.net_r, 1.0)

        end_frame = _frame([{"high": 100.5, "low": 99.5, "close": 100.25, "spread_points": 0}])
        end = simulate_bid_ask_bracket_trade_on_normalized_frame(end_frame, long_setup)
        self.assertEqual(end.exit_reason, "end_of_data")
        self.assertEqual(end.net_r, 0.25)

        for bad_setup, message in [
            (TradeSetup("bad", "flat", 0, 100, 99, 101), "side"),  # type: ignore[arg-type]
            (TradeSetup("bad", "long", 2, 100, 99, 101), "entry_index"),
            (TradeSetup("bad", "long", 0, 100, 100.5, 101), "Long setup"),
            (TradeSetup("bad", "short", 0, 100, 99, 101), "Short setup"),
        ]:
            with self.assertRaisesRegex(ValueError, message):
                simulate_bid_ask_bracket_trade_on_normalized_frame(target_frame, bad_setup)

    def test_frame_runner_returns_bid_ask_variants_without_touching_ohlc_path(self) -> None:
        rows = [
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 8.0, "low": 5.0, "close": 6.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 8.0, "low": 4.0, "close": 5.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 3.8, "close": 7.0},
            {"high": 8.5, "low": 4.5, "close": 7.0},
            {"high": 8.8, "low": 3.5, "close": 8.0},
            {"high": 9.5, "low": 7.5, "close": 9.0},
            {"high": 12.0, "low": 8.0, "close": 11.0},
        ]
        frame = _frame(rows)
        candidate = TradeModelCandidate("base", "next_open", "fs_structure", 1.0)

        result = run_lp_force_strike_execution_realism_on_frame(
            frame,
            symbol="TEST",
            timeframe="M30",
            candidate=candidate,
            variants=[ExecutionRealismVariant("bid_ask", 0.0), ExecutionRealismVariant("bid_ask", 1.0)],
            pivot_strength=2,
            atr_period=1,
        )

        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(
            {trade.metadata["execution_variant_id"] for trade in result.trades},
            {"bid_ask_buffer_0x", "bid_ask_buffer_1x"},
        )

    def test_frame_runner_rejects_empty_and_unsupported_variants_and_records_skips(self) -> None:
        rows = [
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 8.0, "low": 5.0, "close": 6.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 8.0, "low": 4.0, "close": 5.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 3.8, "close": 7.0},
            {"high": 8.5, "low": 4.5, "close": 7.0},
            {"high": 8.8, "low": 3.5, "close": 8.0},
            {"high": 9.5, "low": 7.5, "close": 9.0},
            {"high": 12.0, "low": 8.0, "close": 11.0},
        ]
        frame = _frame(rows)
        candidate = TradeModelCandidate("base", "signal_midpoint_pullback", "fs_structure", 1.0)

        with self.assertRaisesRegex(ValueError, "At least one"):
            run_lp_force_strike_execution_realism_on_frame(
                frame,
                symbol="TEST",
                timeframe="M30",
                candidate=candidate,
                variants=[],
                pivot_strength=2,
                atr_period=1,
            )
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            run_lp_force_strike_execution_realism_on_frame(
                frame,
                symbol="TEST",
                timeframe="M30",
                candidate=candidate,
                variants=[ExecutionRealismVariant("ohlc", 0.0)],
                pivot_strength=2,
                atr_period=1,
            )

        skipped = run_lp_force_strike_execution_realism_on_frame(
            frame,
            symbol="TEST",
            timeframe="M30",
            candidate=candidate,
            variants=[ExecutionRealismVariant("bid_ask", 0.0)],
            pivot_strength=2,
            atr_period=1,
            max_entry_wait_bars=1,
            costs=CostConfig(fallback_spread_points=1.0, point=10.0),
        )
        self.assertEqual(len(skipped.trades), 0)
        self.assertEqual(len(skipped.skipped), 1)
        self.assertIn("execution_variant_id=bid_ask_buffer_0x", skipped.skipped[0].detail)


if __name__ == "__main__":
    unittest.main()
