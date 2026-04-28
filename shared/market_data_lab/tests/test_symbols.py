from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import FOREX_MAJOR_CROSS_PAIRS, FOREX_MAJOR_CURRENCIES


class SymbolUniverseTests(unittest.TestCase):
    def test_forex_major_cross_universe_contains_28_pairs(self) -> None:
        self.assertEqual(FOREX_MAJOR_CURRENCIES, ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"))
        self.assertEqual(len(FOREX_MAJOR_CROSS_PAIRS), 28)
        self.assertEqual(len(set(FOREX_MAJOR_CROSS_PAIRS)), 28)

    def test_forex_major_cross_universe_excludes_non_forex_markets(self) -> None:
        excluded = {"XAUUSD", "US30", "BTCUSD", "USDZAR", "EURTRY"}

        self.assertTrue(excluded.isdisjoint(FOREX_MAJOR_CROSS_PAIRS))


if __name__ == "__main__":
    unittest.main()
