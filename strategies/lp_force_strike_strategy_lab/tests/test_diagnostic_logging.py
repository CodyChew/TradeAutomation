from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


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

        self.assertEqual(diagnostics["schema_version"], 1)
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
        self.assertEqual(fields["diagnostic_schema_version"], 1)
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
        self.assertEqual(bare["schema_version"], 1)
        self.assertNotIn("strategy", bare)
        self.assertNotIn("risk_distance", bare["setup"])
        self.assertEqual(diagnostic_module.diagnostics_from_fields(None), {})
        self.assertEqual(diagnostic_module.diagnostics_from_fields({"diagnostics": "bad"}), {})
        self.assertEqual(diagnostic_module.enrich_diagnostics({}, market=None, spread_gate=None)["schema_version"], 1)

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
                "symbol,timeframe,side,net_r,meta_risk_atr,meta_bars_from_lp_break\nEURUSD,H4,long,0.25,0.5,2\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(WORKSPACE_ROOT / "scripts" / "build_lpfs_trade_diagnostics.py"),
                    "--journal",
                    f"FTMO={journal}",
                    "--benchmark-trades",
                    f"FTMO={benchmark}",
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
            self.assertTrue((output_dir / "backtest_comparison.csv").exists())
            self.assertIn("LPFS Trade Diagnostics", (output_dir / "summary.md").read_text(encoding="utf-8"))

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
            include_market_snapshots=False,
        )
        self.assertIn("[System.IO.FileShare]::ReadWrite", script)
        self.assertIn("$TailLines = 500", script)
        self.assertNotIn("Get-Content", script)


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
