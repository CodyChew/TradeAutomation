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

v21 = importlib.import_module("run_lp_force_strike_v21_crypto_btc_eth")


class V21CryptoReportTests(unittest.TestCase):
    def test_crypto_dataset_config_loads_without_changing_fx_universe(self) -> None:
        crypto = load_dataset_config(WORKSPACE_ROOT / "configs" / "datasets" / "crypto_btc_eth_sol_broker_history.json")
        fx = load_dataset_config(WORKSPACE_ROOT / "configs" / "datasets" / "forex_major_crosses_10y.json")

        self.assertEqual(crypto.symbols, ("BTCUSD", "ETHUSD", "SOLUSD"))
        self.assertEqual(crypto.timeframes, ("M30", "H4", "H8", "H12", "D1", "W1"))
        self.assertEqual(len(fx.symbols), 28)
        self.assertIn("EURUSD", fx.symbols)
        self.assertNotIn("BTCUSD", fx.symbols)

    def test_v21_strategy_config_marks_btc_eth_decision_and_sol_exploratory(self) -> None:
        config = json.loads(
            (WORKSPACE_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v21_crypto_btc_eth.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(config["decision_symbols"], ["BTCUSD", "ETHUSD"])
        self.assertEqual(config["exploratory_symbols"], ["SOLUSD"])
        self.assertEqual(config["risk_bucket_scale"], 0.05)
        self.assertEqual(config["target_r"], 1.0)

    def test_min_lot_overrisk_is_classified_not_sizeable(self) -> None:
        specs = pd.DataFrame(
            [
                {
                    "symbol": "BTCUSD",
                    "trade_tick_value": 1.0,
                    "trade_tick_size": 1.0,
                    "volume_min": 0.01,
                    "volume_step": 0.01,
                    "volume_max": 100.0,
                }
            ]
        )
        trade = {
            "symbol": "BTCUSD",
            "timeframe": "H4",
            "asset_role": "decision",
            "side": "long",
            "signal_index": 10,
            "risk_distance": 100.0,
            "meta_signal_spread_to_risk": 0.01,
        }

        row = v21._feasibility_row(
            trade,
            specs,
            account_equity=1000.0,
            risk_bucket_scale=0.05,
            max_spread_risk_fraction=0.1,
        )

        self.assertEqual(row["feasibility_status"], "not_sizeable")
        self.assertFalse(row["live_feasible"])
        self.assertAlmostEqual(row["min_lot_risk_pct"], 0.1)

    def test_volume_rounding_never_rounds_above_allowed_risk(self) -> None:
        specs = pd.DataFrame(
            [
                {
                    "symbol": "ETHUSD",
                    "trade_tick_value": 1.0,
                    "trade_tick_size": 1.0,
                    "volume_min": 0.01,
                    "volume_step": 0.01,
                    "volume_max": 100.0,
                }
            ]
        )
        trade = {
            "symbol": "ETHUSD",
            "timeframe": "H4",
            "asset_role": "decision",
            "side": "short",
            "signal_index": 20,
            "risk_distance": 30.0,
            "meta_signal_spread_to_risk": 0.02,
        }

        row = v21._feasibility_row(
            trade,
            specs,
            account_equity=10000.0,
            risk_bucket_scale=0.05,
            max_spread_risk_fraction=0.1,
        )

        self.assertEqual(row["feasibility_status"], "live_feasible")
        self.assertEqual(row["rounded_volume"], 0.03)
        self.assertLessEqual(row["actual_risk_pct"], row["target_risk_pct"])

    def test_html_report_contains_required_sections(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "asset_role": "decision",
                    "trades": 40,
                    "wins": 24,
                    "losses": 16,
                    "win_rate": 0.6,
                    "total_net_r": 30.0,
                    "profit_factor": 1.5,
                    "max_drawdown_r": 5.0,
                    "return_to_drawdown": 6.0,
                    "worst_month_r": -2.0,
                }
            ]
        )
        symbol_summary = pd.DataFrame(
            [
                {"asset_role": "decision", "symbol": "BTCUSD", "trades": 20, "win_rate": 0.6, "total_net_r": 20.0, "profit_factor": 1.4, "max_drawdown_r": 4.0, "return_to_drawdown": 5.0},
                {"asset_role": "exploratory", "symbol": "SOLUSD", "trades": 3, "win_rate": 0.33, "total_net_r": -1.0, "profit_factor": 0.5, "max_drawdown_r": 2.0, "return_to_drawdown": -0.5},
            ]
        )
        baseline_comparison = pd.DataFrame(
            [
                {
                    "comparison_row": "V15 canonical FX baseline",
                    "scope": "28 FX pairs",
                    "trades": 13012,
                    "total_net_r": 1512.3,
                    "avg_net_r": 0.116,
                    "profit_factor": 1.265,
                    "max_drawdown_r": 33.4,
                    "return_to_drawdown": 45.3,
                    "worst_month_r": None,
                    "note": "Current strategy baseline.",
                },
                {
                    "comparison_row": "V21 BTC/ETH crypto transfer",
                    "scope": "BTCUSD + ETHUSD",
                    "trades": 40,
                    "total_net_r": 30.0,
                    "avg_net_r": 0.75,
                    "profit_factor": 1.5,
                    "max_drawdown_r": 5.0,
                    "return_to_drawdown": 6.0,
                    "worst_month_r": -2.0,
                    "note": "Crypto transfer test.",
                },
            ]
        )
        timeframe_summary = pd.DataFrame(
            [{"asset_role": "decision", "timeframe": "H4", "trades": 10, "win_rate": 0.6, "total_net_r": 8.0, "profit_factor": 1.3, "max_drawdown_r": 2.0, "return_to_drawdown": 4.0}]
        )
        symbol_timeframe = pd.DataFrame(
            [{"asset_role": "decision", "symbol": "BTCUSD", "timeframe": "H4", "trades": 10, "total_net_r": 8.0, "profit_factor": 1.3, "max_drawdown_r": 2.0, "return_to_drawdown": 4.0}]
        )
        feasibility = pd.DataFrame(
            [{"asset_role": "decision", "symbol": "BTCUSD", "timeframe": "H4", "live_feasible": True, "spread_ok": True}]
        )
        sizeability = pd.DataFrame(
            [{"asset_role": "decision", "symbol": "BTCUSD", "timeframe": "H4", "trades": 10, "live_feasible": 9, "live_feasible_rate": 0.9, "not_sizeable": 1, "spread_too_wide": 0, "median_min_lot_risk_pct": 0.01, "median_required_equity": 1000.0}]
        )
        spread = pd.DataFrame(
            [{"asset_role": "decision", "symbol": "BTCUSD", "timeframe": "H4", "trades": 10, "avg_spread_to_risk_pct": 2.0, "max_spread_to_risk_pct": 5.0, "spread_failures": 0, "spread_failure_rate": 0.0}]
        )
        symbol_specs = pd.DataFrame(
            [{"symbol": "BTCUSD", "digits": 2, "point": 0.01, "spread_points": 100, "trade_tick_value": 1.0, "trade_tick_size": 0.01, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0, "trade_contract_size": 1.0, "trade_stops_level": 0, "trade_freeze_level": 0}]
        )
        quality = pd.DataFrame(
            [{"symbol": "BTCUSD", "timeframe": "H4", "status": "ok", "rows": 100, "coverage_start_utc": "2020-01-01", "coverage_end_utc": "2026-01-01", "large_gap_count": 0, "suspicious_bar_count": 0}]
        )
        decision = {"status": "research_only", "headline": "Crypto is research-only.", "detail": "Positive but not live.", "follow_up": "Inspect BTC."}

        html = v21._html_report(
            Path("reports/test"),
            decision=decision,
            btc_eth_summary=summary,
            baseline_comparison=baseline_comparison,
            symbol_summary=symbol_summary,
            timeframe_summary=timeframe_summary,
            symbol_timeframe_summary=symbol_timeframe,
            feasibility=feasibility,
            spread=spread,
            sizeability=sizeability,
            symbol_specs=symbol_specs,
            dataset_quality=quality,
            run_summary={"account_equity": 10000.0},
        )

        for text in [
            "LP + Force Strike V21 Crypto Research",
            "Decision Card",
            "BTC/ETH Result Summary",
            "Baseline Comparison",
            "V15 canonical FX baseline",
            "V21 BTC/ETH crypto transfer",
            "Symbol Verdicts",
            "Timeframe Breakdown",
            "Execution Feasibility",
            "Spread Risk",
            "SOL Appendix",
            "Follow-Up Section",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, html)

    def test_runner_source_writes_required_artifacts_and_has_no_live_hooks(self) -> None:
        source = (WORKSPACE_ROOT / "scripts" / "run_lp_force_strike_v21_crypto_btc_eth.py").read_text(encoding="utf-8")
        expected_artifacts = [
            "pull_results.json",
            "coverage_report.csv",
            "data_quality_report.csv",
            "symbol_specs.csv",
            "trades.csv",
            "skipped_trades.csv",
            "summary_by_symbol.csv",
            "summary_by_timeframe.csv",
            "summary_by_symbol_timeframe.csv",
            "baseline_comparison.csv",
            "execution_feasibility.csv",
            "spread_to_risk_breakdown.csv",
            "sizeability_breakdown.csv",
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
