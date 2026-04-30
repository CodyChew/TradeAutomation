from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from lp_levels_lab import active_lp_levels_by_bar, lookback_days_for_timeframe  # noqa: E402
from lp_levels_lab.levels import _unit_seconds  # noqa: E402


class LPLevelsEdgeCaseTests(unittest.TestCase):
    def test_timeframe_parser_falls_back_for_invalid_inputs(self) -> None:
        self.assertEqual(lookback_days_for_timeframe(0), 365)
        self.assertEqual(lookback_days_for_timeframe(1), 5)
        self.assertEqual(lookback_days_for_timeframe(""), 365)
        self.assertEqual(lookback_days_for_timeframe("M0"), 365)
        self.assertEqual(lookback_days_for_timeframe("UNKNOWN"), 365)
        self.assertEqual(lookback_days_for_timeframe("PERIOD_H4"), 30)
        self.assertEqual(_unit_seconds("X", 1), None)

    def test_detector_validates_inputs_and_empty_frames(self) -> None:
        with self.assertRaisesRegex(ValueError, "pivot_strength"):
            active_lp_levels_by_bar(pd.DataFrame(columns=["time_utc", "high", "low"]), "M30", pivot_strength=0)

        with self.assertRaisesRegex(ValueError, "missing required columns"):
            active_lp_levels_by_bar(pd.DataFrame({"time_utc": [], "high": []}), "M30")

        empty = active_lp_levels_by_bar(pd.DataFrame(columns=["time_utc", "high", "low"]), "M30")
        self.assertEqual(empty, [])


if __name__ == "__main__":
    unittest.main()
