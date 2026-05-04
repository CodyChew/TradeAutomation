from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PINE_PATH = PROJECT_ROOT / "tradingview" / "majority_flush.pine"


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


class MajorityFlushIndicatorTests(unittest.TestCase):
    def test_pine_indicator_file_has_expected_top_level_contract(self) -> None:
        source = _pine_source()
        self.assertTrue(PINE_PATH.exists())
        self.assertIn("//@version=6", source)
        self.assertIn("indicator(", source)
        self.assertIn('"Majority Flush"', source)
        self.assertIn("overlay = true", source)
        self.assertNotIn("strategy(", source)
        self.assertEqual(source.count("("), source.count(")"))
        self.assertEqual(source.count("["), source.count("]"))

    def test_pine_defaults_match_concept_plan(self) -> None:
        source = _pine_source()
        self.assertEqual(_input_int_default(source, "pivotStrengthInput"), 3)
        self.assertEqual(_input_float_default(source, "maxCongestedBarRatioInput"), 0.35)
        self.assertEqual(_input_int_default(source, "maxRetainedMovesInput"), 80)

    def test_pine_includes_full_leg_forced_lp_and_midpoint_visuals(self) -> None:
        source = _pine_source()
        self.assertIn("x1 = downsideOriginBarIndex", source)
        self.assertIn("line.set_x2(downsideFullLegLine", source)
        self.assertIn("line.set_x2(upsideFullLegLine", source)
        self.assertIn("forcedLpLine", source)
        self.assertIn("midpointGuideLine", source)
        self.assertIn("showMidpointGuidesInput", source)
        self.assertIn("showRejectedDiagnosticsInput", source)

    def test_pine_includes_congestion_ratio_filter(self) -> None:
        source = _pine_source()
        self.assertIn("downsideCongestedBarCount", source)
        self.assertIn("upsideCongestedBarCount", source)
        self.assertIn("downsideCongestedBarRatio <= maxCongestedBarRatioInput", source)
        self.assertIn("upsideCongestedBarRatio <= maxCongestedBarRatioInput", source)
        self.assertIn('text = midpointPassed ? "cong" : "50%"', source)

    def test_pine_alerts_for_both_sides(self) -> None:
        source = _pine_source()
        self.assertIn("alertcondition(downsideFlushSignal", source)
        self.assertIn("alertcondition(upsideFlushSignal", source)
        self.assertIn('"Downside Majority Flush"', source)
        self.assertIn('"Upside Majority Flush"', source)

    def test_pine_excludes_execution_terms(self) -> None:
        source = _pine_source().lower()
        forbidden = ["strategy(", "entry", "exit", "stop", "target", "risk", "mt5", "telegram", "live execution"]
        for term in forbidden:
            with self.subTest(term=term):
                self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main()
