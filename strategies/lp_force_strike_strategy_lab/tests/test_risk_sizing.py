from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from run_lp_force_strike_risk_sizing_experiment import (  # noqa: E402
    _max_drawdown_from_curve,
    apply_risk_schedule,
    contribution_rows,
    exposure_metrics,
    realized_equity_curve,
    risk_pct_for_timeframe,
    risk_reserved_equity_curve,
    worst_periods,
)


def _trades(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": row.get("symbol", "EURUSD"),
                "timeframe": row.get("timeframe", "H4"),
                "entry_time_utc": pd.Timestamp(row["entry"], tz="UTC"),
                "exit_time_utc": pd.Timestamp(row["exit"], tz="UTC"),
                "net_r": float(row["net_r"]),
            }
            for row in rows
        ]
    )


class RiskSizingTests(unittest.TestCase):
    def test_fixed_risk_applies_to_every_timeframe(self) -> None:
        schedule = {"schedule_id": "fixed", "label": "Fixed", "kind": "fixed", "risk_pct": 0.25}

        self.assertEqual(risk_pct_for_timeframe(schedule, "H4"), 0.25)
        self.assertEqual(risk_pct_for_timeframe(schedule, "W1"), 0.25)

    def test_ladder_risk_applies_by_timeframe_and_unknown_fails(self) -> None:
        schedule = {
            "schedule_id": "ladder",
            "label": "Ladder",
            "kind": "timeframe",
            "risk_by_timeframe": {"H4": 0.10, "H8": 0.10, "D1": 0.40},
        }

        self.assertEqual(risk_pct_for_timeframe(schedule, "H4"), 0.10)
        self.assertEqual(risk_pct_for_timeframe(schedule, "D1"), 0.40)
        with self.assertRaisesRegex(ValueError, "no risk for timeframe"):
            risk_pct_for_timeframe(schedule, "M30")

    def test_realized_drawdown_uses_trade_exits(self) -> None:
        frame = apply_risk_schedule(
            _trades(
                [
                    {"entry": "2026-01-01", "exit": "2026-01-01", "net_r": 2.0},
                    {"entry": "2026-01-02", "exit": "2026-01-02", "net_r": -1.0},
                    {"entry": "2026-01-05", "exit": "2026-01-05", "net_r": -1.0},
                    {"entry": "2026-01-08", "exit": "2026-01-08", "net_r": 2.0},
                ]
            ),
            {"schedule_id": "fixed", "label": "Fixed", "kind": "fixed", "risk_pct": 1.0},
        )

        curve = realized_equity_curve(frame)
        drawdown = _max_drawdown_from_curve(curve, "equity_pct")

        self.assertEqual(curve["equity_pct"].tolist(), [2.0, 1.0, 0.0, 2.0])
        self.assertEqual(drawdown["max_drawdown_pct"], 2.0)
        self.assertEqual(drawdown["longest_underwater_days"], 6.0)

    def test_risk_reserved_drawdown_includes_open_trade_risk(self) -> None:
        frame = apply_risk_schedule(
            _trades(
                [
                    {"symbol": "EURUSD", "entry": "2026-01-01", "exit": "2026-01-03", "net_r": 1.0},
                    {"symbol": "EURUSD", "entry": "2026-01-02", "exit": "2026-01-04", "net_r": -1.0},
                ]
            ),
            {"schedule_id": "fixed", "label": "Fixed", "kind": "fixed", "risk_pct": 1.0},
        )

        realized = _max_drawdown_from_curve(realized_equity_curve(frame), "equity_pct")
        reserved_curve = risk_reserved_equity_curve(frame)
        reserved = _max_drawdown_from_curve(reserved_curve, "equity_reserved_pct")

        self.assertEqual(float(reserved_curve["open_risk_pct"].max()), 2.0)
        self.assertEqual(realized["max_drawdown_pct"], 1.0)
        self.assertEqual(reserved["max_drawdown_pct"], 2.0)

    def test_worst_day_week_month_are_deterministic(self) -> None:
        frame = apply_risk_schedule(
            _trades(
                [
                    {"entry": "2026-01-01", "exit": "2026-01-01", "net_r": 1.0},
                    {"entry": "2026-01-02", "exit": "2026-01-02", "net_r": -2.0},
                    {"entry": "2026-01-09", "exit": "2026-01-09", "net_r": -1.0},
                ]
            ),
            {"schedule_id": "fixed", "label": "Fixed", "kind": "fixed", "risk_pct": 1.0},
        )

        periods = worst_periods(frame)

        self.assertEqual(periods["negative_days"], 2)
        self.assertEqual(periods["worst_day"], "2026-01-02")
        self.assertEqual(periods["worst_day_pct"], -2.0)
        self.assertEqual(periods["negative_weeks"], 2)
        self.assertEqual(periods["negative_months"], 1)
        self.assertEqual(periods["worst_month_pct"], -2.0)

    def test_exposure_metrics_track_concurrency_and_reserved_risk(self) -> None:
        frame = apply_risk_schedule(
            _trades(
                [
                    {"symbol": "EURUSD", "entry": "2026-01-01", "exit": "2026-01-05", "net_r": 1.0},
                    {"symbol": "EURUSD", "entry": "2026-01-02", "exit": "2026-01-06", "net_r": 1.0},
                    {"symbol": "GBPUSD", "entry": "2026-01-02", "exit": "2026-01-03", "net_r": 1.0},
                ]
            ),
            {"schedule_id": "fixed", "label": "Fixed", "kind": "fixed", "risk_pct": 0.5},
        )

        metrics = exposure_metrics(frame)

        self.assertEqual(metrics["max_concurrent_trades"], 3)
        self.assertEqual(metrics["max_same_symbol_stack"], 2)
        self.assertEqual(metrics["max_new_trades_same_time"], 2)
        self.assertEqual(metrics["max_reserved_open_risk_pct"], 1.5)

    def test_timeframe_contribution_totals(self) -> None:
        frame = apply_risk_schedule(
            _trades(
                [
                    {"timeframe": "H4", "entry": "2026-01-01", "exit": "2026-01-02", "net_r": 1.0},
                    {"timeframe": "H4", "entry": "2026-01-03", "exit": "2026-01-04", "net_r": -1.0},
                    {"timeframe": "D1", "entry": "2026-01-05", "exit": "2026-01-06", "net_r": 2.0},
                ]
            ),
            {
                "schedule_id": "ladder",
                "label": "Ladder",
                "kind": "timeframe",
                "risk_by_timeframe": {"H4": 0.25, "D1": 0.50},
            },
        )

        rows = contribution_rows(frame, "timeframe")
        d1 = rows[rows["timeframe"] == "D1"].iloc[0]
        h4 = rows[rows["timeframe"] == "H4"].iloc[0]

        self.assertEqual(float(d1["total_return_pct"]), 1.0)
        self.assertEqual(float(h4["total_return_pct"]), 0.0)
        self.assertEqual(int(h4["trades"]), 2)


if __name__ == "__main__":
    unittest.main()
