from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from build_lp_force_strike_dashboard import _candidate_short  # noqa: E402
from lp_force_strike_dashboard_metadata import load_dashboard_metadata  # noqa: E402


DOCS_ROOT = WORKSPACE_ROOT / "docs"


class DashboardPagesTests(unittest.TestCase):
    def test_metadata_exists_for_all_versioned_pages(self) -> None:
        metadata = load_dashboard_metadata()
        pages = {page["page"]: page for page in metadata["pages"]}

        self.assertEqual(set(pages), {f"v{version}.html" for version in range(1, 18)})
        for version in range(1, 18):
            page = pages[f"v{version}.html"]
            for field in ("title", "question", "setup", "how_to_read", "conclusion", "action", "status_label"):
                self.assertTrue(page[field], f"missing {field} for v{version}")

    def test_every_generated_dashboard_links_to_all_pages(self) -> None:
        expected_links = ['href="index.html"', 'href="strategy.html"', 'href="live_ops.html"'] + [
            f'href="v{version}.html"' for version in range(1, 18)
        ]

        for path in [DOCS_ROOT / "index.html", DOCS_ROOT / "strategy.html", DOCS_ROOT / "live_ops.html"] + [
            DOCS_ROOT / f"v{version}.html" for version in range(1, 18)
        ]:
            html = path.read_text(encoding="utf-8")
            for link in expected_links:
                self.assertIn(link, html, f"{path.name} missing {link}")

    def test_generated_dashboards_use_shared_static_chrome(self) -> None:
        paths = [DOCS_ROOT / "index.html", DOCS_ROOT / "strategy.html", DOCS_ROOT / "live_ops.html"] + [
            DOCS_ROOT / f"v{version}.html" for version in range(1, 18)
        ]

        for path in paths:
            html = path.read_text(encoding="utf-8")
            self.assertIn('class="dashboard-header"', html, f"{path.name} missing shared header")
            self.assertIn('class="report-nav"', html, f"{path.name} missing section navigation")
            self.assertNotIn("<script", html.lower(), f"{path.name} should remain CSS-only")

        for path in [DOCS_ROOT / "index.html", DOCS_ROOT / "strategy.html"] + [
            DOCS_ROOT / f"v{version}.html" for version in range(1, 18)
        ]:
            html = path.read_text(encoding="utf-8")
            self.assertIn('id="metric-glossary"', html, f"{path.name} missing metric glossary")
            self.assertIn("Risk-Reserved DD", html, f"{path.name} missing risk-reserved DD definition")

        for version in range(1, 18):
            html = (DOCS_ROOT / f"v{version}.html").read_text(encoding="utf-8")
            self.assertIn('class="table-scroll"', html, f"v{version}.html missing table scroll wrapper")
            self.assertIn('class="data-table', html, f"v{version}.html missing data-table class")

    def test_current_dashboards_archive_v1_to_v12_navigation(self) -> None:
        for path in (DOCS_ROOT / "index.html", DOCS_ROOT / "strategy.html", DOCS_ROOT / "live_ops.html"):
            html = path.read_text(encoding="utf-8")
            self.assertIn("Archive V1-V12", html)
            self.assertIn('class="archive-nav"', html)
            self.assertIn('href="v1.html"', html)
            self.assertIn('href="v12.html"', html)
            self.assertIn('href="v13.html"', html)
            self.assertIn('href="v17.html"', html)
            self.assertNotIn("<script", html.lower())

    def test_strategy_page_explains_current_strategy_and_limits(self) -> None:
        html = (DOCS_ROOT / "strategy.html").read_text(encoding="utf-8")
        lower_html = html.lower()

        self.assertIn("Current Strategy Guide: V13 Mechanics + V15 Risk Buckets", html)
        self.assertIn("Trade Mechanics Contract", html)
        self.assertIn("Current Baseline In One Screen", html)
        self.assertIn("LP3 take-all", html)
        self.assertIn("H4/H8/H12/D1/W1", html)
        self.assertIn("LP break + raw Force Strike", html)
        self.assertIn("Signal formation", html)
        self.assertIn("Pending entry", html)
        self.assertIn("Stop and target", html)
        self.assertIn("Expiry / cancel", html)
        self.assertIn("Correctness And Verification", html)
        self.assertIn("Research vs Live Execution", html)
        self.assertIn("MT5 live runner", html)
        self.assertIn("Broker expiry is only a conservative emergency backstop", html)
        self.assertIn("Risk Model", html)
        self.assertIn("Invalid / Negative Events", html)
        self.assertIn("Visual Reference", html)
        self.assertIn("LP3", html)
        self.assertIn("6 actual closed bars", html)
        self.assertIn("0.5 signal-candle pullback", html)
        self.assertIn("FS structure stop", html)
        self.assertIn("1R target", html)
        self.assertIn("same-bar stop-first", lower_html)
        self.assertIn("bar 7", html)
        self.assertIn("wrong-side close", lower_html)
        self.assertIn("Gap-through stop or target", html)
        self.assertIn("Missing or zero ATR", html)
        self.assertIn("Risk-reserved DD can exceed realized DD", html)
        self.assertIn("high-return row", lower_html)
        self.assertIn("real MT5 pending orders", html)
        self.assertIn("href=\"live_ops.html\"", html)
        self.assertIn("href=\"v13.html\"", html)
        self.assertIn("href=\"v14.html\"", html)
        self.assertIn("href=\"v15.html\"", html)
        self.assertGreaterEqual(html.count("<svg"), 6)
        self.assertNotIn("<script", lower_html)

    def test_live_ops_page_explains_runtime_scenarios(self) -> None:
        html = (DOCS_ROOT / "live_ops.html").read_text(encoding="utf-8")
        lower_html = html.lower()

        self.assertIn("LP + Force Strike Live Ops", html)
        self.assertIn("Static Verification Guide", html)
        self.assertIn("What Proves The Runner Is Correct", html)
        self.assertIn("MT5 orders_get / positions_get", html)
        self.assertIn("data/live/lpfs_live_state.json", html)
        self.assertIn("data/live/lpfs_live_journal.jsonl", html)
        self.assertIn("Telegram is reporting only", html)
        self.assertIn("Operator Checklist", html)
        self.assertIn("Before starting", html)
        self.assertIn("While running", html)
        self.assertIn("After Telegram alert", html)
        self.assertIn("Send Gates", html)
        self.assertIn("Reconciliation Gates", html)
        self.assertIn("Strategy expiry is after 6 actual MT5 bars from the signal candle", html)
        self.assertIn("Broker expiry is only a conservative emergency backstop", html)
        self.assertIn("Spread Policy", html)
        self.assertIn("Retryable WAITING", html)
        self.assertIn("setups_blocked", html)
        self.assertIn("No spread auto-cancel", html)
        self.assertIn("does not have a dedicated Telegram alert yet", html)
        self.assertIn("Operator Commands", html)
        self.assertIn("RUNNER STARTED / STOPPED", html)
        self.assertIn("Run until manually stopped", html)
        self.assertIn("Phase 2 plan", html)
        self.assertIn("Production wrapper", html)
        self.assertIn("docs/phase2_production_hardening.md", html)
        self.assertIn("href=\"strategy.html\"", html)
        self.assertIn("href=\"v15.html\"", html)
        self.assertNotIn("<script", lower_html)

    def test_entry_wait_pages_show_rejected_conclusion(self) -> None:
        expected = "Do not replace the fixed 6-bar pullback wait"

        for version in (7, 8):
            html = (DOCS_ROOT / f"v{version}.html").read_text(encoding="utf-8")
            self.assertIn(expected, html)
            self.assertIn("Baseline Comparison", html)
            self.assertIn("Fixed 6-bar baseline", html)

    def test_home_page_points_to_current_baseline_not_v8_focus(self) -> None:
        html = (DOCS_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("Current Baseline", html)
        self.assertIn("Current Research Pages", html)
        self.assertIn("Research Archive V1-V12", html)
        self.assertNotIn("Current focus", html)
        self.assertIn("V8 is positive but weaker", html)

    def test_v10_dashboard_is_analysis_first(self) -> None:
        html = (DOCS_ROOT / "v10.html").read_text(encoding="utf-8")

        self.assertIn("Best Practical Mechanics", html)
        self.assertIn("Take-All vs Capped", html)
        self.assertIn("Rejected But Interesting", html)

    def test_v11_dashboard_shows_timeframe_decision_sections(self) -> None:
        html = (DOCS_ROOT / "v11.html").read_text(encoding="utf-8")

        self.assertIn("Best Timeframe Mix", html)
        self.assertIn("H4/H8 Decision", html)
        self.assertIn("Underwater Reduction", html)
        self.assertIn("LP4/LP5 Diagnostics", html)

    def test_v12_dashboard_shows_lp_pivot_decision_sections(self) -> None:
        html = (DOCS_ROOT / "v12.html").read_text(encoding="utf-8")

        self.assertIn("All-Timeframe Pivot Decision", html)
        self.assertIn("Quality vs Profitability", html)
        self.assertIn("Drawdown Smoothness", html)
        self.assertIn("No-H4 Robustness Contrast", html)

    def test_recent_dashboards_show_chat_style_decision_brief(self) -> None:
        metadata = load_dashboard_metadata()
        pages = {page["page"]: page for page in metadata["pages"]}

        for version in range(10, 18):
            self.assertIn("decision_brief", pages[f"v{version}.html"])
            html = (DOCS_ROOT / f"v{version}.html").read_text(encoding="utf-8")
            self.assertIn("Decision Brief", html)

        v11_html = (DOCS_ROOT / "v11.html").read_text(encoding="utf-8")
        self.assertIn("Remove H4: lower DD/underwater, but gives up about 308R", v11_html)
        self.assertIn("Remove H8: gives up about 157R", v11_html)

    def test_v13_dashboard_shows_relaxed_portfolio_sections(self) -> None:
        html = (DOCS_ROOT / "v13.html").read_text(encoding="utf-8")

        self.assertIn("Decision Brief", html)
        self.assertIn("Portfolio Rule Leaderboard", html)
        self.assertIn("Exposure Reality Check", html)
        self.assertIn("Period Robustness", html)
        self.assertIn("Ticker Robustness", html)

    def test_v14_dashboard_shows_risk_sizing_sections(self) -> None:
        html = (DOCS_ROOT / "v14.html").read_text(encoding="utf-8")

        self.assertIn("Decision Brief", html)
        self.assertIn("Risk Schedule Composition", html)
        self.assertIn("Tight H12-D1 basket (recommended)", html)
        self.assertIn("<td>0.15%</td><td>0.15%</td><td>0.30%</td><td>0.30%</td><td>0.45%</td>", html)
        self.assertIn("Risk Tolerance Calibration", html)
        self.assertIn("target risk-reserved DD / current risk-reserved DD", html)
        self.assertIn("Target Risk-Reserved DD", html)
        self.assertIn("Fixed Risk Drawdown", html)
        self.assertIn("Timeframe Ladder Drawdown", html)
        self.assertIn("Risk-Reserved Drawdown", html)
        self.assertIn("Worst Day / Week / Month", html)
        self.assertIn("Max Concurrent Exposure", html)
        self.assertIn("Timeframe Contribution", html)

    def test_v15_dashboard_shows_bucket_sensitivity_sections(self) -> None:
        html = (DOCS_ROOT / "v15.html").read_text(encoding="utf-8")

        self.assertIn("Decision Brief", html)
        self.assertIn("Risk Bucket Sensitivity", html)
        self.assertIn("Practical Return Leaderboard", html)
        self.assertIn("Most-efficient practical row", html)
        self.assertIn("H4/H8 0.20%, H12/D1 0.30%, W1 0.75%", html)
        self.assertIn("Grid Heatmap By W1 Risk", html)
        self.assertIn("Recommended Ladder Timeframe Contribution", html)

    def test_v16_dashboard_shows_execution_realism_sections(self) -> None:
        html = (DOCS_ROOT / "v16.html").read_text(encoding="utf-8")

        self.assertIn("Decision Brief", html)
        self.assertIn("Decision Read", html)
        self.assertIn("Trade-Level Bid/Ask Result", html)
        self.assertIn("V15 Bucket Sensitivity Rerun", html)
        self.assertIn("Highest Spread Pressure Pockets", html)
        self.assertIn("Long entry requires Ask low", html)
        self.assertIn("Research-only; no MT5 live calls", html)

    def test_v17_dashboard_shows_proximity_sections(self) -> None:
        html = (DOCS_ROOT / "v17.html").read_text(encoding="utf-8")

        self.assertIn("Decision Brief", html)
        self.assertIn("Decision Read", html)
        self.assertIn("Trade-Level Proximity Result", html)
        self.assertIn("V15 Bucket Sensitivity Rerun", html)
        self.assertIn("Quality Buckets Without Filtering", html)
        self.assertIn("Strict touch for longs requires", html)
        self.assertIn("Research-only; no MT5 live calls", html)

    def test_risk_dashboard_drawdown_meanings_and_values_are_preserved(self) -> None:
        v14_html = (DOCS_ROOT / "v14.html").read_text(encoding="utf-8")
        self.assertIn("Realized DD", v14_html)
        self.assertIn("Risk-Reserved DD", v14_html)
        self.assertIn("Closed-trade equity drawdown only", v14_html)
        self.assertIn("Live-account stress drawdown", v14_html)
        self.assertIn("Tight H12-D1 basket", v14_html)
        self.assertIn("324.18%", v14_html)
        self.assertIn("5.90%", v14_html)
        self.assertIn("7.86%", v14_html)

        v15_html = (DOCS_ROOT / "v15.html").read_text(encoding="utf-8")
        self.assertIn("Realized DD", v15_html)
        self.assertIn("Reserved DD", v15_html)
        self.assertIn("Highest-return practical row", v15_html)
        self.assertIn("421.82%", v15_html)
        self.assertIn("8.22%", v15_html)
        self.assertIn("9.72%", v15_html)
        self.assertIn("Most-efficient practical row", v15_html)
        self.assertIn("383.17%", v15_html)
        self.assertIn("6.57%", v15_html)
        self.assertIn("7.89%", v15_html)

    def test_lp_pivot_candidate_labels_are_readable(self) -> None:
        label = _candidate_short("lp_pivot_2__signal_zone_0p5_pullback__fs_structure__1r")

        self.assertEqual(label, "LP pivot 2 / zone 0.5 pullback / structure / 1R")


if __name__ == "__main__":
    unittest.main()
