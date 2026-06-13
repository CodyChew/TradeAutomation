from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from run_lpfs_ftmo_challenge_frontier import (  # noqa: E402
    RiskProfile,
    challenge_window_outcomes,
    classify_limit,
    daily_loss_stress,
    frontier_risk_profiles,
    spread_gate_pass,
    write_outputs,
)


def _test_profile() -> RiskProfile:
    return RiskProfile(lower_risk_pct=1.0, middle_risk_pct=1.0, w1_risk_pct=1.0)


def _trade_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    data = pd.DataFrame(rows)
    data["symbol"] = data.get("symbol", "EURUSD")
    data["timeframe"] = data.get("timeframe", "H4")
    data["entry_time_utc"] = pd.to_datetime(data["entry_time_utc"], utc=True)
    data["exit_time_utc"] = pd.to_datetime(data["exit_time_utc"], utc=True)
    return data


def _window_row(windows: pd.DataFrame, *, target_type: str, start_utc: str) -> dict[str, object]:
    start = pd.Timestamp(start_utc).tz_convert("UTC").isoformat()
    rows = windows[(windows["target_type"] == target_type) & (windows["start_utc"] == start)]
    if rows.empty:
        raise AssertionError(f"No {target_type} window found for {start}")
    return rows.iloc[0].to_dict()


