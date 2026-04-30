from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from force_strike_pattern_lab import close_location, detect_force_strike_patterns  # noqa: E402


class ForceStrikeEdgeCaseTests(unittest.TestCase):
    def test_close_location_zero_or_inverted_range_is_neutral(self) -> None:
        self.assertEqual(close_location(1.0, 1.0, 1.0, 1.0), 0.5)
        self.assertEqual(close_location(1.0, 0.5, 1.0, 1.0), 0.5)

    def test_detector_requires_ohlc_columns(self) -> None:
        frame = pd.DataFrame({"time_utc": ["2026-01-01T00:00:00Z"], "open": [1.0], "high": [1.0], "low": [1.0]})

        with self.assertRaisesRegex(ValueError, "missing required columns: close"):
            detect_force_strike_patterns(frame)


if __name__ == "__main__":
    unittest.main()
