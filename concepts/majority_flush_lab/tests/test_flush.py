from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
LP_SRC_ROOT = REPO_ROOT / "concepts" / "lp_levels_lab" / "src"
for path in (SRC_ROOT, LP_SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from majority_flush_lab import ForcedLP, MajorityFlushConfig, MajorityFlushMove, detect_majority_flushes  # noqa: E402


def _frame(rows: list[tuple[float, float, float, float]], *, reverse: bool = False) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    data = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    data.insert(0, "time_utc", [str(item) for item in times])
    if reverse:
        return data.iloc[::-1].reset_index(drop=True)
    return data


def _downside_two_support_frame(*, flush_start_open: float = 19.0, reverse: bool = False) -> pd.DataFrame:
    return _frame(
        [
            (15.0, 16.0, 14.0, 15.5),
            (13.0, 15.0, 10.0, 14.0),
            (14.0, 15.0, 13.0, 14.5),
            (16.0, 17.0, 14.0, 15.0),
            (13.0, 16.0, 12.0, 15.0),
            (15.0, 17.0, 14.0, 16.0),
            (18.0, 20.0, 16.0, 17.0),
            (flush_start_open, 18.0, 13.0, 14.0),
            (14.0, 15.0, 9.5, 10.5),
        ],
        reverse=reverse,
    )


def _upside_two_resistance_frame(*, flush_start_open: float = 11.0) -> pd.DataFrame:
    return _frame(
        [
            (13.0, 16.0, 12.0, 13.5),
            (15.0, 18.0, 13.0, 14.0),
            (14.0, 16.0, 12.0, 13.0),
            (11.0, 15.0, 10.0, 14.0),
            (13.0, 16.0, 11.0, 12.0),
            (12.0, 15.0, 10.0, 11.0),
            (10.0, 12.0, 8.0, 9.0),
            (flush_start_open, 14.0, 9.0, 13.0),
            (13.0, 19.0, 12.0, 18.0),
        ]
    )


class MajorityFlushTests(unittest.TestCase):
    def test_public_exports_are_available(self) -> None:
        self.assertIs(ForcedLP.__name__, "ForcedLP")
        self.assertIs(MajorityFlushMove.__name__, "MajorityFlushMove")
        self.assertIs(MajorityFlushConfig.__name__, "MajorityFlushConfig")

    def test_detects_downside_flush_forcing_two_support_lps(self) -> None:
        moves = detect_majority_flushes(_downside_two_support_frame(), "D1", config=MajorityFlushConfig(pivot_strength=1))

        self.assertEqual(len(moves), 1)
        move = moves[0]
        self.assertEqual(move.side, "downside")
        self.assertEqual(move.origin_index, 6)
        self.assertEqual(move.flush_start_index, 7)
        self.assertEqual(move.completion_index, 8)
        self.assertEqual(move.duration_bars, 2)
        self.assertEqual(move.leg_high, 20.0)
        self.assertEqual(move.leg_low, 9.5)
        self.assertEqual(move.completion_price, 9.5)
        self.assertEqual([lp.price for lp in move.forced_lps], [12.0, 10.0])
        self.assertTrue(all(lp.lp_side == "support" for lp in move.forced_lps))
        self.assertTrue(all(lp.midpoint_passed for lp in move.forced_lps))
        self.assertTrue(all(lp.constipated_ratio_passed for lp in move.forced_lps))
        self.assertEqual([lp.constipated_bar_ratio for lp in move.forced_lps], [0.0, 0.0])

    def test_detects_upside_flush_forcing_two_resistance_lps(self) -> None:
        moves = detect_majority_flushes(_upside_two_resistance_frame(), "D1", config=MajorityFlushConfig(pivot_strength=1))

        self.assertEqual(len(moves), 1)
        move = moves[0]
        self.assertEqual(move.side, "upside")
        self.assertEqual(move.origin_index, 6)
        self.assertEqual(move.flush_start_index, 7)
        self.assertEqual(move.completion_index, 8)
        self.assertEqual(move.duration_bars, 2)
        self.assertEqual(move.leg_high, 19.0)
        self.assertEqual(move.leg_low, 8.0)
        self.assertEqual(move.completion_price, 19.0)
        self.assertEqual([lp.price for lp in move.forced_lps], [16.0, 18.0])
        self.assertTrue(all(lp.lp_side == "resistance" for lp in move.forced_lps))
        self.assertTrue(all(lp.midpoint_passed for lp in move.forced_lps))
        self.assertTrue(all(lp.constipated_ratio_passed for lp in move.forced_lps))

    def test_midpoint_rule_is_per_lp(self) -> None:
        config = MajorityFlushConfig(pivot_strength=1, include_rejected=True)
        moves = detect_majority_flushes(_downside_two_support_frame(flush_start_open=15.5), "D1", config=config)

        self.assertEqual(len(moves), 1)
        forced = moves[0].forced_lps
        self.assertEqual([lp.price for lp in forced], [12.0, 10.0])
        self.assertEqual([lp.midpoint for lp in forced], [16.0, 15.0])
        self.assertEqual([lp.midpoint_passed for lp in forced], [False, True])
        self.assertEqual(forced[0].invalidation_reason, "midpoint_failed")
        self.assertIsNone(forced[1].invalidation_reason)

    def test_default_output_excludes_midpoint_rejections(self) -> None:
        moves = detect_majority_flushes(_downside_two_support_frame(flush_start_open=15.5), "D1", config=MajorityFlushConfig(pivot_strength=1))

        self.assertEqual(len(moves), 1)
        self.assertEqual([lp.price for lp in moves[0].forced_lps], [10.0])

    def test_input_is_sorted_before_detection(self) -> None:
        moves = detect_majority_flushes(
            _downside_two_support_frame(reverse=True),
            "D1",
            config=MajorityFlushConfig(pivot_strength=1),
        )

        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].origin_index, 6)
        self.assertEqual([lp.price for lp in moves[0].forced_lps], [12.0, 10.0])

    def test_config_defaults_match_concept_plan(self) -> None:
        config = MajorityFlushConfig()

        self.assertEqual(config.pivot_strength, 3)
        self.assertFalse(config.include_rejected)
        self.assertEqual(config.max_constipated_bar_ratio, 0.35)


if __name__ == "__main__":
    unittest.main()
