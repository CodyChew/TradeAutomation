from __future__ import annotations

import importlib.util
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
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

from backtest_engine_lab import TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    LiveSendExecutorConfig,
    build_setup_diagnostics,
    closed_trade_diagnostic_rows,
    enrich_diagnostics,
    fields_with_diagnostics,
    flatten_diagnostics,
)
import lp_force_strike_strategy_lab.diagnostic_logging as diagnostic_module  # noqa: E402
from lp_force_strike_strategy_lab.execution_contract import MT5MarketSnapshot  # noqa: E402
import lp_force_strike_strategy_lab.live_executor as live_module  # noqa: E402
from lp_force_strike_strategy_lab.notifications import NotificationEvent  # noqa: E402


class DiagnosticLoggingTests(unittest.TestCase):
    def test_setup_diagnostics_are_compact_versioned_and_backtest_joinable(self) -> None:
        diagnostics = build_setup_diagnostics(
            _setup(),
            config=LiveSendExecutorConfig(symbols=("EURUSD",), timeframes=("H4",)),
            signal_key="lpfs:EURUSD:H4:10:long:signal_zone_0p5_pullback__fs_structure__1r:2026-01-01T00:00:00Z",
        )

        self.assertEqual(diagnostics["schema_version"], 2)
        self.assertEqual(diagnostics["setup"]["setup_id"], "EURUSD_H4_long")
        self.assertEqual(diagnostics["setup"]["entry_zone"], 0.5)
        self.assertAlmostEqual(diagnostics["setup"]["risk_atr"], 0.5)
        self.assertEqual(diagnostics["strategy"]["pivot_strength"], 3)
        self.assertEqual(diagnostics["backtest_join"]["symbol"], "EURUSD")
        self.assertIn("signal_zone_0p5", diagnostics["backtest_join"]["trade_key"])

        enriched = enrich_diagnostics(
            diagnostics,
            market=MT5MarketSnapshot(bid=1.0999, ask=1.1001, spread_points=2, time_utc="2026-01-01T04:00:00Z"),
            execution={"execution_path": "pending_limit", "stage": "order_sent"},
        )
        fields = fields_with_diagnostics({"order_ticket": 9001}, enriched)
        self.assertEqual(fields["diagnostic_schema_version"], 2)
        self.assertEqual(fields["diagnostics"]["market"]["spread_points"], 2.0)
        flat = flatten_diagnostics(fields["diagnostics"])
        self.assertEqual(flat["diagnostic_execution_execution_path"], "pending_limit")

    def test_diagnostic_helpers_cover_old_rows_and_malformed_values(self) -> None:
        bare = build_setup_diagnostics(
            TradeSetup(
                setup_id="bad",
                side="long",
                entry_index=1,
                entry_price=None,  # type: ignore[arg-type]
                stop_price="bad",  # type: ignore[arg-type]
                target_price=None,  # type: ignore[arg-type]
                symbol="eurusd",
                timeframe="h4",
                signal_index=None,
                metadata={"entry_zone": "bad", "lp_break_index": "bad"},
            )
        )
        self.assertEqual(bare["schema_version"], 2)
        self.assertNotIn("strategy", bare)
        self.assertNotIn("risk_distance", bare["setup"])
        self.assertEqual(diagnostic_module.diagnostics_from_fields(None), {})
        self.assertEqual(diagnostic_module.diagnostics_from_fields({"diagnostics": "bad"}), {})
        self.assertEqual(diagnostic_module.enrich_diagnostics({}, market=None, spread_gate=None)["schema_version"], 2)

        @dataclass(frozen=True)
        class Nested:
            value: int

        flattened = flatten_diagnostics(
            {
                "schema_version": 1,
                "items": [Nested(1), ("x", {"empty": ""})],
                "nested": {"empty": {}, "value": "kept"},
            }
        )
        self.assertEqual(flattened["diagnostic_items"], [{"value": 1}, ["x", {"empty": ""}]])
        self.assertEqual(flattened["diagnostic_nested_value"], "kept")

    def test_live_diagnostic_timing_helpers_handle_empty_and_bad_inputs(self) -> None:
        event = NotificationEvent(kind="setup_rejected", mode="LIVE", title="Rejected")
        self.assertIs(live_module._with_event_diagnostics(event, None), event)
        self.assertIsNone(live_module._signal_to_event_seconds("bad", "H4", "2026-01-01T00:00:00Z"))
        self.assertIsNone(
            live_module._signal_to_event_seconds(
                "lpfs:EURUSD:H4:10:long:c:2026-01-01T00:00:00Z",
                "H4",
                "bad",
            )
        )
        self.assertIsNone(live_module._seconds_between("bad", "2026-01-01T00:00:00Z"))

    def test_closed_trade_diagnostic_rows_tolerate_old_and_new_journals(self) -> None:
        diagnostics = build_setup_diagnostics(_setup(), config=LiveSendExecutorConfig(), signal_key="sig")
        new_rows = closed_trade_diagnostic_rows(
            [
                _row("position_opened", {"position_id": 1, "opened_utc": "2026-01-01T00:00:00Z"}),
                _row(
                    "take_profit_hit",
                    fields_with_diagnostics(
                        {
                            "position_id": 1,
                            "entry": 1.1,
                            "close_price": 1.105,
                            "initial_volume": 0.02,
                            "closed_volume": 0.02,
                            "remaining_volume": 0.0,
                            "close_deal_tickets": [1001, 1002],
                            "close_deal_count": 2,
                            "aggregate_close_profit": 12.0,
                            "aggregate_r_result": 1.0,
                            "close_reason_detail": "all_close_deals_tp",
                            "r_result": 1.0,
                            "closed_utc": "2026-01-01T04:00:00Z",
                        },
                        diagnostics,
                    ),
                ),
            ],
            lane="FTMO",
        )
        self.assertEqual(new_rows[0]["lane"], "FTMO")
        self.assertEqual(new_rows[0]["diagnostic_setup_setup_id"], "EURUSD_H4_long")
        self.assertEqual(new_rows[0]["close_deal_tickets"], "1001,1002")
        self.assertEqual(new_rows[0]["close_deal_count"], 2)
        self.assertEqual(new_rows[0]["aggregate_close_profit"], 12.0)
        self.assertEqual(new_rows[0]["aggregate_r_result"], 1.0)
        self.assertEqual(new_rows[0]["close_reason_detail"], "all_close_deals_tp")

        old_rows = closed_trade_diagnostic_rows(
            [
                _row("position_opened", {"position_id": 2, "opened_utc": "2026-01-01T00:00:00Z"}),
                _row(
                    "stop_loss_hit",
                    {
                        "position_id": 2,
                        "entry": 1.1,
                        "close_price": 1.095,
                        "r_result": -1.0,
                        "closed_utc": "2026-01-01T04:00:00Z",
                    },
                ),
            ],
            lane="IC",
        )
        self.assertEqual(old_rows[0]["lane"], "IC")
        self.assertNotIn("diagnostic_setup_setup_id", old_rows[0])

    def test_trade_diagnostics_script_writes_additive_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            journal = tmp / "journal.jsonl"
            benchmark = tmp / "backtest.csv"
            candle_root = tmp / "candles"
            diagnostics = build_setup_diagnostics(_setup(), config=LiveSendExecutorConfig(), signal_key="sig")
            rows = [
                _row("position_opened", {"position_id": 1, "opened_utc": "2026-01-01T00:00:00Z"}),
                _row(
                    "take_profit_hit",
                    fields_with_diagnostics(
                        {"position_id": 1, "entry": 1.1, "close_price": 1.105, "r_result": 1.0, "closed_utc": "2026-01-01T04:00:00Z"},
                        diagnostics,
                    ),
                ),
            ]
            journal.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            benchmark.write_text(
                (
                    "symbol,timeframe,side,signal_index,entry_index,entry_time_utc,exit_time_utc,"
                    "net_r,meta_risk_atr,meta_bars_from_lp_break,meta_fs_signal_time_utc\n"
                    "EURUSD,H4,long,10,11,2026-01-01T00:00:00Z,2026-01-01T04:00:00Z,0.25,0.5,2,2026-01-01T00:00:00Z\n"
                ),
                encoding="utf-8",
            )
            candle_dir = candle_root / "EURUSD" / "H4"
            candle_dir.mkdir(parents=True)
            candle_lines = ["time_utc,symbol,timeframe,open,high,low,close,tick_volume,spread_points,real_volume"]
            start = "2025-12-28T00:00:00Z"
            base = pd.Timestamp(start)
            for index in range(30):
                timestamp = base + pd.Timedelta(hours=4 * index)
                open_price = 1.0900 + index * 0.0001
                close_price = open_price + (0.0002 if index % 2 == 0 else -0.0001)
                high_price = max(open_price, close_price) + 0.0003
                low_price = min(open_price, close_price) - 0.0003
                candle_lines.append(
                    f"{timestamp.isoformat()},EURUSD,H4,{open_price:.5f},{high_price:.5f},{low_price:.5f},{close_price:.5f},"
                    f"{100 + index},{index % 5},0"
                )
            (candle_dir / "EURUSD_H4.csv").write_text("\n".join(candle_lines), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "build_lpfs_trade_diagnostics.py"),
                    "--journal",
                    f"FTMO={journal}",
                    "--benchmark-trades",
                    f"FTMO={benchmark}",
                    "--candle-root",
                    f"FTMO={candle_root}",
                    "--output-root",
                    str(tmp / "reports"),
                    "--as-of-utc",
                    "2026-05-23T00:00:00Z",
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output_dir = tmp / "reports" / "20260523_000000"
            self.assertTrue((output_dir / "closed_trade_diagnostics.csv").exists())
            self.assertTrue((output_dir / "backtest_diagnostics.csv").exists())
            self.assertTrue((output_dir / "backtest_comparison.csv").exists())
            self.assertTrue((output_dir / "timeframe_confluence.csv").exists())
            self.assertTrue((output_dir / "research_candidates.csv").exists())
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertIn("LPFS Trade Diagnostics", (output_dir / "summary.md").read_text(encoding="utf-8"))
            with (output_dir / "closed_trade_diagnostics.csv").open("r", encoding="utf-8", newline="") as handle:
                closed_rows = list(csv.DictReader(handle))
            self.assertEqual(closed_rows[0]["analysis_session_utc"], "asia_utc")
            self.assertEqual(closed_rows[0]["timeframe_frequency_class"], "higher_frequency")
            self.assertTrue(closed_rows[0]["candle_time_utc"].startswith("2026-01-01T00:00:00"))
            self.assertIn(closed_rows[0]["candle_rsi_regime"], {"neutral", "oversold", "overbought"})
            self.assertIn(closed_rows[0]["candle_close_vs_ema_20"], {"above", "below", "near"})
            self.assertIn(closed_rows[0]["candle_macd_histogram_regime"], {"positive", "negative", "zero"})
            with (output_dir / "backtest_comparison.csv").open("r", encoding="utf-8", newline="") as handle:
                comparison_rows = list(csv.DictReader(handle))
            self.assertTrue(
                any(row["group_by"] == "lane|timeframe|candle_rsi_regime" for row in comparison_rows)
            )
            self.assertTrue(
                any(row["group_by"] == "lane|timeframe|candle_macd_histogram_regime" for row in comparison_rows)
            )
            with (output_dir / "timeframe_confluence.csv").open("r", encoding="utf-8", newline="") as handle:
                confluence_rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["timeframe"] == "H4" for row in confluence_rows))
            with (output_dir / "research_candidates.csv").open("r", encoding="utf-8", newline="") as handle:
                candidate_rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["group_by"] == "timeframe" and row["timeframe"] == "H4" for row in candidate_rows))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["scope"], "offline_read_only_strategy_attribution")
            self.assertEqual(manifest["row_counts"]["closed_trade_diagnostics"], 1)
            self.assertTrue(any(output["path"].endswith("research_candidates.csv") for output in manifest["outputs"]))

            excluded = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "build_lpfs_trade_diagnostics.py"),
                    "--journal",
                    f"FTMO={journal}",
                    "--benchmark-trades",
                    f"FTMO={benchmark}",
                    "--candle-root",
                    f"FTMO={candle_root}",
                    "--output-root",
                    str(tmp / "excluded_reports"),
                    "--as-of-utc",
                    "2026-05-23T00:00:00Z",
                    "--exclude-window",
                    "downtime=2026-01-01T00:00:00Z,2026-01-02T00:00:00Z",
                ],
                cwd=WORKSPACE_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(excluded.returncode, 0, excluded.stderr)
            excluded_dir = tmp / "excluded_reports" / "20260523_000000"
            with (excluded_dir / "closed_trade_diagnostics.csv").open("r", encoding="utf-8", newline="") as handle:
                excluded_rows = list(csv.DictReader(handle))
            self.assertEqual(excluded_rows[0]["excluded_from_strategy_analysis"], "True")
            self.assertEqual(excluded_rows[0]["strategy_analysis_exclusion_reason"], "downtime")
            with (excluded_dir / "research_candidates.csv").open("r", encoding="utf-8", newline="") as handle:
                excluded_candidates = list(csv.DictReader(handle))
            self.assertEqual(excluded_candidates, [])
            excluded_manifest = json.loads((excluded_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                excluded_manifest["row_counts"]["closed_trade_diagnostics_excluded_from_strategy_analysis"],
                1,
            )

    def test_gate_attribution_remote_script_uses_shared_bounded_reader(self) -> None:
        module_path = WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_gate_attribution.py"
        spec = importlib.util.spec_from_file_location("gate_script", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        script = module._remote_shared_jsonl_reader_script(
            r"C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl",
            tail_lines=500,
            max_source_bytes=4096,
            include_market_snapshots=False,
        )
        self.assertIn("[System.IO.FileShare]::ReadWrite", script)
        self.assertIn("$TailLines = 500", script)
        self.assertIn("$MaxSourceBytes = 4096", script)
        self.assertIn("Seek(-1 * $MaxSourceBytes", script)
        self.assertIn("$stream.ReadByte()", script)
        self.assertNotIn("$discard.ReadLine()", script)
        self.assertNotIn("Get-Content", script)

    def test_gate_attribution_local_reader_bounds_source_bytes_before_tail(self) -> None:
        module_path = WORKSPACE_ROOT / "scripts" / "summarize_lpfs_live_gate_attribution.py"
        spec = importlib.util.spec_from_file_location("gate_script", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            journal.write_text(
                "\n".join(json.dumps({"event": "setup_rejected", "seq": seq}) for seq in range(20)) + "\n",
                encoding="utf-8",
            )

            rows = module._load_local_jsonl(str(journal), tail_lines=10, max_source_bytes=90)

        seqs = [row["seq"] for row in rows]
        self.assertGreater(len(seqs), 0)
        self.assertLessEqual(len(seqs), 10)
        self.assertEqual(seqs[-1], 19)
        self.assertNotIn(0, seqs)


def _setup() -> TradeSetup:
    return TradeSetup(
        setup_id="EURUSD_H4_long",
        side="long",
        entry_index=11,
        entry_price=1.1,
        stop_price=1.095,
        target_price=1.105,
        symbol="EURUSD",
        timeframe="H4",
        signal_index=10,
        metadata={
            "candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
            "entry_model": "signal_zone_pullback",
            "entry_wait_mode": "fixed_bars",
            "entry_zone": 0.5,
            "stop_model": "fs_structure",
            "target_r": 1.0,
            "lp_price": 1.11,
            "lp_break_index": 6,
            "lp_break_time_utc": "2026-01-01T00:00:00Z",
            "fs_mother_index": 8,
            "fs_signal_index": 10,
            "fs_signal_time_utc": "2026-01-01T00:00:00Z",
            "fs_total_bars": 3,
            "bars_from_lp_break": 4,
            "structure_low": 1.095,
            "structure_high": 1.105,
            "atr": 0.01,
            "risk_atr": 0.5,
        },
    )


def _row(kind: str, fields: dict) -> dict:
    return {
        "event": kind,
        "notification_event": {
            "kind": kind,
            "mode": "LIVE",
            "title": kind,
            "symbol": "EURUSD",
            "timeframe": "H4",
            "side": "long",
            "signal_key": "lpfs:EURUSD:H4:10:long:candidate:2026-01-01T00:00:00Z",
            "fields": fields,
        },
    }


if __name__ == "__main__":
    unittest.main()
