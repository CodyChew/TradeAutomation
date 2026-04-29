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

from lp_force_strike_strategy_lab import filter_trade_timeframes  # noqa: E402
from run_lp_force_strike_timeframe_mix_experiment import run_timeframe_mix_analysis  # noqa: E402


def _trade(
    symbol: str,
    timeframe: str,
    pivot_strength: int,
    entry: str,
    exit_time: str,
    net_r: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "pivot_strength": pivot_strength,
        "entry_time_utc": entry,
        "exit_time_utc": exit_time,
        "net_r": net_r,
    }


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _trade("EURUSD", "H4", 3, "2026-01-01", "2026-01-02", 1.0),
            _trade("GBPUSD", "H8", 3, "2026-01-02", "2026-01-03", -1.0),
            _trade("USDJPY", "H12", 3, "2026-01-03", "2026-01-04", 1.0),
            _trade("AUDUSD", "D1", 4, "2026-01-04", "2026-01-05", 1.0),
            _trade("USDCAD", "W1", 5, "2026-01-05", "2026-01-06", 1.0),
        ]
    )


def _config() -> dict[str, object]:
    return {
        "main_pivot_strength": 3,
        "diagnostic_pivot_strengths": [4, 5],
        "diagnostic_timeframe_set_ids": ["all"],
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
                "timeframe_set_id": "h8_h12",
                "timeframe_set_label": "H8+H12",
                "timeframes": ["H8", "H12"],
            },
            {
                "timeframe_set_id": "all",
                "timeframe_set_label": "All",
                "timeframes": ["H4", "H8", "H12", "D1", "W1"],
            },
        ],
    }


class TimeframeMixTests(unittest.TestCase):
    def test_filter_trade_timeframes_includes_selected_and_excludes_others(self) -> None:
        filtered = filter_trade_timeframes(_frame(), ["H8", "H12"])

        self.assertEqual(set(filtered["timeframe"]), {"H8", "H12"})
        self.assertNotIn("H4", set(filtered["timeframe"]))

    def test_timeframe_mix_rows_mark_main_and_diagnostic_roles(self) -> None:
        summary, _accepted = run_timeframe_mix_analysis(_frame(), _config())

        main_rows = summary[summary["row_role"] == "main"]
        diagnostic_rows = summary[summary["row_role"] == "diagnostic"]

        self.assertEqual(set(main_rows["pivot_strength"]), {3})
        self.assertEqual(set(diagnostic_rows["pivot_strength"]), {4, 5})
        self.assertEqual(set(diagnostic_rows["timeframe_set_id"]), {"all"})

    def test_timeframe_mix_filters_each_row_before_portfolio_selection(self) -> None:
        summary, accepted = run_timeframe_mix_analysis(_frame(), _config())

        h8_h12_summary = summary[
            (summary["timeframe_set_id"] == "h8_h12") & (summary["pivot_strength"] == 3)
        ].iloc[0]
        h8_h12_accepted = accepted[
            (accepted["timeframe_set_id"] == "h8_h12") & (accepted["pivot_strength"] == 3)
        ]

        self.assertEqual(h8_h12_summary["trades_available"], 2)
        self.assertEqual(set(h8_h12_accepted["timeframe"]), {"H8", "H12"})

    def test_v11_all_timeframe_lp3_reproduces_v10_baseline(self) -> None:
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
                "timeframes": ["H4", "H8", "H12", "D1", "W1"],
            }
        ]
        trades = pd.read_csv(trades_path)

        summary, _accepted = run_timeframe_mix_analysis(trades, config)
        baseline = summary[(summary["timeframe_set_id"] == "all") & (summary["pivot_strength"] == 3)].iloc[0]

        self.assertEqual(int(baseline["trades_accepted"]), 10037)
        self.assertAlmostEqual(float(baseline["total_net_r"]), 1100.9405, places=3)
        self.assertAlmostEqual(float(baseline["max_drawdown_r"]), 26.7175, places=3)
        self.assertAlmostEqual(float(baseline["longest_underwater_days"]), 162.0, places=3)


if __name__ == "__main__":
    unittest.main()
