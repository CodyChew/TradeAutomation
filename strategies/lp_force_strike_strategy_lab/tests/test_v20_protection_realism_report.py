from __future__ import annotations

import importlib
import json
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

v20 = importlib.import_module("run_lp_force_strike_v20_protection_realism")


class V20ProtectionRealismReportTests(unittest.TestCase):
    def test_variant_config_accepts_delay_min_stop_and_retry_fields(self) -> None:
        variants = v20._variants_from_config(
            {
                "protection_variants": [
                    {"variant_id": "control_bid_ask", "mode": "control"},
                    {
                        "variant_id": "lock_0p50r_pct_90_m30_minstop_1x",
                        "mode": "lock_r_protect",
                        "threshold_r": 0.9,
                        "lock_r": 0.5,
                        "activation_delay_m30_bars": 1,
                        "activation_model": "next_m30_open",
                        "min_stop_distance_spread_mult": 1.0,
                        "retry_rejected_modification": True,
                    },
                ]
            }
        )

        self.assertEqual(variants[1].threshold_r, 0.9)
        self.assertEqual(variants[1].lock_r, 0.5)
        self.assertEqual(variants[1].activation_delay_m30_bars, 1)
        self.assertEqual(variants[1].activation_model, "next_m30_open")
        self.assertEqual(variants[1].min_stop_distance_spread_mult, 1.0)
        self.assertTrue(variants[1].retry_rejected_modification)

        with self.assertRaises(ValueError):
            v20._variants_from_config({"protection_variants": [{"variant_id": "lock", "mode": "lock_r_protect"}]})

    def test_config_includes_m30_replay_and_no_hard_close_variants(self) -> None:
        config = json.loads(
            (WORKSPACE_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v20_protection_realism.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(config["replay_timeframe"], "M30")
        self.assertEqual(config["target_r"], 1.0)
        self.assertTrue(all(item["mode"] != "close" for item in config["protection_variants"]))
        self.assertTrue(any(item["variant_id"] == "lock_0p50r_pct_90_m30_next" for item in config["protection_variants"]))
        self.assertTrue(any(item["variant_id"] == "lock_0p50r_pct_90_m30_same_assumed" for item in config["protection_variants"]))

    def test_protection_funnel_counts_triggers_activations_and_rejections(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "meta_tp_near_triggered": True,
                    "meta_protection_activated": True,
                    "meta_protection_activation_status": "activated",
                    "exit_reason": "tp_near_lock_stop",
                },
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "meta_tp_near_triggered": True,
                    "meta_protection_activated": False,
                    "meta_protection_activation_status": "rejected_too_late",
                    "exit_reason": "stop",
                },
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "meta_tp_near_triggered": False,
                    "meta_protection_activated": False,
                    "meta_protection_activation_status": "not_triggered",
                    "exit_reason": "target",
                },
            ]
        )

        funnel = v20._protection_funnel(trades)
        row = funnel.iloc[0]

        self.assertEqual(row["triggered"], 2)
        self.assertEqual(row["activated"], 1)
        self.assertAlmostEqual(row["activation_rate_of_triggers"], 0.5)
        self.assertEqual(row["rejected_too_late"], 1)
        self.assertEqual(row["protected_stop_exits"], 1)

    def test_html_report_contains_v20_decision_funnel_and_rules(self) -> None:
        decision_frame = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "stress_family": "next_m30_bar_lock",
                    "trades": 10,
                    "total_net_r_delta": 300.0,
                    "profit_factor": 1.4,
                    "profit_factor_delta_vs_control": 0.1,
                    "activation_rate_of_triggers": 0.8,
                    "rejected_too_late": 1,
                    "rejected_min_stop_distance": 0,
                    "saved_from_stop_r_delta": 400.0,
                    "sacrificed_full_tp_r_delta": -100.0,
                    "efficient_return_to_reserved_drawdown": 60.0,
                    "efficient_reserved_max_drawdown_pct": 5.0,
                    "efficient_worst_month_pct": -2.0,
                    "live_design_candidate": True,
                }
            ]
        )
        outcomes = pd.DataFrame([{"tp_near_variant_id": "lock_0p50r_pct_90_m30_next", "outcome": "saved_from_stop", "trades": 3}])
        funnel = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "triggered": 8,
                    "activated": 6,
                    "activation_rate_of_triggers": 0.75,
                    "rejected_too_late": 1,
                    "rejected_min_stop_distance": 1,
                    "protected_stop_exits": 3,
                }
            ]
        )
        symbol_timeframe = pd.DataFrame(
            [{"tp_near_variant_id": "lock_0p50r_pct_90_m30_next", "symbol": "EURUSD", "timeframe": "H4", "trades": 2, "total_net_r_delta_vs_control": 10.0, "profit_factor": 1.5}]
        )
        years = pd.DataFrame(
            [{"tp_near_variant_id": "lock_0p50r_pct_90_m30_next", "exit_year": 2026, "trades": 2, "total_net_r_delta_vs_control": 10.0, "total_net_r": 20.0}]
        )
        samples = pd.DataFrame(
            [
                {
                    "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                    "outcome": "saved_from_stop",
                    "symbol": "EURUSD",
                    "timeframe": "H4",
                    "side": "long",
                    "signal_index": 1,
                    "control_exit_reason": "stop",
                    "control_net_r": -1.0,
                    "variant_exit_reason": "tp_near_lock_stop",
                    "variant_net_r": 0.5,
                    "net_r_delta_vs_control": 1.5,
                }
            ]
        )
        run_summary = {
            "decision": {
                "headline": "lock_0p50r_pct_90_m30_next is the strongest V20 live-design candidate.",
                "detail": "passed",
                "follow_up": "design stop modification",
            },
            "best_variant": {
                "tp_near_variant_id": "lock_0p50r_pct_90_m30_next",
                "total_net_r_delta": 300.0,
                "activation_rate_of_triggers": 0.75,
                "efficient_reserved_max_drawdown_pct": 5.0,
                "efficient_worst_month_pct": -2.0,
                "live_design_candidate": True,
            },
        }

        html = v20._html_report(Path("reports/test"), decision_frame, outcomes, funnel, symbol_timeframe, years, samples, run_summary)

        self.assertIn("LP + Force Strike V20 Protection Realism", html)
        self.assertIn("Decision Card", html)
        self.assertIn("Protection Funnel", html)
        self.assertIn("fast 0.9R touch", html)
        self.assertIn("same-M30 assumed variant is an optimistic upper bound", html)
        self.assertIn("Follow-Up Recommendation", html)

    def test_runner_source_writes_required_artifacts_and_has_no_live_hooks(self) -> None:
        source = (WORKSPACE_ROOT / "scripts" / "run_lp_force_strike_v20_protection_realism.py").read_text(encoding="utf-8")
        expected_artifacts = [
            "trades.csv",
            "summary_by_variant.csv",
            "old_vs_new_trade_delta.csv",
            "protection_outcome_breakdown.csv",
            "protection_funnel.csv",
            "symbol_timeframe_breakdown.csv",
            "year_breakdown.csv",
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
