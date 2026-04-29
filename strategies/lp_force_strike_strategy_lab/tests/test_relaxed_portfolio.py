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

from run_lp_force_strike_relaxed_portfolio_experiment import (  # noqa: E402
    exposure_metrics,
    period_robustness,
    run_relaxed_portfolio_analysis,
    ticker_robustness,
    top_underwater_periods,
)


def _trades(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "pivot_strength": row.get("pivot_strength", 3),
                "entry_time_utc": pd.Timestamp(row["entry"], tz="UTC"),
                "exit_time_utc": pd.Timestamp(row["exit"], tz="UTC"),
                "net_r": row["net_r"],
            }
            for row in rows
        ]
    )


def _config() -> dict:
    return {
        "pivot_strength": 3,
        "timeframes": ["H4", "H8", "D1"],
        "risk_per_trade_pct_examples": [0.25, 0.5],
        "concentration_warning_share": 1.0,
        "portfolio_rules": [
            {
                "portfolio_id": "take_all",
                "max_open_r": None,
                "enforce_one_per_symbol": False,
                "risk_r_per_trade": 1.0,
            },
            {
                "portfolio_id": "one_symbol_no_cap",
                "max_open_r": None,
                "enforce_one_per_symbol": True,
                "risk_r_per_trade": 1.0,
            },
            {
                "portfolio_id": "cap_16r",
                "max_open_r": 16.0,
                "enforce_one_per_symbol": True,
                "risk_r_per_trade": 1.0,
            },
        ],
    }


class RelaxedPortfolioTests(unittest.TestCase):
    def test_take_all_allows_same_symbol_stacking(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H8", "entry": "2026-01-02", "exit": "2026-01-06", "net_r": 1.0},
            ]
        )

        _summary, accepted, _symbols, _underwater, _yearly = run_relaxed_portfolio_analysis(frame, _config())

        take_all = accepted[accepted["portfolio_id"] == "take_all"]
        one_symbol = accepted[accepted["portfolio_id"] == "one_symbol_no_cap"]
        self.assertEqual(len(take_all), 2)
        self.assertEqual(exposure_metrics(take_all)["max_same_symbol_stack"], 2)
        self.assertEqual(len(one_symbol), 1)

    def test_one_symbol_no_cap_rejects_symbol_overlap_without_total_cap(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "USDJPY", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H8", "entry": "2026-01-02", "exit": "2026-01-06", "net_r": 1.0},
            ]
        )

        summary, accepted, _symbols, _underwater, _yearly = run_relaxed_portfolio_analysis(frame, _config())

        one_symbol_summary = summary[summary["portfolio_id"] == "one_symbol_no_cap"].iloc[0]
        one_symbol = accepted[accepted["portfolio_id"] == "one_symbol_no_cap"]
        self.assertEqual(int(one_symbol_summary["rejected_symbol_overlap"]), 1)
        self.assertEqual(int(one_symbol_summary["rejected_max_open_r"]), 0)
        self.assertEqual(len(one_symbol), 3)

    def test_wider_caps_preserve_higher_timeframe_priority(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "D1", "entry": "2026-01-01", "exit": "2026-01-03", "net_r": 1.0},
            ]
        )

        _summary, accepted, _symbols, _underwater, _yearly = run_relaxed_portfolio_analysis(frame, _config())

        selected = accepted[accepted["portfolio_id"] == "cap_16r"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected.iloc[0]["timeframe"], "D1")

    def test_period_robustness_counts_negative_years(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2025-01-01", "exit": "2025-01-02", "net_r": 2.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": -1.0},
                {"symbol": "USDJPY", "timeframe": "H4", "entry": "2026-02-01", "exit": "2026-02-02", "net_r": -1.0},
            ]
        )

        metrics = period_robustness(frame)

        self.assertEqual(metrics["negative_years"], 1)
        self.assertEqual(metrics["worst_year"], "2026")
        self.assertEqual(metrics["negative_months"], 2)

    def test_ticker_robustness_counts_negative_symbols(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": -1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": 2.0},
                {"symbol": "GBPUSD", "timeframe": "H8", "entry": "2026-01-03", "exit": "2026-01-04", "net_r": 1.0},
            ]
        )

        metrics, by_symbol = ticker_robustness(frame)

        self.assertEqual(metrics["negative_symbols"], 1)
        self.assertEqual(metrics["worst_symbol"], "EURUSD")
        self.assertEqual(metrics["best_symbol"], "GBPUSD")
        self.assertEqual(len(by_symbol), 2)

    def test_exposure_metrics_are_deterministic(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H8", "entry": "2026-01-02", "exit": "2026-01-06", "net_r": 1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-03", "net_r": 1.0},
            ]
        )

        metrics = exposure_metrics(frame)

        self.assertEqual(metrics["max_concurrent_trades"], 3)
        self.assertEqual(metrics["max_same_symbol_stack"], 2)
        self.assertEqual(metrics["max_new_trades_same_time"], 2)

    def test_top_underwater_periods_are_sorted_by_duration(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-01", "net_r": 3.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-02", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-05", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-08", "exit": "2026-01-08", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-10", "exit": "2026-01-10", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-11", "exit": "2026-01-11", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-12", "exit": "2026-01-12", "net_r": 1.0},
            ]
        )

        periods = top_underwater_periods(frame, limit=2)

        self.assertEqual(len(periods), 2)
        self.assertGreaterEqual(float(periods.iloc[0]["days"]), float(periods.iloc[1]["days"]))


if __name__ == "__main__":
    unittest.main()
