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

        self.assertEqual(set(pages), {f"v{version}.html" for version in range(1, 13)})
        for version in range(1, 13):
            page = pages[f"v{version}.html"]
            for field in ("title", "question", "setup", "how_to_read", "conclusion", "action", "status_label"):
                self.assertTrue(page[field], f"missing {field} for v{version}")

    def test_every_generated_dashboard_links_to_all_pages(self) -> None:
        expected_links = ['href="index.html"'] + [f'href="v{version}.html"' for version in range(1, 13)]

        for path in [DOCS_ROOT / "index.html"] + [DOCS_ROOT / f"v{version}.html" for version in range(1, 13)]:
            html = path.read_text(encoding="utf-8")
            for link in expected_links:
                self.assertIn(link, html, f"{path.name} missing {link}")

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

    def test_lp_pivot_candidate_labels_are_readable(self) -> None:
        label = _candidate_short("lp_pivot_2__signal_zone_0p5_pullback__fs_structure__1r")

        self.assertEqual(label, "LP pivot 2 / zone 0.5 pullback / structure / 1R")


if __name__ == "__main__":
    unittest.main()
