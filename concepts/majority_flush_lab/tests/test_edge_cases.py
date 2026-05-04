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

from majority_flush_lab import MajorityFlushConfig, detect_majority_flushes  # noqa: E402


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    data = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    data.insert(0, "time_utc", [str(item) for item in times])
    return data


def _stagnation_base(tail: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return _frame(
        [
            (15.0, 16.0, 14.0, 15.5),
            (13.0, 15.0, 10.0, 14.0),
            (14.0, 15.0, 13.0, 14.5),
            (18.0, 20.0, 16.0, 17.0),
            *tail,
        ]
    )


class MajorityFlushEdgeCaseTests(unittest.TestCase):
    def test_empty_frame_returns_no_moves(self) -> None:
        frame = pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])

        self.assertEqual(detect_majority_flushes(frame, "D1"), [])

    def test_missing_columns_raise_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required columns: close, open"):
            detect_majority_flushes(pd.DataFrame({"time_utc": [], "high": [], "low": []}), "D1")

    def test_invalid_pivot_strength_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "pivot_strength"):
            detect_majority_flushes(
                pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"]),
                "D1",
                config=MajorityFlushConfig(pivot_strength=0),
            )

    def test_invalid_constipated_ratio_raises(self) -> None:
        frame = pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])
        with self.assertRaisesRegex(ValueError, "max_constipated_bar_ratio"):
            detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(max_constipated_bar_ratio=1.1))

    def test_zero_range_frame_returns_no_moves(self) -> None:
        frame = _frame([(10.0, 10.0, 10.0, 10.0), (10.0, 10.0, 10.0, 10.0), (10.0, 10.0, 10.0, 10.0)])

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_equal_origin_high_is_not_valid_origin(self) -> None:
        frame = _frame(
            [
                (15.0, 20.0, 14.0, 15.5),
                (19.0, 20.0, 16.0, 17.0),
                (17.0, 18.0, 9.0, 10.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_two_no_progress_candles_before_force_reject_leg(self) -> None:
        frame = _stagnation_base(
            [
                (17.0, 19.0, 13.0, 15.0),
                (15.0, 18.0, 13.5, 16.0),
                (16.0, 17.0, 13.2, 15.0),
                (15.0, 16.0, 9.5, 10.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_two_inside_bars_before_force_reject_leg(self) -> None:
        frame = _stagnation_base(
            [
                (17.0, 19.0, 13.0, 15.0),
                (15.0, 18.0, 13.5, 16.0),
                (16.0, 17.0, 14.0, 15.0),
                (15.0, 16.0, 9.5, 10.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_small_downside_leg_is_rejected_when_too_much_of_it_is_congested(self) -> None:
        frame = _stagnation_base(
            [
                (15.0, 19.0, 13.0, 16.0),
                (14.0, 18.0, 12.5, 15.0),
                (15.0, 16.0, 9.5, 10.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_small_upside_leg_is_rejected_when_too_much_of_it_is_congested(self) -> None:
        frame = _frame(
            [
                (13.0, 16.0, 12.0, 13.5),
                (15.0, 18.0, 13.0, 14.0),
                (14.0, 16.0, 12.0, 13.0),
                (11.0, 15.0, 10.0, 14.0),
                (13.0, 16.0, 11.0, 12.0),
                (12.0, 15.0, 10.0, 11.0),
                (10.0, 12.0, 8.0, 9.0),
                (12.0, 15.0, 9.0, 11.0),
                (13.0, 15.5, 10.0, 12.0),
                (13.0, 19.0, 12.0, 18.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])

    def test_longer_leg_tolerates_some_congestion_when_ratio_is_allowed(self) -> None:
        frame = _stagnation_base(
            [
                (16.0, 19.0, 13.0, 17.0),
                (12.0, 13.0, 9.5, 10.0),
            ]
        )
        config = MajorityFlushConfig(pivot_strength=1, include_rejected=True, max_constipated_bar_ratio=0.75)

        moves = detect_majority_flushes(frame, "D1", config=config)

        self.assertEqual(len(moves), 1)
        forced = moves[0].forced_lps
        self.assertEqual([lp.price for lp in forced], [10.0])
        self.assertEqual(forced[0].constipated_bar_ratio, 0.5)
        self.assertTrue(forced[0].constipated_ratio_passed)

    def test_no_move_when_direction_does_not_start_after_origin(self) -> None:
        frame = _frame(
            [
                (11.0, 12.0, 8.0, 9.0),
                (9.0, 10.0, 6.0, 7.0),
                (7.0, 9.0, 7.0, 8.0),
                (8.0, 12.0, 7.0, 11.0),
            ]
        )

        self.assertEqual(detect_majority_flushes(frame, "D1", config=MajorityFlushConfig(pivot_strength=1)), [])


if __name__ == "__main__":
    unittest.main()
