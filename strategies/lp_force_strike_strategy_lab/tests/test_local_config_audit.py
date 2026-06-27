from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPT_PATH = WORKSPACE_ROOT / "scripts" / "audit_lpfs_local_configs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_lpfs_local_configs", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalConfigAuditTests(unittest.TestCase):
    def test_redacted_audit_reports_shape_without_secret_values(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {
                            "expected_login": "12345678",
                            "expected_server": "Broker-Secret-Server",
                            "login": "87654321",
                            "password": "super-secret-password",
                        },
                        "telegram": {
                            "enabled": True,
                            "bot_token": "123456:telegram-secret-token",
                            "chat_id": "-987654321",
                        },
                        "live_send": {
                            "execution_mode": "LIVE_SEND",
                            "live_send_enabled": True,
                            "real_money_ack": "I_UNDERSTAND_THIS_SENDS_REAL_ORDERS",
                            "symbols": ["EURUSD", "GBPUSD"],
                            "timeframes": ["H4"],
                            "market_recovery_mode": "disabled",
                            "strategy_magic": 131500,
                            "order_comment_prefix": "LPFS",
                            "risk_bucket_scale": 1.0,
                            "max_risk_pct_per_trade": 0.75,
                            "max_open_risk_pct": 6.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            row = module.audit_config(config_path)
            text = module.render_text([row])
            json_text = json.dumps(row, sort_keys=True)

        self.assertEqual(row["status"], "review")
        self.assertIn("live_send_enabled_true_review_required", row["findings"])
        self.assertTrue(row["expected_login_set"])
        self.assertTrue(row["expected_server_set"])
        self.assertTrue(row["telegram_token_set"])
        self.assertEqual(row["symbols_count"], 2)
        self.assertEqual(row["timeframes_count"], 1)
        self.assertEqual(row["settings_load_status"], "ok")
        self.assertEqual(row["effective_risk_buckets_pct"]["W1"], 0.75)
        for secret in (
            "12345678",
            "Broker-Secret-Server",
            "87654321",
            "super-secret-password",
            "telegram-secret-token",
            "-987654321",
        ):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, json_text)

    def test_audit_flags_invalid_recovery_mode_and_missing_identity(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {},
                        "live_send": {
                            "execution_mode": "LIVE_SEND",
                            "live_send_enabled": True,
                            "real_money_ack": "",
                            "market_recovery_mode": "better_than_entry_only",
                        },
                    }
                ),
                encoding="utf-8",
            )

            row = module.audit_config(config_path)
            missing = module.audit_config(Path(tmpdir) / "missing.local.json")

        self.assertEqual(row["status"], "review")
        self.assertIn("market_recovery_not_disabled", row["findings"])
        self.assertIn("live_send_enabled_without_ack", row["findings"])
        self.assertIn("missing_expected_login", row["findings"])
        self.assertIn("missing_expected_server", row["findings"])
        self.assertEqual(missing["status"], "missing")


if __name__ == "__main__":
    unittest.main()
