from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from run_lp_force_strike_bucket_sensitivity_experiment import (  # noqa: E402
    _passes_practical_filters,
    expand_bucket_schedules,
)


class BucketSensitivityTests(unittest.TestCase):
    def test_expand_bucket_schedules_builds_cross_product(self) -> None:
        config = {
            "buckets": [
                {"bucket_id": "ltf", "label": "H4/H8", "timeframes": ["H4", "H8"], "risk_pct_values": [0.1, 0.2]},
                {"bucket_id": "h12_d1", "label": "H12/D1", "timeframes": ["H12", "D1"], "risk_pct_values": [0.3]},
                {"bucket_id": "w1", "label": "W1", "timeframes": ["W1"], "risk_pct_values": [0.45, 0.75]},
            ]
        }

        schedules = expand_bucket_schedules(config)

        self.assertEqual(len(schedules), 4)
        selected = schedules[0]
        self.assertEqual(selected["kind"], "timeframe")
        self.assertEqual(selected["risk_by_timeframe"]["H4"], selected["risk_by_timeframe"]["H8"])
        self.assertEqual(selected["risk_by_timeframe"]["H12"], selected["risk_by_timeframe"]["D1"])
        self.assertIn("W1", selected["risk_by_timeframe"])

    def test_practical_filters_require_all_thresholds(self) -> None:
        filters = {
            "max_reserved_drawdown_pct": 10.0,
            "max_reserved_open_risk_pct": 6.0,
            "min_worst_month_pct": -5.0,
        }
        base = {
            "reserved_max_drawdown_pct": 9.9,
            "max_reserved_open_risk_pct": 5.9,
            "worst_month_pct": -4.9,
        }

        self.assertTrue(_passes_practical_filters(base, filters))
        self.assertFalse(_passes_practical_filters({**base, "reserved_max_drawdown_pct": 10.1}, filters))
        self.assertFalse(_passes_practical_filters({**base, "max_reserved_open_risk_pct": 6.1}, filters))
        self.assertFalse(_passes_practical_filters({**base, "worst_month_pct": -5.1}, filters))


if __name__ == "__main__":
    unittest.main()
