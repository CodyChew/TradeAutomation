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

from market_data_lab import load_dataset_config  # noqa: E402

v22 = importlib.import_module("run_lp_force_strike_v22_lp_fs_separation")


class V22LPFSSeparationReportTests(unittest.TestCase):
    def test_v22_config_loads_without_changing_fx_universe(self) -> None:
        config = json.loads(
            (
                WORKSPACE_ROOT
                / "configs"
                / "strategies"
                / "lp_force_strike_experiment_v22_lp_fs_separation.json"
            ).read_text(encoding="utf-8")
        )
        fx = load_dataset_config(WORKSPACE_ROOT / config["dataset_config"])

        self.assertEqual(len(fx.symbols), 28)
        self.assertIn("EURUSD", fx.symbols)
        self.assertEqual(config["pivot_strength"], 3)
        self.assertEqual(config["timeframes"], ["H4", "H8", "H12", "D1", "W1"])
        self.assertEqual(config["docs_output_path"], "docs/v22.html")

    def test_revalidation_matrix_classifies_required_branches(self) -> None:
        matrix = v22._research_revalidation_matrix()
        lookup = dict(zip(matrix["research_branch"], matrix["classification"]))

        self.assertEqual(lookup["V9 full signal/trade generation"], "rerun_in_v22")
        self.assertEqual(lookup["V15 risk bucket sensitivity"], "rerun_in_v22")
        self.assertEqual(lookup["V16 bid/ask execution realism"], "rerun_in_v22")
        self.assertEqual(lookup["V17 LP/FS proximity"], "stale_until_rerun")
        self.assertEqual(lookup["V18/V19 TP-near exits"], "stale_until_rerun")
        self.assertEqual(lookup["V20 protection realism"], "stale_until_rerun")
        self.assertEqual(lookup["V21 crypto expansion"], "stale_before_crypto_live_planning")
        self.assertEqual(lookup["V1-V8 exploratory search history"], "historical_context_only")

    def test_overlap_audit_flags_duplicate_and_missing_joins(self) -> None:
        signals = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "signal_join_key": "EURUSD|H4|10|3",
                    "lp_pivot_index": 4,
                    "fs_mother_index": 4,
                    "lp_is_fs_mother": True,
                    "lp_inside_fs_formation": True,
                },
                {
                    "separation_variant_id": "control_current",
                    "signal_join_key": "EURUSD|H4|10|3",
                    "lp_pivot_index": 4,
                    "fs_mother_index": 4,
                    "lp_is_fs_mother": True,
                    "lp_inside_fs_formation": True,
                },
                {
                    "separation_variant_id": "exclude_lp_pivot_inside_fs",
                    "signal_join_key": "EURUSD|H4|20|3",
                    "lp_pivot_index": 3,
                    "fs_mother_index": 5,
                    "lp_is_fs_mother": False,
                    "lp_inside_fs_formation": False,
                },
            ]
        )
        trades = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "trade_key": "a",
                    "signal_join_key": "EURUSD|H4|10|3",
                },
                {
                    "separation_variant_id": "exclude_lp_pivot_inside_fs",
                    "trade_key": "b",
                    "signal_join_key": "EURUSD|H4|99|3",
                },
            ]
        )

        audit = v22._overlap_audit(trades, signals)
        lookup = {
            (row["separation_variant_id"], row["audit_check"]): row["count"]
            for _, row in audit.iterrows()
        }

        self.assertEqual(lookup[("control_current", "duplicate_signal_join_keys")], 1)
        self.assertEqual(lookup[("exclude_lp_pivot_inside_fs", "missing_trade_to_signal_joins")], 1)

    def test_html_report_contains_required_sections(self) -> None:
        comparison = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "separation_variant_label": "Current V15 signal rules",
                    "trades": 100,
                    "trade_delta_vs_control": 0,
                    "win_rate": 0.58,
                    "win_rate_delta_vs_control": 0.0,
                    "profit_factor": 1.26,
                    "pf_delta_vs_control": 0.0,
                    "total_net_r": 12.0,
                    "total_net_r_delta_vs_control": 0.0,
                    "avg_net_r": 0.12,
                    "avg_net_r_delta_vs_control": 0.0,
                    "target_exits": 58,
                    "stop_exits": 42,
                    "same_bar_stop_exits": 1,
                    "bucket_efficient_reserved_max_drawdown_pct": 8.0,
                    "bucket_efficient_return_to_reserved_drawdown": 40.0,
                    "bucket_efficient_worst_month_pct": -3.0,
                    "lp_mother_trades_removed": 0,
                },
                {
                    "separation_variant_id": "exclude_lp_pivot_inside_fs",
                    "separation_variant_label": "Require LP pivot before FS mother",
                    "trades": 90,
                    "trade_delta_vs_control": -10,
                    "win_rate": 0.59,
                    "win_rate_delta_vs_control": 0.01,
                    "profit_factor": 1.28,
                    "pf_delta_vs_control": 0.02,
                    "total_net_r": 11.5,
                    "total_net_r_delta_vs_control": -0.5,
                    "avg_net_r": 0.128,
                    "avg_net_r_delta_vs_control": 0.008,
                    "target_exits": 53,
                    "stop_exits": 37,
                    "same_bar_stop_exits": 1,
                    "bucket_efficient_reserved_max_drawdown_pct": 7.5,
                    "bucket_efficient_return_to_reserved_drawdown": 41.0,
                    "bucket_efficient_worst_month_pct": -2.8,
                    "lp_mother_trades_removed": 10,
                },
            ]
        )
        audit = pd.DataFrame(
            [
                {"separation_variant_id": "control_current", "audit_check": "duplicate_trade_keys", "count": 0, "status": "pass"},
                {"separation_variant_id": "control_current", "audit_check": "missing_trade_to_signal_joins", "count": 0, "status": "pass"},
            ]
        )
        breakdown = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "separation_variant_label": "Current",
                    "symbol": "EURUSD",
                    "timeframe": "H4",
                    "exit_year": 2024,
                    "trades": 10,
                    "win_rate": 0.6,
                    "total_net_r": 2.0,
                    "avg_net_r": 0.2,
                    "profit_factor": 1.4,
                    "return_to_drawdown_r": 2.0,
                }
            ]
        )
        bucket = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "trades": 100,
                    "efficient_schedule_id": "bucket_ltf0p20",
                    "efficient_total_return_pct": 20.0,
                    "efficient_reserved_max_drawdown_pct": 5.0,
                    "efficient_worst_month_pct": -2.0,
                    "efficient_return_to_reserved_drawdown": 4.0,
                }
            ]
        )
        execution = pd.DataFrame(
            [
                {
                    "separation_variant_id": "control_current",
                    "execution_variant_id": "bid_ask_buffer_0p00x",
                    "trades": 99,
                    "win_rate": 0.58,
                    "total_net_r": 12.1,
                    "avg_net_r": 0.122,
                    "profit_factor": 1.27,
                    "max_drawdown_r": 3.0,
                    "return_to_drawdown_r": 4.0,
                }
            ]
        )
        delta = pd.DataFrame(
            [
                {
                    "change_type": "removed_by_separation",
                    "symbol": "USDCHF",
                    "timeframe": "H4",
                    "side": "short",
                    "signal_index": 299,
                    "control_exit_reason": "target",
                    "control_net_r": 1.0,
                    "lp_pivot_index": 10,
                    "fs_mother_index": 10,
                    "fs_signal_index": 14,
                    "lp_is_fs_mother": True,
                    "lp_inside_fs_formation": True,
                }
            ]
        )
        decision = {
            "status": "design_valid_but_small_tradeoff",
            "headline": "The rule is conceptually cleaner.",
            "detail": "Small tradeoff.",
            "follow_up": "Inspect removed trades.",
        }

        html = v22._html_report(
            Path("reports/test"),
            decision=decision,
            comparison=comparison,
            overlap_audit=audit,
            symbol_summary=breakdown,
            timeframe_summary=breakdown,
            symbol_timeframe_summary=breakdown,
            year_breakdown=breakdown,
            bucket_summary=bucket,
            execution_summary=execution,
            delta=delta,
            revalidation=v22._research_revalidation_matrix(),
            run_summary={"datasets": 2, "failed_datasets": 0, "trades": 190, "signals": 200},
        )

        for text in [
            "LP + Force Strike V22 LP-FS Separation",
            "Decision Card",
            "Comparison Table",
            "Overlap Audit",
            "V15 Bucket Sensitivity Rerun",
            "V16 Bid/Ask Execution Realism",
            "Symbol Breakdown",
            "Timeframe Breakdown",
            "Year Breakdown",
            "Research Revalidation Matrix",
            "Follow-Up Section",
            "Removed Trade Samples",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, html)

    def test_runner_source_writes_required_artifacts_and_has_no_production_hooks(self) -> None:
        source = (WORKSPACE_ROOT / "scripts" / "run_lp_force_strike_v22_lp_fs_separation.py").read_text(encoding="utf-8")
        expected_artifacts = [
            "signals.csv",
            "trades.csv",
            "skipped.csv",
            "overlap_audit.csv",
            "summary_by_variant.csv",
            "old_vs_new_trade_delta.csv",
            "summary_by_symbol.csv",
            "summary_by_timeframe.csv",
            "summary_by_symbol_timeframe.csv",
            "year_breakdown.csv",
            "bucket_sensitivity_by_variant.csv",
            "execution_realism_by_variant.csv",
            "research_revalidation_matrix.csv",
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
            "Telegram",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
