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

v19 = importlib.import_module("run_lp_force_strike_v19_tp_near_robustness")


class V19TPNearRobustnessReportTests(unittest.TestCase):
    def test_variant_config_accepts_haircut_and_delay_fields(self) -> None:
        variants = v19._variants_from_config(
            {
                "tp_near_variants": [
                    {"variant_id": "control_bid_ask", "mode": "control"},
                    {
                        "variant_id": "close_pct_90_haircut_0p5x",
                        "mode": "close",
                        "threshold_value": 0.9,
                        "fill_haircut_spread_mult": 0.5,
                    },
                    {
                        "variant_id": "close_pct_95_delay_1bar",
                        "mode": "close",
                        "threshold_value": 0.95,
                        "activation_delay_bars": 1,
                    },
                ]
            }
        )

        self.assertEqual(variants[1].fill_haircut_spread_mult, 0.5)
        self.assertEqual(variants[2].activation_delay_bars, 1)

        with self.assertRaises(ValueError):
            v19._variants_from_config({"tp_near_variants": [{"variant_id": "close_pct_90", "mode": "close"}]})

    def test_decision_frame_marks_variant_candidate_when_all_gates_pass(self) -> None:
        summary = pd.DataFrame(
            [
                {"tp_near_variant_id": "control_bid_ask", "trades": 4, "total_net_r": 1000.0, "profit_factor": 1.2},
                {"tp_near_variant_id": "close_pct_90", "trades": 4, "total_net_r": 1300.0, "profit_factor": 1.5},
            ]
        )
        delta = pd.DataFrame(
            [
                {
                    "comparison_baseline": "control_bid_ask",
                    "tp_near_variant_id": "control_bid_ask",
                    "total_net_r_delta": 0.0,
                },
                {
                    "comparison_baseline": "control_bid_ask",
                    "tp_near_variant_id": "close_pct_90",
                    "total_net_r_delta": 300.0,
                },
            ]
        )
        outcomes = pd.DataFrame(
            [
                {"tp_near_variant_id": "close_pct_90", "outcome": "saved_from_stop", "trades": 3, "net_r_delta_vs_control": 300.0},
                {"tp_near_variant_id": "close_pct_90", "outcome": "sacrificed_full_tp", "trades": 1, "net_r_delta_vs_control": -100.0},
                {"tp_near_variant_id": "close_pct_90", "outcome": "same_bar_conflict", "trades": 0, "net_r_delta_vs_control": 0.0},
            ]
        )
        bucket = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "control_bid_ask",
                    "efficient_return_to_reserved_drawdown": 40.0,
                    "efficient_passes_practical_filters": True,
                },
                {
                    "tp_near_variant_id": "close_pct_90",
                    "efficient_return_to_reserved_drawdown": 60.0,
                    "efficient_passes_practical_filters": True,
                },
            ]
        )
        symbol_timeframe = pd.DataFrame(
            [
                {"tp_near_variant_id": "close_pct_90", "symbol": "EURUSD", "timeframe": "H4", "total_net_r_delta_vs_control": 150.0},
                {"tp_near_variant_id": "close_pct_90", "symbol": "GBPUSD", "timeframe": "D1", "total_net_r_delta_vs_control": 150.0},
            ]
        )
        years = pd.DataFrame(
            [
                {"tp_near_variant_id": "close_pct_90", "exit_year": 2024, "total_net_r_delta_vs_control": 100.0},
                {"tp_near_variant_id": "close_pct_90", "exit_year": 2025, "total_net_r_delta_vs_control": 100.0},
                {"tp_near_variant_id": "close_pct_90", "exit_year": 2026, "total_net_r_delta_vs_control": -10.0},
            ]
        )

        decision = v19._variant_decision_frame(
            summary,
            delta,
            outcomes,
            bucket,
            symbol_timeframe,
            years,
            {"min_stressed_r_delta": 250.0, "min_saved_to_sacrificed_r_ratio": 2.0},
        )
        row = decision[decision["tp_near_variant_id"].eq("close_pct_90")].iloc[0]

        self.assertTrue(bool(row["live_candidate"]))
        self.assertAlmostEqual(float(row["saved_to_sacrificed_r_ratio"]), 3.0)
        self.assertEqual(row["stress_family"], "clean_close")

    def test_html_report_contains_dashboard_decision_and_follow_up_sections(self) -> None:
        decision_frame = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "close_pct_90",
                    "stress_family": "clean_close",
                    "trades": 10,
                    "total_net_r_delta": 300.0,
                    "profit_factor": 1.4,
                    "profit_factor_delta_vs_control": 0.1,
                    "saved_from_stop_r_delta": 400.0,
                    "sacrificed_full_tp_r_delta": -100.0,
                    "saved_to_sacrificed_r_ratio": 4.0,
                    "same_bar_conflict_trades": 0,
                    "efficient_return_to_reserved_drawdown": 60.0,
                    "live_candidate": True,
                    "efficient_reserved_max_drawdown_pct": 5.0,
                    "efficient_worst_month_pct": -2.0,
                }
            ]
        )
        outcomes = pd.DataFrame([{"tp_near_variant_id": "close_pct_90", "outcome": "saved_from_stop", "trades": 3}])
        symbol_timeframe = pd.DataFrame(
            [{"tp_near_variant_id": "close_pct_90", "symbol": "EURUSD", "timeframe": "H4", "trades": 2, "total_net_r_delta_vs_control": 10.0, "total_net_r": 20.0, "profit_factor": 1.5}]
        )
        years = pd.DataFrame(
            [{"tp_near_variant_id": "close_pct_90", "exit_year": 2026, "trades": 2, "total_net_r_delta_vs_control": 10.0, "total_net_r": 20.0}]
        )
        stress = pd.DataFrame(
            [{"base_stress_variant_id": "close_pct_90", "stress_family": "clean_close", "tp_near_variant_id": "close_pct_90", "trades": 10, "total_net_r_delta": 300.0, "profit_factor": 1.4, "exit_reason_changed": 3}]
        )
        samples = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "close_pct_90",
                    "outcome": "saved_from_stop",
                    "symbol": "EURUSD",
                    "timeframe": "H4",
                    "side": "long",
                    "signal_index": 1,
                    "control_exit_reason": "stop",
                    "control_net_r": -1.0,
                    "variant_exit_reason": "tp_near_close",
                    "variant_net_r": 0.9,
                    "net_r_delta_vs_control": 1.9,
                }
            ]
        )
        run_summary = {
            "decision": {
                "headline": "close_pct_90 is the strongest V19 live-design candidate.",
                "detail": "passed",
                "follow_up": "design live mechanics",
            },
            "best_variant": {
                "tp_near_variant_id": "close_pct_90",
                "total_net_r_delta": 300.0,
                "profit_factor": 1.4,
                "efficient_return_to_reserved_drawdown": 60.0,
                "efficient_reserved_max_drawdown_pct": 5.0,
                "efficient_worst_month_pct": -2.0,
                "live_candidate": True,
            },
        }

        html = v19._html_report(Path("reports/test"), decision_frame, outcomes, symbol_timeframe, years, stress, samples, run_summary)

        self.assertIn("LP + Force Strike V19 TP-Near Robustness", html)
        self.assertIn("Decision Card", html)
        self.assertIn("Variant Ranking And Gates", html)
        self.assertIn("Symbol / Timeframe Winners And Losers", html)
        self.assertIn("Year-By-Year Stability", html)
        self.assertIn("Changed-Trade Samples", html)
        self.assertIn("Follow-Up Recommendation", html)

    def test_runner_source_writes_required_artifacts_and_has_no_live_hooks(self) -> None:
        source = (WORKSPACE_ROOT / "scripts" / "run_lp_force_strike_v19_tp_near_robustness.py").read_text(encoding="utf-8")
        expected_artifacts = [
            "trades.csv",
            "summary_by_variant.csv",
            "old_vs_new_trade_delta.csv",
            "tp_near_outcome_breakdown.csv",
            "symbol_timeframe_breakdown.csv",
            "year_breakdown.csv",
            "stress_sensitivity.csv",
            "changed_trade_samples.csv",
            "run_summary.json",
            "dashboard.html",
        ]
        for artifact in expected_artifacts:
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, source)

        forbidden = [
            "live_executor",
            "run_lp_force_strike_live_executor",
            "order_send",
            "config.local",
            "lpfs_live_state",
            "lpfs_live_journal",
            "MetaTrader5",
            "TelegramNotifier",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
