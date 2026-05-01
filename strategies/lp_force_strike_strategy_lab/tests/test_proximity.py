from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import (  # noqa: E402
    add_proximity_columns,
    classify_lp_fs_proximity,
    proximity_variant_mask,
    proximity_variant_label,
)


class LPFSProximityTests(unittest.TestCase):
    def test_long_strict_touch_when_structure_low_crosses_lp(self) -> None:
        result = classify_lp_fs_proximity(
            side="long",
            lp_price=1.1000,
            structure_low=1.0995,
            structure_high=1.1200,
            atr=0.0100,
        )

        self.assertTrue(result.strict_touch)
        self.assertEqual(result.gap_price, 0.0)
        self.assertEqual(result.gap_atr, 0.0)
        self.assertEqual(result.quality_bucket, "touched")

    def test_long_gap_is_measured_above_support_lp(self) -> None:
        result = classify_lp_fs_proximity(
            side="long",
            lp_price=1.1000,
            structure_low=1.1025,
            structure_high=1.1200,
            atr=0.0100,
        )

        self.assertFalse(result.strict_touch)
        self.assertAlmostEqual(result.gap_price, 0.0025)
        self.assertAlmostEqual(result.gap_atr, 0.25)
        self.assertEqual(result.quality_bucket, "within_0p25_atr")

    def test_short_strict_touch_when_structure_high_crosses_resistance_lp(self) -> None:
        result = classify_lp_fs_proximity(
            side="short",
            lp_price=1.2000,
            structure_low=1.1700,
            structure_high=1.2010,
            atr=0.0100,
        )

        self.assertTrue(result.strict_touch)
        self.assertEqual(result.quality_bucket, "touched")

    def test_short_gap_is_measured_below_resistance_lp(self) -> None:
        result = classify_lp_fs_proximity(
            side="short",
            lp_price=1.2000,
            structure_low=1.1700,
            structure_high=1.1940,
            atr=0.0100,
        )

        self.assertFalse(result.strict_touch)
        self.assertAlmostEqual(result.gap_price, 0.0060)
        self.assertAlmostEqual(result.gap_atr, 0.60)
        self.assertEqual(result.quality_bucket, "within_1p00_atr")

    def test_missing_or_zero_atr_marks_non_touch_unknown(self) -> None:
        result = classify_lp_fs_proximity(
            side="long",
            lp_price=1.1000,
            structure_low=1.1020,
            structure_high=1.1200,
            atr=0.0,
        )

        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, "missing_or_zero_atr")
        self.assertEqual(result.quality_bucket, "unknown")
        self.assertIsNone(result.gap_atr)

    def test_invalid_inputs_are_classified_as_unknown(self) -> None:
        unsupported = classify_lp_fs_proximity(
            side="flat",
            lp_price=1.1000,
            structure_low=1.1010,
            structure_high=1.1200,
            atr=0.0100,
        )
        missing_lp = classify_lp_fs_proximity(
            side="long",
            lp_price="not-a-price",
            structure_low=1.1010,
            structure_high=1.1200,
            atr=0.0100,
        )
        missing_low = classify_lp_fs_proximity(
            side="long",
            lp_price=1.1000,
            structure_low=None,
            structure_high=1.1200,
            atr=0.0100,
        )
        missing_high = classify_lp_fs_proximity(
            side="short",
            lp_price=1.2000,
            structure_low=1.1700,
            structure_high=None,
            atr=0.0100,
        )

        self.assertEqual(unsupported.reason, "unsupported_side")
        self.assertEqual(missing_lp.reason, "missing_lp_price")
        self.assertEqual(missing_low.reason, "missing_structure_low")
        self.assertEqual(missing_high.reason, "missing_structure_high")
        for result in (unsupported, missing_lp, missing_low, missing_high):
            self.assertEqual(result.status, "unknown")
            self.assertEqual(result.quality_bucket, "unknown")
            self.assertIsNone(result.gap_price)

    def test_variant_masks_accept_expected_thresholds(self) -> None:
        frame = pd.DataFrame(
            [
                {"side": "long", "meta_lp_price": 1.1000, "meta_structure_low": 1.0990, "meta_structure_high": 1.1200, "meta_atr": 0.0100},
                {"side": "long", "meta_lp_price": 1.1000, "meta_structure_low": 1.1030, "meta_structure_high": 1.1200, "meta_atr": 0.0100},
                {"side": "long", "meta_lp_price": 1.1000, "meta_structure_low": 1.1075, "meta_structure_high": 1.1200, "meta_atr": 0.0100},
                {"side": "long", "meta_lp_price": 1.1000, "meta_structure_low": 1.1120, "meta_structure_high": 1.1200, "meta_atr": 0.0100},
                {"side": "long", "meta_lp_price": 1.1000, "meta_structure_low": 1.1020, "meta_structure_high": 1.1200, "meta_atr": None},
            ]
        )
        classified = add_proximity_columns(frame)

        self.assertEqual(proximity_variant_mask(classified, "current_v15").tolist(), [True, True, True, True, True])
        self.assertEqual(proximity_variant_mask(classified, "strict_touch").tolist(), [True, False, False, False, False])
        self.assertEqual(proximity_variant_mask(classified, "gap_0p50_atr").tolist(), [True, True, False, False, False])
        self.assertEqual(proximity_variant_mask(classified, "gap_1p00_atr").tolist(), [True, True, True, False, False])

    def test_empty_frames_and_unknown_variants_are_handled_cleanly(self) -> None:
        frame = pd.DataFrame(columns=["side", "meta_lp_price", "meta_structure_low", "meta_structure_high", "meta_atr"])
        classified = add_proximity_columns(frame)

        self.assertTrue(classified.empty)
        self.assertEqual(proximity_variant_mask(classified, "current_v15").tolist(), [])
        self.assertEqual(proximity_variant_label("made_up"), "made_up")
        with self.assertRaises(ValueError):
            proximity_variant_mask(classified, "made_up")


if __name__ == "__main__":
    unittest.main()
