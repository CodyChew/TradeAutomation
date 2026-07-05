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
SCRIPT = WORKSPACE_ROOT / "scripts" / "build_lpfs_candidate_backtest_matrix.py"


class CandidateBacktestMatrixBuilderTests(unittest.TestCase):
    def test_cli_builds_guarded_candidate_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            config = tmp / "candidate_config.json"
            _write_diagnostics_packet(diagnostics)
            _write_candidate_config(config)

            result = _run_builder(diagnostics, config, tmp / "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            output_dir = tmp / "out" / "20260705_000000"
            decision_rows = _read_csv(output_dir / "candidate_decision_summary.csv")
            guardrails = _read_csv(output_dir / "candidate_guardrails.csv")
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            summary = (output_dir / "summary.md").read_text(encoding="utf-8")

            risk = _find(decision_rows, candidate_id="h8_risk_atr_lt_0p5")
            self.assertEqual(risk["decision"], "active_research_candidate_backtest_supported")
            self.assertEqual(risk["backtest_guardrail_status"], "complete")
            self.assertEqual(risk["current_live_trades"], "4")
            self.assertEqual(risk["current_live_net_r"], "-4.000000")
            self.assertEqual(risk["negative_windows"], "all,last_12m,last_6m,last_3m")
            self.assertEqual(risk["improving_exclusion_windows"], "all,last_12m,last_6m,last_3m")

            macd = _find(decision_rows, candidate_id="macd_negative")
            self.assertEqual(macd["decision"], "data_gap_backtest_factor_coverage")
            self.assertEqual(macd["backtest_guardrail_status"], "incomplete_factor_coverage")

            guard = _find(guardrails, candidate_id="macd_negative")
            self.assertEqual(guard["backtest_guardrail_status"], "incomplete_factor_coverage")
            self.assertEqual(guard["requires_candle_provenance"], "true")

            self.assertEqual(manifest["scope"], "offline_read_only_strategy_research")
            self.assertEqual(manifest["report"], "lpfs_candidate_backtest_matrix")
            self.assertEqual(manifest["row_counts"]["candidate_decision_summary"], 3)
            self.assertTrue(any(output["path"].endswith("candidate_guardrails.csv") for output in manifest["outputs"]))
            self.assertIn("no_vps_access", manifest["non_actions"])
            self.assertIn("research_only_not_live_approval", json.dumps(manifest))
            self.assertIn("offline/read-only", summary)
            self.assertIn("does not approve live strategy", summary)

    def test_source_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            config = tmp / "candidate_config.json"
            _write_diagnostics_packet(diagnostics, tamper_manifest=True)
            _write_candidate_config(config)

            result = _run_builder(diagnostics, config, tmp / "out")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source hash mismatch", result.stderr)

    def test_optional_factor_manifest_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            factor_dir = tmp / "factor"
            config = tmp / "candidate_config.json"
            _write_diagnostics_packet(diagnostics)
            _write_factor_packet(factor_dir, tamper_manifest=True)
            _write_candidate_config(config)

            result = _run_builder(diagnostics, config, tmp / "out", factor_dir=factor_dir)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source hash mismatch", result.stderr)

    def test_missing_recent_window_column_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            diagnostics = tmp / "diagnostics"
            config = tmp / "candidate_config.json"
            _write_diagnostics_packet(diagnostics, omit_recent_window=True)
            _write_candidate_config(config)

            result = _run_builder(diagnostics, config, tmp / "out")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing recent-window columns", result.stderr)


def _run_builder(
    diagnostics: Path,
    config: Path,
    output_root: Path,
    *,
    factor_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--diagnostics-dir",
        str(diagnostics),
        "--candidate-config",
        str(config),
        "--output-root",
        str(output_root),
        "--as-of-utc",
        "2026-07-05T00:00:00Z",
    ]
    if factor_dir is not None:
        command.extend(["--factor-attribution-dir", str(factor_dir)])
    return subprocess.run(
        command,
        cwd=WORKSPACE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_candidate_config(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "description": "synthetic research-only candidate config",
        "decision_boundary": "research_only_not_live_approval",
        "candidate_defaults": {
            "min_live_trades": 4,
            "max_removal_share": 0.6,
            "complete_coverage_threshold": 0.8,
        },
        "candidates": [
            {
                "candidate_id": "h8_risk_atr_lt_0p5",
                "candidate_label": "H8 + Risk/ATR < 0.5",
                "candidate_type": "primary",
                "source_factor_family": "price_structure",
                "filters": {"timeframe": "h8", "risk_atr_bucket": "lt_0p5"},
                "rationale": "synthetic supported candidate",
            },
            {
                "candidate_id": "macd_negative",
                "candidate_label": "MACD negative",
                "candidate_type": "diagnostic",
                "source_factor_family": "momentum",
                "filters": {"candle_macd_histogram_regime": "negative"},
                "rationale": "synthetic incomplete coverage candidate",
            },
            {
                "candidate_id": "long_side",
                "candidate_label": "Long side",
                "candidate_type": "broad",
                "source_factor_family": "core",
                "filters": {"side": "long"},
                "rationale": "synthetic broad context",
            },
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_diagnostics_packet(
    diagnostics: Path,
    *,
    tamper_manifest: bool = False,
    omit_recent_window: bool = False,
) -> None:
    diagnostics.mkdir(parents=True)
    live_fields = [
        "lane",
        "symbol",
        "timeframe",
        "side",
        "r_result",
        "aggregate_r_result",
        "close_profit",
        "excluded_from_strategy_analysis",
        "result_time_utc",
        "risk_atr_bucket",
        "setup_age_bars_bucket",
        "candle_macd_histogram_regime",
    ]
    backtest_fields = [
        "lane",
        "symbol",
        "timeframe",
        "side",
        "r_result",
        "risk_atr_bucket",
        "setup_age_bars_bucket",
        "candle_macd_histogram_regime",
        "recent_last_3m",
        "recent_last_6m",
        "recent_last_12m",
    ]
    if omit_recent_window:
        backtest_fields.remove("recent_last_3m")
    live_rows = [
        _live("FTMO", "EURUSD", "H8", "LONG", -1.0, "lt_0p5", "negative"),
        _live("FTMO", "GBPUSD", "H8", "SHORT", -1.0, "lt_0p5", "negative"),
        _live("IC", "EURUSD", "H8", "LONG", -1.0, "lt_0p5", "negative"),
        _live("IC", "GBPUSD", "H8", "SHORT", -1.0, "lt_0p5", "negative"),
        _live("FTMO", "AUDUSD", "H4", "LONG", 2.0, "0p5_to_1", "positive"),
        _live("IC", "AUDUSD", "H4", "LONG", 2.0, "0p5_to_1", "positive"),
    ]
    backtest_rows = [
        _backtest("FTMO", "EURUSD", "H8", "LONG", -1.0, "lt_0p5", "negative"),
        _backtest("FTMO", "GBPUSD", "H8", "SHORT", -1.0, "lt_0p5", ""),
        _backtest("IC", "EURUSD", "H8", "LONG", -1.0, "lt_0p5", ""),
        _backtest("IC", "GBPUSD", "H8", "SHORT", -1.0, "lt_0p5", ""),
        _backtest("FTMO", "AUDUSD", "H4", "LONG", 2.0, "0p5_to_1", ""),
        _backtest("IC", "AUDUSD", "H4", "LONG", 2.0, "0p5_to_1", ""),
        _backtest("FTMO", "USDJPY", "D1", "SHORT", 1.0, "gte_1p5", ""),
        _backtest("IC", "USDJPY", "D1", "SHORT", 1.0, "gte_1p5", ""),
    ]
    if omit_recent_window:
        backtest_rows = [{key: value for key, value in row.items() if key != "recent_last_3m"} for row in backtest_rows]
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
        "generated_at_utc": "2026-07-05T00:00:00+00:00",
        "inputs": {
            "candle_sources": [
                {
                    "lane": "FTMO",
                    "path": str(diagnostics / "candles"),
                    "provenance": "vps_lane_broker_feed",
                    "validation_status": "validated",
                    "safe_for_strategy_analysis": True,
                }
            ]
        },
        "outputs": outputs,
        "row_counts": {
            "closed_trade_diagnostics": len(live_rows),
            "backtest_diagnostics": len(backtest_rows),
        },
    }
    (diagnostics / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _write_factor_packet(factor_dir: Path, *, tamper_manifest: bool = False) -> None:
    factor_dir.mkdir(parents=True)
    matrix = factor_dir / "factor_attribution_matrix.csv"
    confluence = factor_dir / "cross_lane_factor_confluence.csv"
    matrix.write_text("lane,dimension,value\nFTMO,risk_atr_bucket,lt_0p5\n", encoding="utf-8")
    confluence.write_text("dimension,value,confluence_status\nrisk_atr_bucket,lt_0p5,both_lanes_negative\n", encoding="utf-8")
    outputs = []
    for path in (matrix, confluence):
        digest = _sha256(path)
        if tamper_manifest and path.name == "factor_attribution_matrix.csv":
            digest = "1" * 64
        outputs.append({"path": str(path), "sha256": digest, "exists": True})
    manifest = {
        "scope": "offline_read_only_factor_attribution",
        "schema_version": 1,
        "outputs": outputs,
    }
    (factor_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _live(lane: str, symbol: str, timeframe: str, side: str, result: float, risk_bucket: str, macd: str) -> dict[str, str]:
    return {
        "lane": lane,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "r_result": str(result),
        "aggregate_r_result": str(result),
        "close_profit": str(result * 10),
        "excluded_from_strategy_analysis": "False",
        "result_time_utc": "2026-07-01T00:00:00Z",
        "risk_atr_bucket": risk_bucket,
        "setup_age_bars_bucket": "1",
        "candle_macd_histogram_regime": macd,
    }


def _backtest(lane: str, symbol: str, timeframe: str, side: str, result: float, risk_bucket: str, macd: str) -> dict[str, str]:
    return {
        "lane": lane,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "r_result": str(result),
        "risk_atr_bucket": risk_bucket,
        "setup_age_bars_bucket": "1",
        "candle_macd_histogram_regime": macd,
        "recent_last_3m": "True",
        "recent_last_6m": "True",
        "recent_last_12m": "True",
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
