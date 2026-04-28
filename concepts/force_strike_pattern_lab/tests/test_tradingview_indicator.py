from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PINE_PATH = PROJECT_ROOT / "tradingview" / "force_strike_pattern.pine"


def _pine_source() -> str:
    return PINE_PATH.read_text(encoding="utf-8")


def _input_int_default(source: str, name: str) -> int:
    pattern = re.compile(rf"^{re.escape(name)}\s*=\s*input\.int\(([^,\n]+)", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"Could not find Pine input default for {name!r}.")
    return int(match.group(1).strip())


class ForceStrikePatternIndicatorTests(unittest.TestCase):
    def test_pine_indicator_file_has_expected_top_level_contract(self) -> None:
        source = _pine_source()
        self.assertTrue(PINE_PATH.exists())
        self.assertIn("//@version=6", source)
        self.assertIn("indicator(", source)
        self.assertIn('"Force Strike Pattern"', source)
        self.assertIn("overlay = true", source)
        self.assertIn("max_boxes_count = 200", source)
        self.assertNotIn("strategy(", source)
        self.assertEqual(source.count("("), source.count(")"))
        self.assertEqual(source.count("["), source.count("]"))

    def test_pine_defaults_match_raw_pattern_plan(self) -> None:
        source = _pine_source()
        self.assertEqual(_input_int_default(source, "minTotalBarsInput"), 3)
        self.assertEqual(_input_int_default(source, "maxTotalBarsInput"), 6)

    def test_pine_excludes_strategy_context_inputs(self) -> None:
        source = _pine_source().lower()
        self.assertNotRegex(source, r"\bsma\b")
        self.assertNotIn("ta.sma", source)
        self.assertNotIn("atr", source)
        self.assertNotIn("trend", source)
        self.assertNotIn("risk", source)
        self.assertNotIn("target", source)
        self.assertNotIn("entry", source)

    def test_pine_uses_raw_force_strike_geometry(self) -> None:
        source = _pine_source()
        self.assertIn("barTwoInside = high[firstBabyOff] <= motherHigh and low[firstBabyOff] >= motherLow", source)
        self.assertIn("brokeLow := brokeLow or low[off] < motherLow", source)
        self.assertIn("brokeHigh := brokeHigh or high[off] > motherHigh", source)
        self.assertIn("closeInside = close[signalOff] >= motherLow and close[signalOff] <= motherHigh", source)
        self.assertIn("not (brokeLow and brokeHigh)", source)

    def test_pine_exposes_raw_markers_alerts_and_mother_boxes(self) -> None:
        source = _pine_source()
        self.assertIn('"Bullish Raw Force Strike"', source)
        self.assertIn('"Bearish Raw Force Strike"', source)
        self.assertIn("plotshape(showBullishSignal", source)
        self.assertIn("plotshape(showBearishSignal", source)
        self.assertIn("box.new(", source)
        self.assertIn("alertcondition(showBullishSignal", source)
        self.assertIn("alertcondition(showBearishSignal", source)


if __name__ == "__main__":
    unittest.main()
