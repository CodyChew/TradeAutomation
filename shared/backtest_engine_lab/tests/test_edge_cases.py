from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest_engine_lab import (  # noqa: E402
    CostConfig,
    TradeSetup,
    drop_incomplete_last_bar,
    is_latest_bar_complete,
    normalize_backtest_frame,
    simulate_bracket_trade,
    simulate_bracket_trade_on_normalized_frame,
)


def _frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_utc": [row[0] for row in rows],
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
        }
    )


class BacktestEngineEdgeCaseTests(unittest.TestCase):
    def test_normalize_validates_malformed_frames(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            normalize_backtest_frame(pd.DataFrame({"time_utc": [], "open": [], "high": [], "low": []}))

        with self.assertRaisesRegex(ValueError, "empty"):
            normalize_backtest_frame(pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"]))

        bad = pd.DataFrame(
            {
                "time_utc": ["2026-01-01T00:00:00Z"],
                "open": ["bad"],
                "high": [101.0],
                "low": [99.0],
                "close": [100.0],
            }
        )
        with self.assertRaisesRegex(ValueError, "non-numeric open"):
            normalize_backtest_frame(bad)

        with self.assertRaisesRegex(ValueError, "invalid high"):
            normalize_backtest_frame(_frame([("2026-01-01T00:00:00Z", 100.0, 99.0, 98.0, 100.0)]))

        with self.assertRaisesRegex(ValueError, "invalid low"):
            normalize_backtest_frame(_frame([("2026-01-01T00:00:00Z", 100.0, 101.0, 101.0, 100.0)]))

    def test_latest_bar_timeframe_and_timezone_edges(self) -> None:
        frame = _frame([("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0)])

        self.assertTrue(is_latest_bar_complete(frame, 30, as_of_time_utc="2026-01-01T00:30:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "PERIOD_30", as_of_time_utc="2026-01-01T00:30:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "TIMEFRAME_M30", as_of_time_utc="2026-01-01T00:30:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "90M", as_of_time_utc="2026-01-01T01:30:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "2H", as_of_time_utc="2026-01-01T02:00:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "3D", as_of_time_utc="2026-01-04T00:00:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "2W", as_of_time_utc="2026-01-15T00:00:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "M5", as_of_time_utc="2026-01-01T00:05:00Z").latest_bar_complete)
        self.assertTrue(is_latest_bar_complete(frame, "H1", as_of_time_utc=pd.Timestamp("2026-01-01T01:00:00")).latest_bar_complete)

        with self.assertRaisesRegex(ValueError, "positive"):
            is_latest_bar_complete(frame, 0, as_of_time_utc="2026-01-01T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            is_latest_bar_complete(frame, "Q1", as_of_time_utc="2026-01-01T00:30:00Z")
        with self.assertRaisesRegex(ValueError, "only row"):
            drop_incomplete_last_bar(frame, "M30", as_of_time_utc="2026-01-01T00:15:00Z")

    def test_cost_fallbacks_and_setup_validation_are_explicit(self) -> None:
        frame = _frame([("2026-01-01T00:00:00Z", 100.0, 106.0, 99.0, 105.0)])
        frame["spread_points"] = ["bad"]
        frame["point"] = ["bad"]
        setup = TradeSetup("L", "long", 0, 100.0, 95.0, 105.0)
        costs = CostConfig(point=0.01, fallback_spread_points=10.0, entry_slippage_points=1.0, exit_slippage_points=1.0)

        trade = simulate_bracket_trade_on_normalized_frame(frame, setup, costs=costs)

        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.entry_fill_price, 100.06)
        self.assertAlmostEqual(trade.exit_fill_price, 104.94)

        no_spread_costs = CostConfig(point=0.01, use_candle_spread=False, fallback_spread_points=20.0)
        no_spread_trade = simulate_bracket_trade_on_normalized_frame(frame, setup, costs=no_spread_costs)
        self.assertAlmostEqual(no_spread_trade.entry_fill_price, 100.10)

        invalid_setups = [
            TradeSetup("bad-side", "flat", 0, 100.0, 95.0, 105.0),  # type: ignore[arg-type]
            TradeSetup("bad-index", "long", 5, 100.0, 95.0, 105.0),
            TradeSetup("bad-long", "long", 0, 100.0, 101.0, 105.0),
            TradeSetup("bad-short", "short", 0, 100.0, 105.0, 101.0),
        ]
        for invalid in invalid_setups:
            with self.subTest(setup=invalid.setup_id):
                with self.assertRaises(ValueError):
                    simulate_bracket_trade(frame, invalid)


if __name__ == "__main__":
    unittest.main()
