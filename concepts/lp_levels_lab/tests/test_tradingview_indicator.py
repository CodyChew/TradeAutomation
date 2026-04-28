from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PINE_PATH = PROJECT_ROOT / "tradingview" / "lp_levels.pine"


def _pine_source() -> str:
    return PINE_PATH.read_text(encoding="utf-8")


def _input_int_default(source: str, name: str) -> int:
    pattern = re.compile(rf"^{re.escape(name)}\s*=\s*input\.int\(([^,\n]+)", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"Could not find Pine input default for {name!r}.")
    return int(match.group(1).strip())


class LPLevelsIndicatorTests(unittest.TestCase):
    def test_pine_indicator_file_has_expected_top_level_contract(self) -> None:
        source = _pine_source()
        self.assertTrue(PINE_PATH.exists())
        self.assertIn("//@version=6", source)
        self.assertIn("indicator(", source)
        self.assertIn('"LP Levels"', source)
        self.assertIn("overlay = true", source)
        self.assertIn("max_lines_count = 500", source)
        self.assertNotIn("strategy(", source)
        self.assertEqual(source.count("("), source.count(")"))
        self.assertEqual(source.count("["), source.count("]"))

    def test_pine_defaults_match_lp_plan(self) -> None:
        source = _pine_source()
        self.assertEqual(_input_int_default(source, "pivotStrength"), 3)
        self.assertEqual(_input_int_default(source, "maxRetainedLevels"), 150)

    def test_pine_uses_strict_pivot_geometry(self) -> None:
        source = _pine_source()
        self.assertIn("pivotHigh > high[strength + distance]", source)
        self.assertIn("pivotHigh > high[strength - distance]", source)
        self.assertIn("pivotLow < low[strength + distance]", source)
        self.assertIn("pivotLow < low[strength - distance]", source)

    def test_pine_maps_timeframe_windows(self) -> None:
        source = _pine_source()
        self.assertIn("seconds <= 135 * 60", source)
        self.assertIn("days := 5", source)
        self.assertIn("seconds <= 14 * 60 * 60", source)
        self.assertIn("days := 30", source)
        self.assertIn("days := 365", source)
        self.assertIn("days := 1460", source)

    def test_pine_uses_wick_touch_breaches_and_deletes(self) -> None:
        source = _pine_source()
        self.assertIn("high >= price", source)
        self.assertIn("low <= price", source)
        self.assertIn("line.delete(array.get(levelLines, idx))", source)
        self.assertNotIn("breachedLevelColor", source)
        self.assertNotIn("breachedLines", source)

    def test_pine_keeps_support_and_resistance_state_separate(self) -> None:
        source = _pine_source()
        self.assertIn("activeHighLines = array.new<line>()", source)
        self.assertIn("activeHighPrices = array.new<float>()", source)
        self.assertIn("activeLowLines = array.new<line>()", source)
        self.assertIn("activeLowPrices = array.new<float>()", source)

    def test_pine_enforces_retained_level_cap(self) -> None:
        source = _pine_source()
        self.assertIn("while array.size(activeHighLines) + array.size(activeLowLines) > maxRetainedLevels", source)
        self.assertIn("oldestGroup", source)
        self.assertIn("line.delete(array.get(activeHighLines, oldestIndex))", source)
        self.assertIn("line.delete(array.get(activeLowLines, oldestIndex))", source)


if __name__ == "__main__":
    unittest.main()
