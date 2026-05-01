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

from run_lp_force_strike_v16_execution_realism import (  # noqa: E402
    _compare_variant_to_baseline,
    _decision,
)


def _row(symbol: str, signal_index: int, net_r: float, *, exit_reason: str = "target") -> dict:
    return {
        "symbol": symbol,
        "timeframe": "H4",
        "side": "long",
        "signal_index": signal_index,
        "pivot_strength": 3,
        "base_candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
        "net_r": net_r,
        "exit_reason": exit_reason,
    }


class V16ExecutionRealismReportTests(unittest.TestCase):
    def test_old_vs_new_delta_counts_missing_added_and_changed_exits(self) -> None:
        baseline = pd.DataFrame([_row("EURUSD", 10, 1.0), _row("GBPUSD", 20, -1.0, exit_reason="stop")])
        variant = pd.DataFrame([_row("EURUSD", 10, -1.0, exit_reason="stop"), _row("AUDUSD", 30, 2.0)])

        delta = _compare_variant_to_baseline(baseline, variant, "bid_ask_buffer_0x")

        self.assertEqual(delta["common_trades"], 1)
        self.assertEqual(delta["missing_from_variant"], 1)
        self.assertEqual(delta["added_in_variant"], 1)
        self.assertEqual(delta["exit_reason_changed"], 1)
        self.assertEqual(delta["win_loss_sign_changed"], 1)
        self.assertEqual(delta["total_net_r_delta"], 1.0)
        self.assertEqual(delta["common_net_r_delta"], -2.0)

    def test_decision_prefers_no_buffer_when_practical_and_not_materially_worse(self) -> None:
        no_buffer = {
            "baseline_total_net_r": 100.0,
            "total_net_r_delta": -5.0,
            "variant_trades": 95,
        }
        bucket_summary = pd.DataFrame(
            [
                {
                    "execution_variant_id": "bid_ask_buffer_0x",
                    "efficient_passes_practical_filters": True,
                    "efficient_return_to_reserved_drawdown": 50.0,
                    "efficient_total_return_pct": 100.0,
                    "efficient_reserved_max_drawdown_pct": 2.0,
                },
                {
                    "execution_variant_id": "bid_ask_buffer_1x",
                    "efficient_passes_practical_filters": True,
                    "efficient_return_to_reserved_drawdown": 40.0,
                    "efficient_total_return_pct": 90.0,
                    "efficient_reserved_max_drawdown_pct": 2.0,
                },
            ]
        )

        decision, best = _decision(no_buffer, bucket_summary, baseline_trade_count=100)

        self.assertEqual(best["execution_variant_id"], "bid_ask_buffer_0x")
        self.assertEqual(decision["headline"], "No stop buffer is currently favored.")


if __name__ == "__main__":
    unittest.main()
