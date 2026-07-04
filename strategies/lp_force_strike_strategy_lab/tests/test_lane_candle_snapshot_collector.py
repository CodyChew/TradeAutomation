from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = WORKSPACE_ROOT / "scripts" / "collect_lpfs_lane_candle_snapshots.py"


def _load_collector():
    spec = importlib.util.spec_from_file_location("collect_lpfs_lane_candle_snapshots", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LaneCandleSnapshotCollectorTests(unittest.TestCase):
    def test_dry_run_writes_reviewable_packet_without_ssh(self) -> None:
        module = _load_collector()

        with tempfile.TemporaryDirectory() as temp_dir:
            packet = module.collect_lane_candle_snapshots(
                lanes=("FTMO",),
                symbols=("EURUSD",),
                timeframes=("H4",),
                history_years=1,
                date_start_utc=None,
                date_end_utc=None,
                output_root=Path(temp_dir),
                dry_run=True,
                now=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            )

            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result"], "DRY_RUN")
            self.assertTrue(manifest["dry_run"])
            self.assertTrue(manifest["collector_repo_head"])
            self.assertTrue(str(manifest["collector_script_path"]).endswith("collect_lpfs_lane_candle_snapshots.py"))
            self.assertRegex(manifest["collector_script_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("no_broker_order_or_position_mutation", manifest["non_actions"])
            self.assertTrue((packet / "ftmo" / "request.json").is_file())
            self.assertTrue((packet / "ftmo" / "remote_collect.ps1").is_file())
            self.assertTrue((packet / "manifest.sha256.txt").is_file())

    def test_remote_script_uses_hash_bound_strict_collector_and_no_task_or_broker_actions(self) -> None:
        module = _load_collector()
        request = module.LaneRequest(
            profile=module.LANE_PROFILES["FTMO"],
            symbols=("EURUSD",),
            timeframes=("H4",),
            history_years=1,
            date_start_utc=None,
            date_end_utc=None,
            collection_id="20260704_120000",
        )

        script = module.build_remote_lane_script(request, remote_root=r"C:\Windows\Temp\lpfs_test")
        helper = module._remote_collect_python_source()

        self.assertIn("collect_lane_candles.py", script)
        self.assertIn("collect script hash mismatch", script)
        self.assertIn("CollectScriptHash", script)
        self.assertIn("collect_script_sha256", script)
        self.assertIn("StrictMT5Proxy", helper)
        self.assertIn("symbol_select is disabled", helper)
        self.assertIn(module.REMOTE_MARKER, script)
        self.assertIn("Compress-Archive", script)
        forbidden = (
            "order_send",
            "orders_send",
            "New-ScheduledTask",
            "Register-ScheduledTask",
            "Start-ScheduledTask",
            "Stop-ScheduledTask",
            "Disable-ScheduledTask",
            "Enable-ScheduledTask",
            "kill_switch",
        )
        for token in forbidden:
            self.assertNotIn(token, script)

    def test_validate_lane_candle_root_accepts_current_ic_server_metadata(self) -> None:
        module = _load_collector()

        with tempfile.TemporaryDirectory() as temp_dir:
            candle_root = Path(temp_dir) / "candles"
            _write_manifest(
                candle_root,
                symbol="EURUSD",
                timeframe="H4",
                server="ICMarketsSC-MT5-2",
                company="Raw Trading Ltd",
            )
            request = module.LaneRequest(
                profile=module.LANE_PROFILES["IC"],
                symbols=("EURUSD",),
                timeframes=("H4",),
                history_years=1,
                date_start_utc=None,
                date_end_utc=None,
                collection_id="20260704_120000",
            )

            validation = module.validate_lane_candle_root(candle_root, request=request)

            self.assertEqual(validation["result"], "PASS", validation["failures"])
            self.assertTrue(validation["safe_for_strategy_analysis"])
            self.assertEqual(validation["expected_server"], "ICMarketsSC-MT5-2")

    def test_validate_lane_candle_root_rejects_cross_lane_metadata(self) -> None:
        module = _load_collector()

        with tempfile.TemporaryDirectory() as temp_dir:
            candle_root = Path(temp_dir) / "candles"
            _write_manifest(
                candle_root,
                symbol="EURUSD",
                timeframe="H4",
                server="ICMarketsSC-MT5-2",
                company="Raw Trading Ltd",
            )
            request = module.LaneRequest(
                profile=module.LANE_PROFILES["FTMO"],
                symbols=("EURUSD",),
                timeframes=("H4",),
                history_years=1,
                date_start_utc=None,
                date_end_utc=None,
                collection_id="20260704_120000",
            )

            validation = module.validate_lane_candle_root(candle_root, request=request)

            self.assertEqual(validation["result"], "STOPPED")
            self.assertFalse(validation["safe_for_strategy_analysis"])
            self.assertTrue(any("FTMO-Server" in failure for failure in validation["failures"]))

    def test_validate_lane_candle_root_rejects_missing_requested_frame(self) -> None:
        module = _load_collector()

        with tempfile.TemporaryDirectory() as temp_dir:
            candle_root = Path(temp_dir) / "candles"
            _write_manifest(
                candle_root,
                symbol="EURUSD",
                timeframe="H4",
                server="FTMO-Server",
                company="FTMO",
            )
            request = module.LaneRequest(
                profile=module.LANE_PROFILES["FTMO"],
                symbols=("EURUSD", "GBPUSD"),
                timeframes=("H4",),
                history_years=1,
                date_start_utc=None,
                date_end_utc=None,
                collection_id="20260704_120000",
            )

            validation = module.validate_lane_candle_root(candle_root, request=request)

            self.assertEqual(validation["result"], "STOPPED")
            self.assertTrue(any("GBPUSD:H4" in failure for failure in validation["failures"]))

    def test_parse_remote_summary_requires_exactly_one_marker(self) -> None:
        module = _load_collector()

        with self.assertRaises(module.CandleSnapshotError):
            module._parse_remote_summary("no marker\n")
        with self.assertRaises(module.CandleSnapshotError):
            module._parse_remote_summary(
                module.REMOTE_MARKER + '{"result":"PASS"}\n' + module.REMOTE_MARKER + '{"result":"PASS"}\n'
            )


def _write_manifest(candle_root: Path, *, symbol: str, timeframe: str, server: str, company: str) -> None:
    candle_dir = candle_root / symbol / timeframe
    candle_dir.mkdir(parents=True, exist_ok=True)
    (candle_dir / f"{symbol}_{timeframe}.parquet").write_bytes(b"PAR1")
    (candle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "mt5",
                "rows": 10,
                "path": str(candle_dir / f"{symbol}_{timeframe}.parquet"),
                "storage_format": "parquet",
                "coverage_start_utc": "2026-01-01T00:00:00+00:00",
                "coverage_end_utc": "2026-07-01T00:00:00+00:00",
                "account_metadata": {"server": server, "company": company},
                "terminal_metadata": {"company": company, "name": company},
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
