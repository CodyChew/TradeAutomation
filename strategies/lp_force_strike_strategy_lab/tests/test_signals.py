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
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import detect_lp_force_strike_signals


def _frame(rows: list[dict]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row.get("open", (row["high"] + row["low"]) / 2.0),
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for index, row in enumerate(rows)
        ]
    )


def _bullish_multiple_support_rows(signal_close: float = 8.0) -> list[dict]:
    return [
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
        {"high": 8.8, "low": 3.5, "close": signal_close},
    ]


def _bearish_multiple_resistance_rows(signal_close: float = 11.0) -> list[dict]:
    return [
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 15.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 16.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 17.0, "low": 10.0, "close": 12.0},
        {"high": 16.5, "low": 10.5, "close": 12.0},
        {"high": 17.2, "low": 10.5, "close": signal_close},
    ]


class LPForceStrikeSignalTests(unittest.TestCase):
    def test_bullish_force_bottom_uses_lowest_broken_support(self) -> None:
        signals = detect_lp_force_strike_signals(_frame(_bullish_multiple_support_rows()), "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "bullish")
        self.assertEqual(signals[0].scenario, "force_bottom")
        self.assertEqual(signals[0].lp_price, 4.0)
        self.assertEqual(signals[0].lp_break_index, 8)
        self.assertEqual(signals[0].fs_signal_index, 10)
        self.assertEqual(signals[0].bars_from_lp_break, 3)

    def test_bearish_force_top_uses_highest_broken_resistance(self) -> None:
        signals = detect_lp_force_strike_signals(_frame(_bearish_multiple_resistance_rows()), "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].side, "bearish")
        self.assertEqual(signals[0].scenario, "force_top")
        self.assertEqual(signals[0].lp_price, 16.0)
        self.assertEqual(signals[0].lp_break_index, 8)
        self.assertEqual(signals[0].fs_signal_index, 10)
        self.assertEqual(signals[0].bars_from_lp_break, 3)

    def test_force_strike_signal_must_be_inside_six_bar_window(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bullish_multiple_support_rows()),
            "M30",
            pivot_strength=2,
            max_bars_from_lp_break=2,
        )

        self.assertEqual(signals, [])

    def test_bullish_exe_candle_must_close_at_or_above_selected_support(self) -> None:
        rows = [
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 8.0, "low": 6.0, "close": 7.0},
            {"high": 9.0, "low": 7.0, "close": 8.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 8.0, "close": 8.5},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 9.0, "low": 8.0, "close": 8.5},
            {"high": 8.0, "low": 5.0, "close": 7.0},
            {"high": 7.5, "low": 5.5, "close": 7.0},
            {"high": 6.1, "low": 4.8, "close": 5.8},
        ]

        signals = detect_lp_force_strike_signals(_frame(rows), "M30", pivot_strength=2)

        self.assertEqual(signals, [])

    def test_bearish_exe_candle_must_close_at_or_below_selected_resistance(self) -> None:
        signals = detect_lp_force_strike_signals(
            _frame(_bearish_multiple_resistance_rows(signal_close=16.2)),
            "M30",
            pivot_strength=2,
        )

        self.assertEqual(signals, [])

    def test_detector_requires_no_sma_atr_or_context_columns(self) -> None:
        frame = _frame(_bullish_multiple_support_rows())

        signals = detect_lp_force_strike_signals(frame, "M30", pivot_strength=2)

        self.assertEqual(len(signals), 1)

    def test_validates_max_bars_from_lp_break(self) -> None:
        with self.assertRaises(ValueError):
            detect_lp_force_strike_signals(_frame([]), "M30", max_bars_from_lp_break=0)


if __name__ == "__main__":
    unittest.main()
