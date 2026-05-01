from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    WORKSPACE_ROOT / "scripts",
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from run_lp_force_strike_v17_lp_fs_proximity import (  # noqa: E402
    _compare_variant_to_baseline,
    _decision,
    _variant_frames,
)
from lp_force_strike_strategy_lab import add_proximity_columns  # noqa: E402


def _row(symbol: str, signal_index: int, net_r: float, *, gap_atr: float = 0.0) -> dict:
    lp = 1.1000
    atr = 0.0100
    structure_low = lp - 0.001 if gap_atr == 0.0 else lp + atr * gap_atr
    return {
        "symbol": symbol,
        "timeframe": "H4",
        "side": "long",
        "signal_index": signal_index,
        "pivot_strength": 3,
        "base_candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
        "net_r": net_r,
        "bars_held": 3,
        "exit_reason": "target" if net_r > 0 else "stop",
        "meta_lp_price": lp,
        "meta_structure_low": structure_low,
        "meta_structure_high": 1.1200,
        "meta_atr": atr,
    }


class V17LPFSProximityReportTests(unittest.TestCase):
    def test_variant_frames_filter_by_proximity(self) -> None:
        baseline = add_proximity_columns(
            pd.DataFrame(
                [
                    _row("EURUSD", 10, 1.0, gap_atr=0.0),
                    _row("GBPUSD", 20, -1.0, gap_atr=0.30),
                    _row("AUDUSD", 30, 1.0, gap_atr=1.20),
                ]
            )
        )

        frames = _variant_frames(baseline, ["current_v15", "strict_touch", "gap_0p50_atr", "gap_1p00_atr"])

        self.assertEqual(len(frames["current_v15"]), 3)
        self.assertEqual(len(frames["strict_touch"]), 1)
        self.assertEqual(len(frames["gap_0p50_atr"]), 2)
        self.assertEqual(len(frames["gap_1p00_atr"]), 2)

    def test_old_vs_filtered_delta_counts_exclusions(self) -> None:
        baseline = add_proximity_columns(pd.DataFrame([_row("EURUSD", 10, 1.0), _row("GBPUSD", 20, -1.0)]))
        variant = baseline.iloc[[0]].copy()

        delta = _compare_variant_to_baseline(baseline, variant, "strict_touch")

        self.assertEqual(delta["variant_trades"], 1)
        self.assertEqual(delta["excluded_from_variant"], 1)
        self.assertEqual(delta["trade_count_cut_pct"], 50.0)
        self.assertEqual(delta["total_net_r_delta"], 1.0)
        self.assertEqual(delta["excluded_net_r"], -1.0)

    def test_decision_keeps_current_when_best_filter_cuts_too_many_trades(self) -> None:
        delta = pd.DataFrame(
            [
                {"proximity_variant_id": "current_v15", "trade_count_cut_pct": 0.0},
                {"proximity_variant_id": "strict_touch", "trade_count_cut_pct": 30.0},
            ]
        )
        bucket_summary = pd.DataFrame(
            [
                {
                    "proximity_variant_id": "current_v15",
                    "efficient_passes_practical_filters": True,
                    "efficient_return_to_reserved_drawdown": 40.0,
                    "efficient_total_return_pct": 100.0,
                },
                {
                    "proximity_variant_id": "strict_touch",
                    "efficient_passes_practical_filters": True,
                    "efficient_return_to_reserved_drawdown": 50.0,
                    "efficient_total_return_pct": 95.0,
                },
            ]
        )

        decision, best = _decision(delta, bucket_summary, {"max_trade_count_cut_pct": 20.0, "max_total_return_drop_pct": 10.0})

        self.assertEqual(best["proximity_variant_id"], "strict_touch")
        self.assertEqual(decision["headline"], "Do not add a hard proximity filter yet.")


if __name__ == "__main__":
    unittest.main()
