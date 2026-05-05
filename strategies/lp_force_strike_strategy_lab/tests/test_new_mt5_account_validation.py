from __future__ import annotations

import csv
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from compare_lpfs_new_mt5_account_v22 import compare_runs  # noqa: E402


class LPFSNewMT5AccountValidationTests(unittest.TestCase):
    def test_new_account_dataset_config_is_separate_from_ftmo_data(self) -> None:
        config = json.loads(
            (WORKSPACE_ROOT / "configs/datasets/lpfs_new_mt5_account_forex_10y.example.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(config["symbol_universe"], "forex_major_cross_pairs")
        self.assertEqual(config["timeframes"], ["H4", "H8", "H12", "D1", "W1"])
        self.assertEqual(config["history_years"], 10)
        self.assertEqual(config["data_root"], "data/raw/lpfs_new_mt5_account/forex")
        self.assertNotIn("ftmo", config["data_root"].lower())

    def test_new_account_strategy_config_preserves_v22_baseline_and_separate_outputs(self) -> None:
        config = json.loads(
            (
                WORKSPACE_ROOT
                / "configs/strategies/lp_force_strike_experiment_v22_new_mt5_account.example.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(config["dataset_config"], "configs/datasets/lpfs_new_mt5_account_forex_10y.example.json")
        self.assertEqual(config["report_root"], "reports/strategies/lp_force_strike_experiment_v22_new_mt5_account")
        self.assertIsNone(config["docs_output_path"])
        self.assertEqual(config["pivot_strength"], 3)
        self.assertEqual(config["max_bars_from_lp_break"], 6)
        self.assertEqual(config["entry_zone"], 0.5)
        self.assertEqual(config["target_r"], 1.0)
        variants = {row["variant_id"]: row for row in config["variants"]}
        self.assertFalse(variants["control_current"]["require_lp_pivot_before_fs_mother"])
        self.assertTrue(variants["exclude_lp_pivot_inside_fs"]["require_lp_pivot_before_fs_mother"])

    def test_new_account_local_config_example_is_fail_closed_and_separate(self) -> None:
        config = json.loads((WORKSPACE_ROOT / "config.lpfs_new_mt5_account.example.json").read_text(encoding="utf-8"))

        self.assertTrue(config["mt5"]["use_existing_terminal_session"])
        self.assertEqual(config["mt5"]["expected_login"], "NEW_ACCOUNT_MT5_LOGIN")
        self.assertFalse(config["telegram"]["enabled"])
        self.assertEqual(config["live_send"]["execution_mode"], "DRY_RUN")
        self.assertFalse(config["live_send"]["live_send_enabled"])
        self.assertEqual(config["live_send"]["real_money_ack"], "")
        self.assertEqual(config["dry_run"]["timeframes"], ["H4", "H8", "H12", "D1", "W1"])
        self.assertTrue(config["dry_run"]["require_lp_pivot_before_fs_mother"])
        self.assertIn("lpfs_new_mt5_account", config["dry_run"]["journal_path"])
        self.assertIn("lpfs_new_mt5_account", config["live_send"]["state_path"])

    def test_audit_script_does_not_send_or_check_orders(self) -> None:
        source = (SCRIPTS_ROOT / "audit_lpfs_new_mt5_account.py").read_text(encoding="utf-8")

        self.assertIn("account_info", source)
        self.assertIn("symbol_info", source)
        self.assertIn("copy_rates_from_pos", source)
        self.assertNotIn(".order_send", source)
        self.assertNotIn(".order_check", source)

    def test_compare_script_writes_metric_and_symbol_timeframe_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            new = root / "new"
            for path in (baseline, new):
                path.mkdir(parents=True)

            header = [
                "separation_variant_id",
                "trades",
                "win_rate",
                "total_net_r",
                "avg_net_r",
                "profit_factor",
                "max_drawdown_r",
                "return_to_drawdown_r",
                "bucket_efficient_total_return_pct",
                "bucket_efficient_reserved_max_drawdown_pct",
                "bucket_efficient_return_to_reserved_drawdown",
            ]
            with (baseline / "summary_by_variant.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=header)
                writer.writeheader()
                writer.writerow(
                    {
                        "separation_variant_id": "exclude_lp_pivot_inside_fs",
                        "trades": "100",
                        "win_rate": "0.55",
                        "total_net_r": "20",
                        "avg_net_r": "0.2",
                        "profit_factor": "1.2",
                        "max_drawdown_r": "5",
                        "return_to_drawdown_r": "4",
                        "bucket_efficient_total_return_pct": "10",
                        "bucket_efficient_reserved_max_drawdown_pct": "2",
                        "bucket_efficient_return_to_reserved_drawdown": "5",
                    }
                )
            with (new / "summary_by_variant.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=header)
                writer.writeheader()
                writer.writerow(
                    {
                        "separation_variant_id": "exclude_lp_pivot_inside_fs",
                        "trades": "110",
                        "win_rate": "0.56",
                        "total_net_r": "23",
                        "avg_net_r": "0.21",
                        "profit_factor": "1.25",
                        "max_drawdown_r": "5.5",
                        "return_to_drawdown_r": "4.18",
                        "bucket_efficient_total_return_pct": "11",
                        "bucket_efficient_reserved_max_drawdown_pct": "2.2",
                        "bucket_efficient_return_to_reserved_drawdown": "5",
                    }
                )

            st_header = ["separation_variant_id", "symbol", "timeframe", "trades", "win_rate", "total_net_r", "avg_net_r", "profit_factor"]
            for path, trades, total_r in ((baseline, "10", "2"), (new, "11", "2.5")):
                with (path / "summary_by_symbol_timeframe.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=st_header)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "separation_variant_id": "exclude_lp_pivot_inside_fs",
                            "symbol": "EURUSD",
                            "timeframe": "H4",
                            "trades": trades,
                            "win_rate": "0.5",
                            "total_net_r": total_r,
                            "avg_net_r": "0.2",
                            "profit_factor": "1.2",
                        }
                    )

            output = root / "comparison"
            with contextlib.redirect_stdout(io.StringIO()):
                result = compare_runs(
                    baseline_run_dir=baseline,
                    new_run_dir=new,
                    output_dir=output,
                    variant="exclude_lp_pivot_inside_fs",
                )
            self.assertEqual(result, 0)
            summary = json.loads((output / "comparison_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["variant"], "exclude_lp_pivot_inside_fs")
            self.assertTrue((output / "symbol_timeframe_delta.csv").exists())


if __name__ == "__main__":
    unittest.main()
