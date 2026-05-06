from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab.dry_run_executor import DryRunLocalConfig  # noqa: E402
from lp_force_strike_strategy_lab.live_executor import LiveSendExecutorConfig, LiveSendSettings  # noqa: E402
from lp_force_strike_strategy_lab.notifications import NotificationDelivery  # noqa: E402
from lp_force_strike_strategy_lab.ops_alerts import (  # noqa: E402
    VpsStartupSnapshot,
    _message_summary,
    _restart_reason_from_message,
    _windows_last_restart_event,
    build_vps_startup_message,
    send_vps_startup_alert,
)
import lp_force_strike_strategy_lab.ops_alerts as ops_alerts_module  # noqa: E402


class RecordingNotifier:
    def __init__(self, deliveries: list[NotificationDelivery]) -> None:
        self.deliveries = list(deliveries)
        self.messages: list[str] = []

    def send_message(self, message: str):
        self.messages.append(message)
        return self.deliveries.pop(0)


class OpsAlertTests(unittest.TestCase):
    def test_startup_message_uses_boot_and_restart_evidence(self) -> None:
        snapshot = VpsStartupSnapshot(
            detected_at_utc="2026-05-06T06:00:00+00:00",
            hostname="EC2AMAZ-ON6FOF2",
            user="SYSTEM",
            boot_time_utc="2026-05-06T03:44:23+00:00",
            restart_event_time_utc="2026-05-06T03:43:01+00:00",
            restart_event_id=1074,
            restart_reason="Reason Code: 0x80020010 | Operating System: Service pack (Planned)",
        )

        message = build_vps_startup_message(
            instance_label="LPFS FTMO LIVE",
            runner_task_name="LPFS_Live",
            runtime_root="C:/TradeAutomationRuntime",
            journal_path="C:/TradeAutomationRuntime/data/live/lpfs_live_journal.jsonl",
            snapshot=snapshot,
        )

        self.assertIn("LPFS FTMO LIVE | VPS STARTED", message)
        self.assertIn("Host: EC2AMAZ-ON6FOF2 | User: SYSTEM", message)
        self.assertIn("Boot: 2026-05-06 11:44 SGT", message)
        self.assertIn("Last restart event: 2026-05-06 11:43 SGT | Event 1074", message)
        self.assertIn("Operating System: Service pack (Planned)", message)
        self.assertIn("Runner task: LPFS_Live", message)
        self.assertIn("Action: confirm MT5 terminal and runner heartbeat after RDP/logon.", message)

    def test_restart_reason_extracts_useful_windows_update_lines(self) -> None:
        message = "\n".join(
            [
                "The process C:\\Windows\\system32\\svchost.exe has initiated the restart.",
                "Reason Code: 0x80020010",
                "Shutdown Type: restart",
                "Comment: Operating System: Service pack (Planned)",
            ]
        )

        self.assertEqual(
            _restart_reason_from_message(message),
            "Reason Code: 0x80020010 | Shutdown Type: restart | Comment: Operating System: Service pack (Planned)",
        )
        self.assertEqual(
            _message_summary(message),
            "The process C:\\Windows\\system32\\svchost.exe has initiated the restart. | Reason Code: 0x80020010",
        )

    def test_windows_restart_event_query_prefers_planned_restart_reason(self) -> None:
        captured = {}

        def fake_run_powershell_json(script: str):
            captured["script"] = script
            return {"id": 1074, "message": "Reason Code: 0x80020010"}

        with mock.patch.object(ops_alerts_module, "_run_powershell_json", side_effect=fake_run_powershell_json):
            event = _windows_last_restart_event()

        self.assertEqual(event["id"], 1074)
        self.assertIn("Where-Object { $_.Id -eq 1074 }", captured["script"])
        self.assertIn("6008,41", captured["script"])

    def test_startup_alert_retries_delivery_and_journals_sanitized_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            settings = LiveSendSettings(
                local=DryRunLocalConfig(telegram_enabled=True, telegram_bot_token="secret-token", telegram_chat_id="chat", telegram_dry_run=False),
                executor=LiveSendExecutorConfig(journal_path=str(Path(tmpdir) / "repo_journal.jsonl")),
            )
            notifier = RecordingNotifier(
                [
                    NotificationDelivery(status="failed", attempted=True, sent=False, message="failed", error="offline"),
                    NotificationDelivery(status="sent", attempted=True, sent=True, message="sent", message_id=22),
                ]
            )
            snapshot = VpsStartupSnapshot(
                detected_at_utc="2026-05-06T06:00:00+00:00",
                hostname="EC2AMAZ-DT73P0T",
                user="SYSTEM",
            )

            with mock.patch.object(ops_alerts_module, "load_live_send_settings", return_value=settings), mock.patch.object(
                ops_alerts_module,
                "telegram_notifier_from_settings",
                return_value=(notifier, None),
            ):
                row = send_vps_startup_alert(
                    config_path="config.local.json",
                    runtime_root=runtime_root,
                    runtime_journal_file_name="lpfs_ic_live_journal.jsonl",
                    instance_label="LPFS IC LIVE",
                    runner_task_name="LPFS_IC_Live",
                    max_attempts=2,
                    retry_seconds=0,
                    snapshot_provider=lambda: snapshot,
                    sleep=lambda seconds: None,
                )

            journal_path = runtime_root / "data" / "live" / "lpfs_ic_live_journal.jsonl"
            persisted = json.loads(journal_path.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(len(notifier.messages), 2)
        self.assertEqual(row["event"], "vps_startup_alert")
        self.assertEqual(row["delivery_attempts"], 2)
        self.assertEqual(row["notification_delivery"]["message_id"], 22)
        self.assertEqual(persisted["notification_delivery"]["message_id"], 22)
        self.assertIn("LPFS IC LIVE | VPS STARTED", persisted["notification"])
        self.assertNotIn("secret-token", json.dumps(persisted))

    def test_startup_alert_journals_disabled_telegram_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = LiveSendSettings(
                local=DryRunLocalConfig(telegram_enabled=False),
                executor=LiveSendExecutorConfig(journal_path=str(Path(tmpdir) / "journal.jsonl")),
            )
            snapshot = VpsStartupSnapshot(
                detected_at_utc="2026-05-06T06:00:00+00:00",
                hostname="host",
                user="SYSTEM",
            )

            with mock.patch.object(ops_alerts_module, "load_live_send_settings", return_value=settings), mock.patch.object(
                ops_alerts_module,
                "telegram_notifier_from_settings",
                return_value=(None, "telegram_disabled"),
            ):
                row = send_vps_startup_alert(
                    config_path="config.local.json",
                    snapshot_provider=lambda: snapshot,
                )

        self.assertEqual(row["event"], "vps_startup_alert")
        self.assertEqual(row["delivery_attempts"], 0)
        self.assertEqual(row["notification_warning"], "telegram_disabled")
        self.assertIsNone(row["notification_delivery"])


if __name__ == "__main__":
    unittest.main()
