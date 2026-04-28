from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import get_timeframe_spec, mt5_timeframe_value, normalize_timeframe


class FakeMT5:
    TIMEFRAME_M30 = 30
    TIMEFRAME_H4 = 240


class TimeframeTests(unittest.TestCase):
    def test_normalize_common_timeframe_aliases(self) -> None:
        cases = {
            "30": "M30",
            "30m": "M30",
            "TIMEFRAME_M30": "M30",
            "4h": "H4",
            "240": "H4",
            "D": "D1",
            "1D": "D1",
            "W": "W1",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_timeframe(raw), expected)

    def test_get_timeframe_spec_has_expected_delta(self) -> None:
        spec = get_timeframe_spec("H4")

        self.assertEqual(spec.label, "H4")
        self.assertEqual(str(spec.expected_delta), "0 days 04:00:00")

    def test_mt5_timeframe_value_uses_constant_name(self) -> None:
        self.assertEqual(mt5_timeframe_value(FakeMT5, "M30"), 30)
        self.assertEqual(mt5_timeframe_value(FakeMT5, "H4"), 240)


if __name__ == "__main__":
    unittest.main()
