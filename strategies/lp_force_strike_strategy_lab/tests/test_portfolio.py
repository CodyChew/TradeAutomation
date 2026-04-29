from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for src_root in [
    SRC_ROOT,
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import (  # noqa: E402
    PortfolioRule,
    closed_trade_drawdown_metrics,
    run_portfolio_rule,
    select_portfolio_trades,
)


def _trades(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "pivot_strength": row.get("pivot_strength", 5),
                "entry_time_utc": pd.Timestamp(row["entry"], tz="UTC"),
                "exit_time_utc": pd.Timestamp(row["exit"], tz="UTC"),
                "net_r": row["net_r"],
            }
            for row in rows
        ]
    )


class PortfolioTests(unittest.TestCase):
    def test_uncapped_rule_accepts_all_trades(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H8", "entry": "2026-01-01", "exit": "2026-01-03", "net_r": -1.0},
            ]
        )

        selected, rejected = select_portfolio_trades(frame, PortfolioRule("take_all"))

        self.assertEqual(len(selected), 2)
        self.assertEqual(rejected["rejected_symbol_overlap"], 0)
        self.assertEqual(rejected["rejected_max_open_r"], 0)

    def test_max_open_r_rejects_trades_after_cap_is_full(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "USDJPY", "timeframe": "H4", "entry": "2026-01-03", "exit": "2026-01-05", "net_r": 1.0},
            ]
        )

        selected, rejected = select_portfolio_trades(frame, PortfolioRule("cap_2r", max_open_r=2.0))

        self.assertEqual(len(selected), 2)
        self.assertEqual(rejected["rejected_max_open_r"], 1)

    def test_one_per_symbol_rejects_overlapping_symbol_trade(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                {"symbol": "EURUSD", "timeframe": "H8", "entry": "2026-01-02", "exit": "2026-01-06", "net_r": 1.0},
            ]
        )

        selected, rejected = select_portfolio_trades(frame, PortfolioRule("one_symbol", enforce_one_per_symbol=True))

        self.assertEqual(len(selected), 1)
        self.assertEqual(rejected["rejected_symbol_overlap"], 1)

    def test_same_symbol_same_time_accepts_higher_timeframe_first(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-01", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "D1", "entry": "2026-01-01", "exit": "2026-01-03", "net_r": 1.0},
            ]
        )

        selected, rejected = select_portfolio_trades(frame, PortfolioRule("one_symbol", enforce_one_per_symbol=True))

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected.iloc[0]["timeframe"], "D1")
        self.assertEqual(rejected["rejected_symbol_overlap"], 1)

    def test_closed_trade_drawdown_tracks_max_dd_and_underwater(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-01", "net_r": 2.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-02", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-03", "exit": "2026-01-03", "net_r": -1.0},
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-05", "exit": "2026-01-05", "net_r": 2.0},
            ]
        )

        metrics = closed_trade_drawdown_metrics(frame)

        self.assertEqual(metrics["max_drawdown_r"], 2.0)
        self.assertEqual(metrics["longest_underwater_days"], 3.0)

    def test_run_portfolio_rule_returns_guardrail_result(self) -> None:
        frame = _trades(
            [
                {"symbol": "EURUSD", "timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-01", "net_r": 1.0},
                {"symbol": "GBPUSD", "timeframe": "H4", "entry": "2026-01-02", "exit": "2026-01-02", "net_r": -1.0},
            ]
        )

        result, selected = run_portfolio_rule(
            frame,
            rule=PortfolioRule("take_all"),
            pivot_strength=5,
            max_drawdown_guardrail_r=2.0,
            max_underwater_guardrail_days=10.0,
        )

        self.assertEqual(len(selected), 2)
        self.assertTrue(result.passed_guardrails)
        self.assertEqual(result.trades_available, 2)


if __name__ == "__main__":
    unittest.main()
