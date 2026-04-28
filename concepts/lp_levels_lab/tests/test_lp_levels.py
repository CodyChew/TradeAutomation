from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lp_levels_lab import LPLevel, active_lp_levels_by_bar, lookback_days_for_timeframe


def _frame(highs: list[float], lows: list[float], *, times: list[str] | None = None) -> pd.DataFrame:
    if times is None:
        times = [str(ts) for ts in pd.date_range("2026-01-01", periods=len(highs), freq="h", tz="UTC")]
    return pd.DataFrame({"time_utc": times, "high": highs, "low": lows})


def _levels_with_side(levels: list[LPLevel], side: str) -> list[LPLevel]:
    return [level for level in levels if level.side == side]


class LPLevelsTests(unittest.TestCase):
    def test_timeframe_bucket_mapping_matches_spec(self) -> None:
        cases = {
            "M30": 5,
            "30": 5,
            "2H": 5,
            "H4": 30,
            "240": 30,
            "H15": 365,
            "D1": 365,
            "D": 365,
            "2D": 365,
            "W1": 1460,
            "W": 1460,
            "D5": 1460,
            "MN1": 1460,
        }
        for timeframe, expected in cases.items():
            with self.subTest(timeframe=timeframe):
                self.assertEqual(lookback_days_for_timeframe(timeframe), expected)

    def test_strict_resistance_pivot_requires_distinct_high(self) -> None:
        levels = active_lp_levels_by_bar(_frame([1.0, 3.0, 2.0], [1.0, 1.0, 1.0]), "M30", pivot_strength=1)
        resistance = _levels_with_side(levels[2], "resistance")
        self.assertEqual(len(resistance), 1)
        self.assertEqual(resistance[0].price, 3.0)
        self.assertEqual(resistance[0].pivot_index, 1)
        self.assertEqual(resistance[0].confirmed_index, 2)

        equal_right_high = active_lp_levels_by_bar(
            _frame([1.0, 3.0, 3.0], [1.0, 1.0, 1.0]),
            "M30",
            pivot_strength=1,
        )
        self.assertEqual(_levels_with_side(equal_right_high[2], "resistance"), [])

    def test_strict_support_pivot_requires_distinct_low(self) -> None:
        levels = active_lp_levels_by_bar(_frame([5.0, 5.0, 5.0], [3.0, 1.0, 2.0]), "M30", pivot_strength=1)
        support = _levels_with_side(levels[2], "support")
        self.assertEqual(len(support), 1)
        self.assertEqual(support[0].price, 1.0)
        self.assertEqual(support[0].pivot_index, 1)
        self.assertEqual(support[0].confirmed_index, 2)

        equal_right_low = active_lp_levels_by_bar(
            _frame([5.0, 5.0, 5.0], [3.0, 1.0, 1.0]),
            "M30",
            pivot_strength=1,
        )
        self.assertEqual(_levels_with_side(equal_right_low[2], "support"), [])

    def test_confirmation_delay_prevents_future_leakage(self) -> None:
        levels = active_lp_levels_by_bar(_frame([1.0, 3.0, 2.0, 2.5], [1.0, 1.0, 1.0, 1.0]), "M30", pivot_strength=1)

        self.assertEqual(_levels_with_side(levels[0], "resistance"), [])
        self.assertEqual(_levels_with_side(levels[1], "resistance"), [])

        resistance = _levels_with_side(levels[2], "resistance")
        self.assertEqual(len(resistance), 1)
        self.assertEqual(resistance[0].pivot_index, 1)
        self.assertEqual(resistance[0].confirmed_index, 2)

    def test_resistance_breach_deletes_level_on_wick_touch(self) -> None:
        levels = active_lp_levels_by_bar(_frame([1.0, 3.0, 2.0, 3.0], [1.0, 1.0, 1.0, 1.0]), "M30", pivot_strength=1)

        self.assertEqual(len(_levels_with_side(levels[2], "resistance")), 1)
        self.assertEqual(_levels_with_side(levels[3], "resistance"), [])

    def test_support_breach_deletes_level_on_wick_touch(self) -> None:
        levels = active_lp_levels_by_bar(_frame([5.0, 5.0, 5.0, 5.0], [3.0, 1.0, 2.0, 1.0]), "M30", pivot_strength=1)

        self.assertEqual(len(_levels_with_side(levels[2], "support")), 1)
        self.assertEqual(_levels_with_side(levels[3], "support"), [])

    def test_lookback_expiry_is_rolling_by_current_bar(self) -> None:
        times = [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-07T00:00:00Z",
        ]
        levels = active_lp_levels_by_bar(_frame([1.0, 3.0, 2.0, 2.0], [1.0, 1.0, 1.0, 1.0], times=times), "M30", pivot_strength=1)

        self.assertEqual(len(_levels_with_side(levels[2], "resistance")), 1)
        self.assertEqual(_levels_with_side(levels[3], "resistance"), [])

    def test_input_is_sorted_by_time_before_detection(self) -> None:
        frame = pd.DataFrame(
            {
                "time_utc": [
                    "2026-01-01T02:00:00Z",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T01:00:00Z",
                ],
                "high": [2.0, 1.0, 3.0],
                "low": [1.0, 1.0, 1.0],
            }
        )

        levels = active_lp_levels_by_bar(frame, "M30", pivot_strength=1)

        resistance = _levels_with_side(levels[2], "resistance")
        self.assertEqual(len(resistance), 1)
        self.assertEqual(resistance[0].price, 3.0)
        self.assertEqual(resistance[0].pivot_index, 1)


if __name__ == "__main__":
    unittest.main()
