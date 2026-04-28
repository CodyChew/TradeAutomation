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

from lp_force_strike_strategy_lab import StabilityFilter, run_stability_analysis, summarize_trades  # noqa: E402


def _trades() -> pd.DataFrame:
    rows = [
        ("c1", "EURUSD", "H4", "2020-01-01", 1.0),
        ("c1", "EURUSD", "H4", "2020-01-02", 1.0),
        ("c1", "GBPJPY", "H4", "2020-01-03", -1.0),
        ("c1", "GBPJPY", "H4", "2020-01-04", -1.0),
        ("c1", "EURUSD", "H4", "2024-01-01", 1.0),
        ("c1", "GBPJPY", "H4", "2024-01-02", 1.0),
        ("c2", "EURUSD", "D1", "2020-01-01", -1.0),
        ("c2", "EURUSD", "D1", "2024-01-01", 1.0),
    ]
    return pd.DataFrame(
        [
            {
                "candidate_id": candidate_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "entry_time_utc": time,
                "net_r": net_r,
                "bars_held": 1,
            }
            for candidate_id, symbol, timeframe, time, net_r in rows
        ]
    )


class StabilityTests(unittest.TestCase):
    def test_summarize_trades_returns_profit_factor(self) -> None:
        summary = summarize_trades(_trades(), ["candidate_id"])
        row = summary[summary["candidate_id"] == "c1"].iloc[0]

        self.assertEqual(row["trades"], 6)
        self.assertAlmostEqual(row["profit_factor"], 4.0 / 2.0)

    def test_stability_filter_is_learned_from_train_only(self) -> None:
        result = run_stability_analysis(
            _trades(),
            split_time_utc="2023-01-01T00:00:00Z",
            candidate_ids=["c1"],
            filters=[
                StabilityFilter("all", include_all_pairs=True),
                StabilityFilter("stable", min_trades=2, min_avg_net_r=0.0, min_profit_factor=1.0),
            ],
        )

        allowed = result.allowed_pairs[result.allowed_pairs["filter_id"] == "stable"]
        self.assertEqual(allowed[["symbol", "timeframe"]].drop_duplicates().to_dict("records"), [{"symbol": "EURUSD", "timeframe": "H4"}])

        test_rows = result.filter_results[
            (result.filter_results["candidate_id"] == "c1") & (result.filter_results["partition"] == "test")
        ].set_index("filter_id")
        self.assertEqual(test_rows.loc["all", "trades"], 2)
        self.assertEqual(test_rows.loc["stable", "trades"], 1)
        self.assertEqual(test_rows.loc["stable", "total_net_r"], 1.0)


if __name__ == "__main__":
    unittest.main()
