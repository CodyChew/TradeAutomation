from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
for src_root in [
    SRC_ROOT,
    SCRIPTS_ROOT,
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from run_lp_force_strike_pivot_finalization_experiment import run_pivot_finalization_analysis  # noqa: E402


def _frame() -> pd.DataFrame:
    rows = []
    for pivot_strength in (3, 4, 5):
        rows.append(
            {
                "symbol": f"EURUSD{pivot_strength}",
                "timeframe": "H4",
                "pivot_strength": pivot_strength,
                "entry_time_utc": "2026-01-01",
                "exit_time_utc": "2026-01-02",
                "net_r": float(pivot_strength),
            }
        )
        rows.append(
            {
                "symbol": f"GBPUSD{pivot_strength}",
                "timeframe": "H8",
                "pivot_strength": pivot_strength,
                "entry_time_utc": "2026-01-03",
                "exit_time_utc": "2026-01-04",
                "net_r": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _config() -> dict[str, object]:
    return {
        "pivot_strengths": [3, 4, 5],
        "max_drawdown_guardrail_r": 30.0,
        "max_underwater_guardrail_days": 180.0,
        "portfolio_rule": {
            "portfolio_id": "cap_4r",
            "max_open_r": 4.0,
            "enforce_one_per_symbol": True,
            "risk_r_per_trade": 1.0,
        },
        "timeframe_sets": [
            {
                "timeframe_set_id": "all",
                "timeframe_set_label": "All",
                "row_role": "main",
                "timeframes": ["H4", "H8"],
            },
            {
                "timeframe_set_id": "no_h4",
                "timeframe_set_label": "No H4",
                "row_role": "diagnostic",
                "timeframes": ["H8"],
            },
        ],
    }


class PivotFinalizationTests(unittest.TestCase):
    def test_pivot_finalization_marks_all_rows_main_and_no_h4_rows_diagnostic(self) -> None:
        summary, _accepted = run_pivot_finalization_analysis(_frame(), _config())

        all_rows = summary[summary["timeframe_set_id"] == "all"]
        no_h4_rows = summary[summary["timeframe_set_id"] == "no_h4"]

        self.assertEqual(set(all_rows["row_role"]), {"main"})
        self.assertEqual(set(no_h4_rows["row_role"]), {"diagnostic"})
        self.assertEqual(set(all_rows["pivot_strength"]), {3, 4, 5})

    def test_pivot_finalization_filters_diagnostic_timeframes_before_selection(self) -> None:
        summary, accepted = run_pivot_finalization_analysis(_frame(), _config())

        no_h4_summary = summary[(summary["timeframe_set_id"] == "no_h4") & (summary["pivot_strength"] == 3)].iloc[0]
        no_h4_accepted = accepted[(accepted["timeframe_set_id"] == "no_h4") & (accepted["pivot_strength"] == 3)]

        self.assertEqual(no_h4_summary["trades_available"], 1)
        self.assertEqual(set(no_h4_accepted["timeframe"]), {"H8"})

    def test_v12_lp3_all_timeframe_reproduces_v10_baseline(self) -> None:
        trades_path = (
            WORKSPACE_ROOT
            / "reports"
            / "strategies"
            / "lp_force_strike_experiment_v9_lp_pivot_strength"
            / "20260429_123831"
            / "trades.csv"
        )
        if not trades_path.exists():
            self.skipTest("V9 local trade log is not available.")

        config = _config()
        config["timeframe_sets"] = [
            {
                "timeframe_set_id": "all",
                "timeframe_set_label": "All",
                "row_role": "main",
                "timeframes": ["H4", "H8", "H12", "D1", "W1"],
            }
        ]
        trades = pd.read_csv(trades_path)

        summary, _accepted = run_pivot_finalization_analysis(trades, config)
        baseline = summary[(summary["timeframe_set_id"] == "all") & (summary["pivot_strength"] == 3)].iloc[0]

        self.assertEqual(int(baseline["trades_accepted"]), 10037)
        self.assertAlmostEqual(float(baseline["total_net_r"]), 1100.9405, places=3)
        self.assertAlmostEqual(float(baseline["max_drawdown_r"]), 26.7175, places=3)
        self.assertAlmostEqual(float(baseline["longest_underwater_days"]), 162.0, places=3)


if __name__ == "__main__":
    unittest.main()
