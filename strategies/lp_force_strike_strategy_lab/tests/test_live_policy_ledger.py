from __future__ import annotations

import csv
import json
import unittest
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
LEDGER_PATH = WORKSPACE_ROOT / "configs/live_policy_ledger.csv"

EXPECTED_HEADER = [
    "lane",
    "policy_id",
    "status",
    "effective_utc",
    "verified_at_utc",
    "applies_to",
    "risk_buckets_pct_json",
    "risk_bucket_scale",
    "max_risk_pct_per_trade",
    "max_open_risk_pct",
    "max_spread_risk_fraction",
    "market_recovery_mode",
    "reason",
    "evidence_ref",
    "status_packet_ref",
    "notes",
]


def _rows() -> list[dict[str, str]]:
    with LEDGER_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


class LivePolicyLedgerTests(unittest.TestCase):
    def test_header_is_exact(self) -> None:
        with LEDGER_PATH.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            self.assertEqual(next(reader), EXPECTED_HEADER)

    def test_bucket_json_and_numeric_risk_fields_are_parseable(self) -> None:
        numeric_fields = [
            "risk_bucket_scale",
            "max_risk_pct_per_trade",
            "max_open_risk_pct",
            "max_spread_risk_fraction",
        ]
        for row in _rows():
            buckets = json.loads(row["risk_buckets_pct_json"])
            self.assertEqual(set(buckets), {"H4", "H8", "H12", "D1", "W1"})
            for value in buckets.values():
                self.assertGreater(Decimal(str(value)), Decimal("0"))
            for field in numeric_fields:
                self.assertGreater(Decimal(row[field]), Decimal("0"), field)

    def test_ic_scale_one_policy_is_single_planned_or_active_row(self) -> None:
        matches = [
            row
            for row in _rows()
            if row["lane"] == "IC"
            and row["status"] in {"planned", "active"}
            and Decimal(row["risk_bucket_scale"]) == Decimal("1.0")
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["max_risk_pct_per_trade"], "0.75")
        self.assertEqual(matches[0]["max_open_risk_pct"], "6.0")

    def test_ftmo_policy_remains_scale_0p05(self) -> None:
        rows = [row for row in _rows() if row["lane"] == "FTMO" and row["status"] == "active"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["risk_bucket_scale"], "0.05")

    def test_ic_historical_scale_two_policy_remains_traceable(self) -> None:
        rows = [
            row
            for row in _rows()
            if row["lane"] == "IC"
            and row["status"] == "historical"
            and Decimal(row["risk_bucket_scale"]) == Decimal("2.0")
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["max_risk_pct_per_trade"], "1.5")
        self.assertEqual(rows[0]["max_open_risk_pct"], "12.0")


if __name__ == "__main__":
    unittest.main()
