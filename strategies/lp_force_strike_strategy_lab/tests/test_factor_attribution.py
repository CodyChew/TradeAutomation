from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPT = WORKSPACE_ROOT / "scripts" / "build_lpfs_factor_attribution.py"


class FactorAttributionBuilderTests(unittest.TestCase):
    def test_cli_builds_lane_first_and_cross_lane_factor_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            output_root = tmp / "out"
            _write_diagnostics_packet(diagnostics)

            result = _run_builder(diagnostics, output_root)

            self.assertEqual(result.returncode, 0, result.stderr)
            output_dir = output_root / "20260704_000000"
            matrix = _read_csv(output_dir / "factor_attribution_matrix.csv")
            confluence = _read_csv(output_dir / "cross_lane_factor_confluence.csv")
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            summary = (output_dir / "summary.md").read_text(encoding="utf-8")

            risk_ftmo = _find(matrix, lane="FTMO", dimension="risk_atr_bucket", value="lt_0p5")
            self.assertEqual(risk_ftmo["live_trades"], "3")
            self.assertEqual(risk_ftmo["live_net_r"], "-3.0")
            self.assertEqual(risk_ftmo["lane_signal_status"], "lane_research_candidate")
            self.assertEqual(risk_ftmo["decision_boundary"], "research_only_not_live_approval")
            self.assertIn("not_live_approval", risk_ftmo["caveats"])

            risk_cross = _find(confluence, dimension="risk_atr_bucket", value="lt_0p5")
            self.assertEqual(risk_cross["confluence_status"], "both_lanes_negative")
            self.assertEqual(risk_cross["strategy_research_decision"], "research_triggered")

            symbol_divergence = _find(confluence, dimension="symbol", value="eurusd")
            self.assertEqual(symbol_divergence["confluence_status"], "one_lane_divergence_or_missing_lane")
            self.assertEqual(symbol_divergence["strategy_research_decision"], "watch_divergence")

            self.assertEqual(manifest["scope"], "offline_read_only_factor_attribution")
            self.assertEqual(manifest["row_counts"]["total"], 8)
            self.assertEqual(manifest["row_counts"]["excluded_from_strategy_analysis"], 1)
            self.assertEqual(manifest["row_counts"]["usable_for_strategy_attribution"], 7)
            self.assertIn("policy_id_unavailable", manifest["data_validity_flags"])
            self.assertIn("no_vps_access", manifest["non_actions"])
            self.assertTrue(any(output["path"].endswith("factor_attribution_matrix.csv") for output in manifest["outputs"]))
            self.assertIn("not live approval", summary.lower())
            self.assertIn("offline/read-only", summary)

    def test_manifest_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            _write_diagnostics_packet(diagnostics, tamper_manifest=True)

            result = _run_builder(diagnostics, tmp / "out")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source hash mismatch", result.stderr)

    def test_missing_required_core_column_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            _write_diagnostics_packet(diagnostics, omit_live_lane=True)

            result = _run_builder(diagnostics, tmp / "out")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required columns", result.stderr)

    def test_missing_optional_factor_columns_emit_caveats_not_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            _write_diagnostics_packet(diagnostics, omit_optional_factors=True)

            result = _run_builder(diagnostics, tmp / "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((tmp / "out" / "20260704_000000" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("live_missing_factor_columns", manifest["data_validity_flags"])
            self.assertIn("backtest_missing_factor_columns", manifest["data_validity_flags"])
            self.assertIn("risk_atr_bucket", manifest["missing_columns"]["live_missing_factor_columns"])
            matrix = _read_csv(tmp / "out" / "20260704_000000" / "factor_attribution_matrix.csv")
            self.assertTrue(any(row["dimension"] == "timeframe" for row in matrix))


def _run_builder(diagnostics: Path, output_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--diagnostics-dir",
            str(diagnostics),
            "--output-root",
            str(output_root),
            "--as-of-utc",
            "2026-07-04T00:00:00Z",
            "--min-live-trades",
            "2",
            "--investigate-live-trades",
            "1",
            "--candidate-net-r",
            "-2",
            "--candidate-gap-vs-all",
            "0",
        ],
        cwd=WORKSPACE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_diagnostics_packet(
    diagnostics: Path,
    *,
    tamper_manifest: bool = False,
    omit_live_lane: bool = False,
    omit_optional_factors: bool = False,
) -> None:
    diagnostics.mkdir(parents=True)
    live_fields = [
        "lane",
        "symbol",
        "timeframe",
        "side",
        "r_result",
        "aggregate_r_result",
        "excluded_from_strategy_analysis",
        "result_time_utc",
    ]
    backtest_fields = [
        "lane",
        "symbol",
        "timeframe",
        "side",
        "r_result",
        "exit_time_utc",
        "recent_last_3m",
        "recent_last_6m",
        "recent_last_12m",
    ]
    optional = [
        "risk_atr_bucket",
        "candle_macd_histogram_regime",
        "candle_tick_volume_regime_252",
        "analysis_session_utc",
        "analysis_weekday_utc",
    ]
    if not omit_optional_factors:
        live_fields.extend(optional)
        backtest_fields.extend(optional)
    if omit_live_lane:
        live_fields.remove("lane")

    live_rows = [
        _row("FTMO", "EURUSD", "H8", "LONG", -1.0, "2026-06-20T00:00:00Z"),
        _row("FTMO", "EURJPY", "H8", "LONG", -1.0, "2026-06-21T00:00:00Z"),
        _row("FTMO", "GBPUSD", "H8", "SHORT", -1.0, "2026-06-22T00:00:00Z"),
        _row("FTMO", "AUDUSD", "H8", "LONG", -10.0, "2026-06-23T00:00:00Z", excluded=True),
        _row("IC", "EURUSD", "H8", "LONG", 1.0, "2026-06-20T00:00:00Z"),
        _row("IC", "EURJPY", "H8", "LONG", -1.0, "2026-06-21T00:00:00Z"),
        _row("IC", "GBPUSD", "H8", "SHORT", -1.0, "2026-06-22T00:00:00Z"),
        _row("IC", "AUDUSD", "H4", "LONG", -1.0, "2026-06-23T00:00:00Z"),
    ]
    backtest_rows = [
        _backtest_row("FTMO", "EURUSD", "H8", "LONG", 0.5),
        _backtest_row("FTMO", "EURJPY", "H8", "LONG", 0.5),
        _backtest_row("FTMO", "GBPUSD", "H8", "SHORT", 0.5),
        _backtest_row("IC", "EURUSD", "H8", "LONG", 0.5),
        _backtest_row("IC", "EURJPY", "H8", "LONG", 0.5),
        _backtest_row("IC", "GBPUSD", "H8", "SHORT", 0.5),
        _backtest_row("IC", "AUDUSD", "H4", "LONG", 0.5),
    ]
    if omit_optional_factors:
        live_rows = [{key: value for key, value in row.items() if key in live_fields} for row in live_rows]
        backtest_rows = [{key: value for key, value in row.items() if key in backtest_fields} for row in backtest_rows]
    if omit_live_lane:
        live_rows = [{key: value for key, value in row.items() if key != "lane"} for row in live_rows]

    _write_csv(diagnostics / "closed_trade_diagnostics.csv", live_fields, live_rows)
    _write_csv(diagnostics / "backtest_diagnostics.csv", backtest_fields, backtest_rows)
    (diagnostics / "summary.md").write_text("synthetic diagnostics\n", encoding="utf-8")
    outputs = []
    for name in ("closed_trade_diagnostics.csv", "backtest_diagnostics.csv", "summary.md"):
        digest = _sha256(diagnostics / name)
        if tamper_manifest and name == "closed_trade_diagnostics.csv":
            digest = "0" * 64
        outputs.append({"path": str(diagnostics / name), "sha256": digest, "exists": True})
    manifest = {
        "scope": "offline_read_only_strategy_attribution",
        "schema_version": 1,
        "generated_at_utc": "2026-07-04T00:00:00+00:00",
        "outputs": outputs,
        "row_counts": {
            "closed_trade_diagnostics": len(live_rows),
            "backtest_diagnostics": len(backtest_rows),
        },
    }
    (diagnostics / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _row(lane: str, symbol: str, timeframe: str, side: str, result: float, timestamp: str, *, excluded: bool = False) -> dict[str, str]:
    return {
        "lane": lane,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "r_result": str(result),
        "aggregate_r_result": str(result),
        "excluded_from_strategy_analysis": str(excluded),
        "result_time_utc": timestamp,
        "risk_atr_bucket": "lt_0p5",
        "candle_macd_histogram_regime": "positive",
        "candle_tick_volume_regime_252": "low",
        "analysis_session_utc": "london_utc",
        "analysis_weekday_utc": "wednesday",
    }


def _backtest_row(lane: str, symbol: str, timeframe: str, side: str, result: float) -> dict[str, str]:
    return {
        "lane": lane,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "r_result": str(result),
        "exit_time_utc": "2026-06-01T00:00:00Z",
        "recent_last_3m": "True",
        "recent_last_6m": "True",
        "recent_last_12m": "True",
        "risk_atr_bucket": "lt_0p5",
        "candle_macd_histogram_regime": "positive",
        "candle_tick_volume_regime_252": "low",
        "analysis_session_utc": "london_utc",
        "analysis_weekday_utc": "wednesday",
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _find(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise AssertionError(f"row not found: {criteria}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
