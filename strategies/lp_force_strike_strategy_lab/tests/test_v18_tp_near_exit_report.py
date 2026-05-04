from __future__ import annotations

import importlib
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
    WORKSPACE_ROOT / "shared" / "market_data_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

v18 = importlib.import_module("run_lp_force_strike_v18_tp_near_exit")


def _trade_row(variant_id: str, net_r: float, exit_reason: str, *, exit_index: int = 1) -> dict:
    return {
        "setup_id": f"setup__{variant_id}",
        "symbol": "GBPCAD",
        "timeframe": "H4",
        "side": "short",
        "signal_index": 10,
        "pivot_strength": 3,
        "base_candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
        "entry_index": 0,
        "exit_index": exit_index,
        "entry_time_utc": "2026-01-01 00:00:00+00:00",
        "exit_time_utc": "2026-01-01 04:00:00+00:00",
        "entry_reference_price": 100.0,
        "entry_fill_price": 100.0,
        "exit_reference_price": 95.0 if net_r > 0.99 else 95.25,
        "exit_fill_price": 95.0 if net_r > 0.99 else 95.25,
        "stop_price": 105.0,
        "target_price": 95.0,
        "risk_distance": 5.0,
        "reference_r": net_r,
        "fill_r": net_r,
        "commission_r": 0.0,
        "net_r": net_r,
        "bars_held": exit_index + 1,
        "exit_reason": exit_reason,
        "candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
        "tp_near_variant_id": variant_id,
        "tp_near_mode": "control" if variant_id == "control_bid_ask" else "close",
        "trade_key": "GBPCAD|H4|short|10|3|signal_zone_0p5_pullback__fs_structure__1r",
    }


class V18TPNearExitReportTests(unittest.TestCase):
    def test_variant_config_requires_control_first(self) -> None:
        config = {
            "tp_near_variants": [
                {"variant_id": "control_bid_ask", "mode": "control"},
                {"variant_id": "close_pct_95", "mode": "close", "threshold_value": 0.95},
            ]
        }
        variants = v18._variants_from_config(config)

        self.assertEqual([variant.variant_id for variant in variants], ["control_bid_ask", "close_pct_95"])

        with self.assertRaises(ValueError):
            v18._variants_from_config({"tp_near_variants": [{"variant_id": "close_pct_95", "mode": "close"}]})
        with self.assertRaises(ValueError):
            v18._variants_from_config({"tp_near_variants": []})

    def test_comparison_and_outcome_metrics_are_written_shapes(self) -> None:
        control = pd.DataFrame([_trade_row("control_bid_ask", 1.0, "target", exit_index=1)])
        close = pd.DataFrame([_trade_row("close_pct_95", 0.95, "tp_near_close", exit_index=0)])
        trades = pd.concat([control, close], ignore_index=True)

        delta = v18._compare_frames(control, close, "close_pct_95", "control_bid_ask")
        outcomes = pd.DataFrame(v18._tp_near_outcome_rows(trades))

        self.assertEqual(delta["exit_reason_changed"], 1)
        self.assertAlmostEqual(delta["total_net_r_delta"], -0.05)
        sacrificed = outcomes[
            outcomes["tp_near_variant_id"].eq("close_pct_95") & outcomes["outcome"].eq("sacrificed_full_tp")
        ].iloc[0]
        self.assertEqual(int(sacrificed["trades"]), 1)
        self.assertAlmostEqual(float(sacrificed["net_r_delta_vs_control"]), -0.05)

    def test_html_report_contains_v18_safety_and_metrics(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "control_bid_ask",
                    "trades": 1,
                    "total_net_r": 1.0,
                    "avg_net_r": 1.0,
                    "profit_factor": None,
                    "tp_near_close_exits": 0,
                    "tp_near_protect_exits": 0,
                }
            ]
        )
        delta = pd.DataFrame(
            [
                {
                    "comparison_baseline": "control_bid_ask",
                    "tp_near_variant_id": "control_bid_ask",
                    "exit_reason_changed": 0,
                    "total_net_r_delta": 0.0,
                }
            ]
        )
        outcomes = pd.DataFrame([{"tp_near_variant_id": "control_bid_ask", "outcome": "unchanged", "trades": 1}])
        bucket = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "control_bid_ask",
                    "efficient_schedule_id": "bucket_ltf0p2_h12_d10p3_w10p75",
                    "efficient_total_return_pct": 1.0,
                    "efficient_reserved_max_drawdown_pct": 1.0,
                    "efficient_max_reserved_open_risk_pct": 1.0,
                    "efficient_worst_month_pct": 0.0,
                    "efficient_return_to_reserved_drawdown": 1.0,
                    "efficient_passes_practical_filters": True,
                }
            ]
        )
        run_summary = {
            "decision": {"headline": "Keep TP handling unchanged for now.", "detail": "control wins"},
            "control_trade_count": 1,
            "variant_trade_rows": 1,
            "best_variant": {"tp_near_variant_id": "control_bid_ask"},
            "signals": 1,
        }

        html = v18._html_report(Path("reports/test"), summary, delta, outcomes, bucket, run_summary)

        self.assertIn("LP + Force Strike V18 TP-Near Exit", html)
        self.assertIn("Research-only", html)
        self.assertIn("Decision Brief", html)
        self.assertIn("TP-Near Variant Leaderboard", html)
        self.assertIn("TP-Near Outcome Breakdown", html)

    def test_runner_source_has_no_live_execution_hooks(self) -> None:
        source = (WORKSPACE_ROOT / "scripts" / "run_lp_force_strike_v18_tp_near_exit.py").read_text(encoding="utf-8")
        forbidden = [
            "live_executor",
            "run_lp_force_strike_live_executor",
            "order_send",
            "config.local",
            "lpfs_live_state",
            "lpfs_live_journal",
            "MetaTrader5",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
