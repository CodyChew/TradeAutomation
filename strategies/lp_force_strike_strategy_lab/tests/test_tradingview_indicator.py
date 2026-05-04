from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PINE_PATH = PROJECT_ROOT / "tradingview" / "lp_force_strike.pine"
README_PATH = PROJECT_ROOT / "tradingview" / "README.md"


def _pine_source() -> str:
    return PINE_PATH.read_text(encoding="utf-8")


def _input_int_default(source: str, name: str) -> int:
    pattern = re.compile(rf"^{re.escape(name)}\s*=\s*input\.int\(([^,\n]+)", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"Could not find Pine input default for {name!r}.")
    return int(match.group(1).strip())


def _input_float_default(source: str, name: str) -> float:
    pattern = re.compile(rf"^{re.escape(name)}\s*=\s*input\.float\(([^,\n]+)", re.MULTILINE)
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"Could not find Pine input default for {name!r}.")
    return float(match.group(1).strip())


class LPForceStrikeTradingViewIndicatorTests(unittest.TestCase):
    def test_pine_indicator_file_has_expected_top_level_contract(self) -> None:
        source = _pine_source()
        self.assertTrue(PINE_PATH.exists())
        self.assertIn("//@version=6", source)
        self.assertIn("indicator(", source)
        self.assertIn('"LP + Force Strike"', source)
        self.assertIn('"LPFS"', source)
        self.assertIn("overlay = true", source)
        self.assertNotIn("strategy(", source)
        self.assertEqual(source.count("("), source.count(")"))
        self.assertEqual(source.count("["), source.count("]"))

    def test_pine_defaults_match_current_lpfs_baseline(self) -> None:
        source = _pine_source()
        self.assertEqual(_input_int_default(source, "pivotStrength"), 3)
        self.assertEqual(_input_int_default(source, "maxBarsFromLpBreak"), 6)
        self.assertEqual(_input_int_default(source, "minTotalBarsInput"), 3)
        self.assertEqual(_input_int_default(source, "maxTotalBarsInput"), 6)
        self.assertEqual(_input_float_default(source, "entryZone"), 0.5)
        self.assertEqual(_input_float_default(source, "targetR"), 1.0)

    def test_pine_uses_lp_level_rule_shape(self) -> None:
        source = _pine_source()
        self.assertIn("pivotHigh > high[strength + distance]", source)
        self.assertIn("pivotHigh > high[strength - distance]", source)
        self.assertIn("pivotLow < low[strength + distance]", source)
        self.assertIn("pivotLow < low[strength - distance]", source)
        self.assertIn("low <= price", source)
        self.assertIn("high >= price", source)
        self.assertIn("seconds == 8 * 60 * 60", source)
        self.assertIn("days := 60", source)
        self.assertIn("seconds == 12 * 60 * 60", source)
        self.assertIn("days := 180", source)
        self.assertIn("days := 1460", source)

    def test_pine_uses_raw_force_strike_rule_shape(self) -> None:
        source = _pine_source()
        self.assertIn("barTwoInside = high[firstBabyOff] <= motherHigh and low[firstBabyOff] >= motherLow", source)
        self.assertIn("brokeLow := brokeLow or low[off] < motherLow", source)
        self.assertIn("brokeHigh := brokeHigh or high[off] > motherHigh", source)
        self.assertIn("closeInside = close[signalOff] >= motherLow and close[signalOff] <= motherHigh", source)
        self.assertIn("not (brokeLow and brokeHigh)", source)
        self.assertIn("f_is_bullish_bar(signalOff)", source)
        self.assertIn("f_is_bearish_bar(signalOff)", source)

    def test_pine_combines_lp_and_force_strike_selection_rules(self) -> None:
        source = _pine_source()
        self.assertIn("closeValidSide = foundSide > 0 ? close >= lpPrice : close <= lpPrice", source)
        self.assertIn("lpPrice < selectedLpPrice", source)
        self.assertIn("lpPrice > selectedLpPrice", source)
        self.assertIn("breakBar > selectedBreakBar", source)
        self.assertIn("barsFromBreak >= 1 and barsFromBreak <= maxBarsFromLpBreak", source)
        self.assertIn("array.remove(trapSides, selectedWindowIndex)", source)

    def test_pine_exposes_visuals_and_alerts(self) -> None:
        source = _pine_source()
        self.assertIn("plotshape(bullishLpfsSignal", source)
        self.assertIn("plotshape(bearishLpfsSignal", source)
        self.assertIn("box.new(", source)
        self.assertIn("selectedLpLine = line.new", source)
        self.assertIn("entryLine = line.new", source)
        self.assertIn("stopLine = line.new", source)
        self.assertIn("targetLine = line.new", source)
        self.assertIn("expiryLine = line.new", source)
        self.assertIn('alertcondition(bullishLpfsSignal, "Bullish LPFS Signal"', source)
        self.assertIn('alertcondition(bearishLpfsSignal, "Bearish LPFS Signal"', source)

    def test_pine_excludes_live_execution_behavior(self) -> None:
        source = _pine_source().lower()
        forbidden_terms = (
            "order_send",
            "order_check",
            "market_recovery",
            "metatrader",
            "telegram",
            "risk_bucket",
            "live_send",
        )
        for term in forbidden_terms:
            self.assertNotIn(term, source)

    def test_readme_documents_visual_boundary(self) -> None:
        self.assertTrue(README_PATH.exists())
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("Copy `lp_force_strike.pine` into TradingView", readme)
        self.assertIn("Python and MT5 remain the source of truth", readme)
        self.assertIn("Bullish LPFS signal", readme)
        self.assertIn("Bearish LPFS signal", readme)


if __name__ == "__main__":
    unittest.main()
