from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from export_lpfs_ea_fixtures import BASE_RISK_PROFILES, build_fixture_payload  # noqa: E402


EA_ROOT = WORKSPACE_ROOT / "mql5" / "lpfs_ea"
EA_SOURCE = EA_ROOT / "Experts" / "LPFS" / "LPFS_EA.mq5"
CANONICAL_FIXTURE = EA_ROOT / "fixtures" / "canonical_lpfs_ea_fixture.json"


class EaMigrationTests(unittest.TestCase):
    def test_mql_source_is_tester_only_and_blackbox_by_default(self) -> None:
        source = EA_SOURCE.read_text(encoding="utf-8")

        self.assertIn("input ENUM_LPFS_RISK_PROFILE InpRiskProfile", source)
        self.assertIn("input long                   InpMagicNumber", source)
        self.assertIn("input bool                   InpTesterOnly", source)
        self.assertIn("input bool                   InpAllowLiveTrading", source)
        self.assertIn("MQL_TESTER", source)
        self.assertIn("INIT_FAILED", source)
        self.assertIn("LPFSEA", source)
        self.assertIn("331500", source)
        self.assertIn("LPFS_MAX_SPREAD_RISK_FRACTION = 0.10", source)
        self.assertIn("PrintBacktestDisclosure", source)
        self.assertIn("Effective Risk Schedule", source)
        self.assertIn("ExposureGatePass", source)
        self.assertIn("ActiveMaxOpenRiskPct", source)
        self.assertIn("InpMaxOpenRiskPct     = 0.0", source)
        self.assertNotIn("input double                 InpMaxSpreadRiskFraction", source)
        self.assertNotIn("input double                 InpRiskH4", source)
        self.assertNotIn("input double                 InpRiskW1", source)

    def test_fixture_payload_is_deterministic_and_covers_required_cases(self) -> None:
        first = build_fixture_payload()
        second = build_fixture_payload()

        self.assertEqual(first, second)
        self.assertEqual(first["fixture_version"], 1)
        self.assertEqual(first["risk_profiles"], BASE_RISK_PROFILES)
        self.assertEqual(len(first["approved_symbols"]), 28)
        self.assertEqual(first["approved_timeframes"], ["H4", "H8", "H12", "D1", "W1"])

        cases = first["cases"]
        for key in ["valid_long_signal", "valid_short_signal", "no_signal", "invalid_lp_fs_separation", "rejections"]:
            self.assertIn(key, cases)

        self.assertEqual(cases["valid_long_signal"]["signal"]["side"], "bullish")
        self.assertEqual(cases["valid_short_signal"]["signal"]["side"], "bearish")
        self.assertEqual(cases["no_signal"]["signals"], [])
        self.assertEqual(cases["invalid_lp_fs_separation"]["default_signal_count"], 0)
        self.assertEqual(cases["invalid_lp_fs_separation"]["legacy_signal_count"], 1)

        rejection_cases = cases["rejections"]
        for key in [
            "spread_too_wide_dynamic",
            "volume_below_min",
            "sl_tp_too_close",
            "pending_expired",
            "duplicate_signal",
            "max_open_risk",
        ]:
            self.assertIn(key, rejection_cases)

        self.assertFalse(rejection_cases["spread_too_wide_dynamic"]["passed"])
        self.assertEqual(rejection_cases["volume_below_min"]["rejection_reason"], "volume_below_min")
        self.assertEqual(rejection_cases["sl_tp_too_close"]["rejection_reason"], "sl_tp_too_close")
        self.assertEqual(rejection_cases["pending_expired"]["rejection_reason"], "pending_expired")
        self.assertEqual(rejection_cases["duplicate_signal"]["rejection_reason"], "duplicate_signal")
        self.assertEqual(rejection_cases["max_open_risk"]["rejection_reason"], "max_open_risk")

    def test_canonical_fixture_matches_python_truth(self) -> None:
        canonical = json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(canonical, build_fixture_payload())

    def test_migration_docs_capture_operator_and_live_boundaries(self) -> None:
        readme = (EA_ROOT / "README.md").read_text(encoding="utf-8")
        page = (WORKSPACE_ROOT / "docs" / "ea_migration.html").read_text(encoding="utf-8")
        tester_template = (EA_ROOT / "tester" / "lpfs_tester_first_run.ini").read_text(encoding="utf-8")
        compile_helper = (EA_ROOT / "scripts" / "Compile-LpfsEa.ps1").read_text(encoding="utf-8")

        for text in [readme, page, tester_template]:
            self.assertIn("Strategy Tester", text)
            self.assertIn("FTMO", text)
            self.assertIn("IC", text)
            self.assertIn("Do not attach", text)

        self.assertIn("No VPS, config, state, journal, or order changes", page)
        self.assertIn("tester load/config smoke passed", page)
        self.assertIn("InpSmokeTestSingleChartOnly", page)
        self.assertIn("full 28-symbol x 5-timeframe basket on every tick", page)
        self.assertIn("Conservative", page)
        self.assertIn("Standard", page)
        self.assertIn("Growth", page)
        self.assertIn("MagicNumber=331500", page)
        self.assertIn("CommentPrefix=LPFSEA", page)
        self.assertIn("MetaEditor", compile_helper)
        self.assertIn("No live terminal, VPS runtime, config, state, journal, or broker order was touched", compile_helper)
        self.assertIn("Full-result smoke: pending", readme)
        self.assertIn("InpSmokeTestSingleChartOnly=true", readme)


if __name__ == "__main__":
    unittest.main()
