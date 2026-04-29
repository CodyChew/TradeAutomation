from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from run_lp_force_strike_experiment import (  # noqa: E402
    _report_candidate_id,
    _selected_pivot_strengths,
    _summary_rows_from_report_rows,
)


class ExperimentRunnerTests(unittest.TestCase):
    def test_selected_pivot_strengths_supports_single_legacy_value(self) -> None:
        self.assertEqual(_selected_pivot_strengths({"pivot_strength": 3}), [3])

    def test_selected_pivot_strengths_supports_grid_values(self) -> None:
        self.assertEqual(_selected_pivot_strengths({"pivot_strengths": [2, "4", 5]}), [2, 4, 5])

    def test_report_candidate_id_only_prefixes_when_requested(self) -> None:
        candidate_id = "signal_zone_0p5_pullback__fs_structure__1r"

        self.assertEqual(_report_candidate_id(candidate_id, 4, include_pivot=False), candidate_id)
        self.assertEqual(
            _report_candidate_id(candidate_id, 4, include_pivot=True),
            "lp_pivot_4__signal_zone_0p5_pullback__fs_structure__1r",
        )

    def test_summary_rows_from_report_rows_groups_by_pivot_strength(self) -> None:
        rows = [
            {"pivot_strength": 2, "candidate_id": "a", "net_r": 1.0, "bars_held": 2, "exit_reason": "target"},
            {"pivot_strength": 2, "candidate_id": "a", "net_r": -1.0, "bars_held": 1, "exit_reason": "stop"},
            {"pivot_strength": 5, "candidate_id": "b", "net_r": 0.5, "bars_held": 3, "exit_reason": "target"},
        ]

        summary = _summary_rows_from_report_rows(rows, group_fields=["pivot_strength"])
        by_pivot = {row["pivot_strength"]: row for row in summary}

        self.assertEqual(by_pivot[2]["trades"], 2)
        self.assertEqual(by_pivot[2]["wins"], 1)
        self.assertEqual(by_pivot[2]["losses"], 1)
        self.assertEqual(by_pivot[2]["avg_net_r"], 0.0)
        self.assertEqual(by_pivot[2]["profit_factor"], 1.0)
        self.assertEqual(by_pivot[5]["trades"], 1)
        self.assertEqual(by_pivot[5]["profit_factor"], None)


if __name__ == "__main__":
    unittest.main()
