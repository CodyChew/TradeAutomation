from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest_engine_lab import (
    CostConfig,
    TradeSetup,
    drop_incomplete_last_bar,
    is_latest_bar_complete,
    normalize_backtest_frame,
    simulate_bracket_trade,
    simulate_bracket_trade_on_normalized_frame,
)


def _frame(rows: list[tuple[str, float, float, float, float]], *, spread_points: float = 0.0, point: float = 0.01) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_utc": [row[0] for row in rows],
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "spread_points": [spread_points for _ in rows],
            "point": [point for _ in rows],
        }
    )


class BacktestEngineTests(unittest.TestCase):
    def test_long_trade_exits_at_target(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 106.0, 99.0, 105.0),
            ]
        )
        setup = TradeSetup(setup_id="L1", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=105.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.reference_r, 1.0)
        self.assertEqual(trade.net_r, 1.0)

    def test_long_trade_exits_at_stop(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 101.0, 94.0, 95.0),
            ]
        )
        setup = TradeSetup(setup_id="L2", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=105.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.reference_r, -1.0)
        self.assertEqual(trade.net_r, -1.0)

    def test_short_trade_exits_at_target(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 101.0, 94.0, 95.0),
            ]
        )
        setup = TradeSetup(setup_id="S1", side="short", entry_index=1, entry_price=100.0, stop_price=105.0, target_price=95.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.reference_r, 1.0)
        self.assertEqual(trade.net_r, 1.0)

    def test_short_trade_exits_at_stop(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 106.0, 99.0, 105.0),
            ]
        )
        setup = TradeSetup(setup_id="S2", side="short", entry_index=1, entry_price=100.0, stop_price=105.0, target_price=95.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.reference_r, -1.0)
        self.assertEqual(trade.net_r, -1.0)

    def test_same_bar_stop_and_target_uses_stop_first(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 106.0, 94.0, 100.0),
            ]
        )
        setup = TradeSetup(setup_id="L3", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=105.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "same_bar_stop_priority")
        self.assertEqual(trade.reference_r, -1.0)

    def test_spread_slippage_and_commission_reduce_net_r(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 111.0, 99.0, 110.0),
            ],
            spread_points=10.0,
            point=0.01,
        )
        setup = TradeSetup(setup_id="L4", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=110.0)
        costs = CostConfig(entry_slippage_points=5.0, exit_slippage_points=5.0, round_turn_commission_points=10.0)

        trade = simulate_bracket_trade(frame, setup, costs=costs)

        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.reference_r, 2.0)
        self.assertAlmostEqual(trade.entry_fill_price, 100.10)
        self.assertAlmostEqual(trade.exit_fill_price, 109.90)
        self.assertAlmostEqual(trade.fill_r, 1.96)
        self.assertAlmostEqual(trade.commission_r, 0.02)
        self.assertAlmostEqual(trade.net_r, 1.94)

    def test_end_of_data_exit_uses_final_close(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 102.0, 98.0, 101.0),
            ]
        )
        setup = TradeSetup(setup_id="L5", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=110.0)

        trade = simulate_bracket_trade(frame, setup)

        self.assertEqual(trade.exit_reason, "end_of_data")
        self.assertEqual(trade.exit_reference_price, 101.0)
        self.assertEqual(trade.reference_r, 0.2)

    def test_normalized_fast_path_matches_standard_simulation(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 100.0, 106.0, 99.0, 105.0),
            ]
        )
        setup = TradeSetup(setup_id="L6", side="long", entry_index=1, entry_price=100.0, stop_price=95.0, target_price=105.0)

        standard = simulate_bracket_trade(frame, setup)
        fast = simulate_bracket_trade_on_normalized_frame(normalize_backtest_frame(frame), setup)

        self.assertEqual(fast.to_dict(), standard.to_dict())

    def test_drop_incomplete_last_bar(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:30:00Z", 101.0, 102.0, 100.0, 101.0),
            ]
        )

        incomplete = is_latest_bar_complete(frame, "M30", as_of_time_utc="2026-01-01T00:45:00Z")
        dropped = drop_incomplete_last_bar(frame, "M30", as_of_time_utc="2026-01-01T00:45:00Z")
        complete = drop_incomplete_last_bar(frame, "M30", as_of_time_utc="2026-01-01T01:00:00Z")

        self.assertFalse(incomplete.latest_bar_complete)
        self.assertEqual(len(dropped), 1)
        self.assertEqual(len(complete), 2)

    def test_drop_incomplete_last_bar_supports_h8(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T08:00:00Z", 101.0, 102.0, 100.0, 101.0),
            ]
        )

        incomplete = is_latest_bar_complete(frame, "H8", as_of_time_utc="2026-01-01T12:00:00Z")
        complete = is_latest_bar_complete(frame, "H8", as_of_time_utc="2026-01-01T16:00:00Z")

        self.assertFalse(incomplete.latest_bar_complete)
        self.assertTrue(complete.latest_bar_complete)

    def test_normalize_sorts_by_time(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:30:00Z", 101.0, 102.0, 100.0, 101.0),
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
            ]
        )

        data = normalize_backtest_frame(frame)

        self.assertEqual(str(data["time_utc"].iloc[0]), "2026-01-01 00:00:00+00:00")

    def test_normalize_rejects_duplicate_timestamps(self) -> None:
        frame = _frame(
            [
                ("2026-01-01T00:00:00Z", 100.0, 101.0, 99.0, 100.0),
                ("2026-01-01T00:00:00Z", 101.0, 102.0, 100.0, 101.0),
            ]
        )

        with self.assertRaisesRegex(ValueError, "duplicate timestamps"):
            normalize_backtest_frame(frame)


if __name__ == "__main__":
    unittest.main()