class FTMOChallengeFrontierTests(unittest.TestCase):
    def test_frontier_grid_includes_midpoint_candidate(self) -> None:
        profiles = frontier_risk_profiles()
        lookup = {(p.lower_risk_pct, p.middle_risk_pct, p.w1_risk_pct) for p in profiles}

        self.assertIn((0.15, 0.25, 0.70), lookup)
        self.assertEqual(len(profiles), 7 * 6 * 7)

    def test_daily_loss_stress_uses_day_start_balance_minus_reserved_equity(self) -> None:
        curve = pd.DataFrame(
            [
                {
                    "time_utc": pd.Timestamp("2026-01-01T04:00:00Z"),
                    "day_start_realized_pct": 1.0,
                    "equity_reserved_pct": -3.6,
                },
                {
                    "time_utc": pd.Timestamp("2026-01-01T08:00:00Z"),
                    "day_start_realized_pct": 1.0,
                    "equity_reserved_pct": -4.2,
                },
            ]
        )

        stress = daily_loss_stress(curve)

        self.assertEqual(len(stress), 1)
        self.assertAlmostEqual(float(stress.iloc[0]["daily_loss_stress_pct"]), 5.2)
        self.assertEqual(stress.iloc[0]["daily_loss_status"], "breach")

    def test_limit_classifier_has_pass_warning_and_breach_bands(self) -> None:
        self.assertEqual(classify_limit(4.49, warning_threshold=4.5, breach_threshold=5.0), "pass")
        self.assertEqual(classify_limit(4.5, warning_threshold=4.5, breach_threshold=5.0), "warning")
        self.assertEqual(classify_limit(5.0, warning_threshold=4.5, breach_threshold=5.0), "breach")

    def test_spread_gate_allows_exact_ten_percent_threshold(self) -> None:
        self.assertTrue(spread_gate_pass(0.10, max_spread_risk_fraction=0.10))
        self.assertFalse(spread_gate_pass(0.10001, max_spread_risk_fraction=0.10))
        self.assertFalse(spread_gate_pass(None, max_spread_risk_fraction=0.10))

    def test_challenge_window_ignores_target_hit_after_window_end(self) -> None:
        trades = _trade_frame(
            [
                {
                    "entry_time_utc": "2026-01-01T00:00:00Z",
                    "exit_time_utc": "2026-01-03T00:00:00Z",
                    "net_r": 10.0,
                }
            ]
        )

        windows = challenge_window_outcomes(trades, [_test_profile()], max_window_days=1, start_frequency="1D")
        row = _window_row(windows, target_type="challenge", start_utc="2026-01-01T00:00:00Z")

        self.assertEqual(row["outcome"], "unresolved")
        self.assertIsNone(row["days_to_outcome"])

    def test_challenge_window_days_to_outcome_start_from_window_start(self) -> None:
        trades = _trade_frame(
            [
                {
                    "entry_time_utc": "2026-01-01T00:00:00Z",
                    "exit_time_utc": "2026-01-01T01:00:00Z",
                    "net_r": 0.0,
                },
                {
                    "entry_time_utc": "2026-01-15T00:00:00Z",
                    "exit_time_utc": "2026-01-16T00:00:00Z",
                    "net_r": 10.0,
                },
            ]
        )

        windows = challenge_window_outcomes(trades, [_test_profile()], max_window_days=30, start_frequency="7D")
        row = _window_row(windows, target_type="challenge", start_utc="2026-01-08T00:00:00Z")

        self.assertEqual(row["outcome"], "hit_target")
        self.assertAlmostEqual(float(row["days_to_outcome"]), 8.0)

    def test_challenge_window_includes_start_and_excludes_end_boundary(self) -> None:
        trades = _trade_frame(
            [
                {
                    "entry_time_utc": "2026-01-01T00:00:00Z",
                    "exit_time_utc": "2026-01-01T12:00:00Z",
                    "net_r": 5.0,
                },
                {
                    "entry_time_utc": "2026-01-02T00:00:00Z",
                    "exit_time_utc": "2026-01-02T12:00:00Z",
                    "net_r": 10.0,
                },
            ]
        )

        windows = challenge_window_outcomes(trades, [_test_profile()], max_window_days=1, start_frequency="1D")
        verification = _window_row(windows, target_type="verification", start_utc="2026-01-01T00:00:00Z")
        challenge = _window_row(windows, target_type="challenge", start_utc="2026-01-01T00:00:00Z")

        self.assertEqual(verification["outcome"], "hit_target")
        self.assertAlmostEqual(float(verification["days_to_outcome"]), 0.5)
        self.assertEqual(challenge["outcome"], "unresolved")

    def test_report_writes_deterministic_csv_content(self) -> None:
        frontier = pd.DataFrame(
            [
                {
                    "profile_id": "ltf0p150_h12d10p250_w10p700",
                    "profile_label": "H4/H8 0.15% / H12/D1 0.25% / W1 0.7%",
                    "mode": "base",
                    "total_return_pct": 1.234567,
                }
            ]
        )
        candidates = pd.DataFrame(
            [
                {
                    "profile_id": "ltf0p150_h12d10p250_w10p700",
                    "profile_label": "H4/H8 0.15% / H12/D1 0.25% / W1 0.7%",
                    "selection_role": "fresh_challenge",
                    "total_return_pct": 1.234567,
                    "reserved_max_drawdown_pct": 0.5,
                    "max_daily_loss_stress_pct": 0.25,
                    "max_reserved_open_risk_pct": 0.75,
                    "worst_month_pct": -0.1,
                    "median_month_pct": 0.2,
                    "p25_month_pct": -0.05,
                    "p75_month_pct": 0.4,
                }
            ]
        )
        daily = pd.DataFrame([{"profile_id": "ltf0p150_h12d10p250_w10p700", "daily_loss_stress_pct": 0.25}])
        spread = pd.DataFrame(
            [
                {
                    "symbol": "ALL",
                    "timeframe": "ALL",
                    "trades": 10,
                    "initial_spread_failures": 1,
                    "initial_spread_failure_rate": 0.1,
                    "avg_spread_to_risk_pct": 3.0,
                    "p90_spread_to_risk_pct": 8.0,
                }
            ]
        )
        windows = pd.DataFrame(
            [
                {
                    "profile_id": "ltf0p150_h12d10p250_w10p700",
                    "target_type": "challenge",
                    "outcome": "hit_target",
                    "days_to_outcome": 30.0,
                }
            ]
        )
        summary = {
            "generated_at_utc": "2026-01-01T00:00:00+00:00",
            "output_dir": "out",
            "docs_output": "docs/ftmo_challenge_profiles.html",
        }

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            write_outputs(
                output_dir=Path(first),
                docs_output=Path(first) / "docs.html",
                frontier=frontier,
                candidates=candidates,
                daily=daily,
                spread=spread,
                windows=windows,
                run_summary=summary,
            )
            write_outputs(
                output_dir=Path(second),
                docs_output=Path(second) / "docs.html",
                frontier=frontier,
                candidates=candidates,
                daily=daily,
                spread=spread,
                windows=windows,
                run_summary=summary,
            )

            self.assertEqual(
                (Path(first) / "frontier_summary.csv").read_text(encoding="utf-8"),
                (Path(second) / "frontier_summary.csv").read_text(encoding="utf-8"),
            )
            self.assertIn("LPFS FTMO Challenge Profiles", (Path(first) / "dashboard.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
