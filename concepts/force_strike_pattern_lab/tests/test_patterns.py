from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from force_strike_pattern_lab import detect_force_strike_patterns, is_bearish_signal_bar, is_bullish_signal_bar


def _frame(rows: list[dict], *, freq: str = "30min") -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq=freq, tz="UTC")
    data = []
    for index, row in enumerate(rows):
        data.append(
            {
                "time_utc": row.get("time_utc", times[index]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
        )
    return pd.DataFrame(data)


class ForceStrikePatternTests(unittest.TestCase):
    def test_signal_bar_boundaries_are_inclusive(self) -> None:
        self.assertTrue(is_bullish_signal_bar(0.0, 3.0, 0.0, 2.0))
        self.assertTrue(is_bearish_signal_bar(0.0, 3.0, 0.0, 1.0))
        self.assertFalse(is_bullish_signal_bar(1.0, 1.0, 1.0, 1.0))
        self.assertFalse(is_bearish_signal_bar(1.0, 1.0, 1.0, 1.0))

    def test_bullish_raw_force_strike_detects(self) -> None:
        patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 90, "high": 97, "low": 88, "close": 96},
                ]
            )
        )

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].side, "bullish")
        self.assertEqual(patterns[0].direction, 1)
        self.assertEqual(patterns[0].breakout_side, "below_mother_low")
        self.assertEqual(patterns[0].total_bars, 3)

    def test_bearish_raw_force_strike_detects(self) -> None:
        patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 102, "high": 103, "low": 98, "close": 99},
                ]
            )
        )

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].side, "bearish")
        self.assertEqual(patterns[0].direction, -1)
        self.assertEqual(patterns[0].breakout_side, "above_mother_high")

    def test_first_baby_must_be_inside_or_equal_mother_range(self) -> None:
        patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 101, "low": 91, "close": 95},
                    {"open": 90, "high": 97, "low": 88, "close": 96},
                ]
            )
        )

        self.assertEqual(patterns, [])

    def test_six_bar_formation_detects_but_seven_bar_formation_expires(self) -> None:
        six_bar_patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 90, "high": 97, "low": 88, "close": 96},
                ]
            )
        )
        self.assertEqual(len(six_bar_patterns), 1)
        self.assertEqual(six_bar_patterns[0].total_bars, 6)

        seven_bar_patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 88, "high": 92, "low": 87, "close": 88},
                    {"open": 90, "high": 97, "low": 88, "close": 96},
                ]
            )
        )
        self.assertEqual(seven_bar_patterns, [])

    def test_two_sided_breakout_discards_formation(self) -> None:
        patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 95, "high": 101, "low": 89, "close": 96},
                ]
            )
        )

        self.assertEqual(patterns, [])

    def test_future_bars_do_not_invalidate_valid_signal(self) -> None:
        patterns = detect_force_strike_patterns(
            _frame(
                [
                    {"open": 95, "high": 100, "low": 90, "close": 95},
                    {"open": 94, "high": 99, "low": 91, "close": 95},
                    {"open": 90, "high": 97, "low": 88, "close": 96},
                    {"open": 101, "high": 104, "low": 100, "close": 101},
                ]
            )
        )

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].signal_index, 2)

    def test_input_is_sorted_by_time_before_detection(self) -> None:
        frame = _frame(
            [
                {"open": 90, "high": 97, "low": 88, "close": 96, "time_utc": "2026-01-01T01:00:00Z"},
                {"open": 95, "high": 100, "low": 90, "close": 95, "time_utc": "2026-01-01T00:00:00Z"},
                {"open": 94, "high": 99, "low": 91, "close": 95, "time_utc": "2026-01-01T00:30:00Z"},
            ]
        )

        patterns = detect_force_strike_patterns(frame)

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].mother_index, 0)
        self.assertEqual(patterns[0].signal_index, 2)

    def test_validates_bar_window_inputs(self) -> None:
        data = _frame([])
        with self.assertRaises(ValueError):
            detect_force_strike_patterns(data, min_total_bars=2)
        with self.assertRaises(ValueError):
            detect_force_strike_patterns(data, min_total_bars=4, max_total_bars=3)


if __name__ == "__main__":
    unittest.main()
