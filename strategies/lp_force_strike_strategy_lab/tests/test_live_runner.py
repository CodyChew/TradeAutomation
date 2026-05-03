from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    WORKSPACE_ROOT,
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import NotificationDelivery  # noqa: E402
from scripts.run_lp_force_strike_live_executor import (  # noqa: E402
    LiveRunnerLock,
    RunnerLockActive,
    _default_heartbeat_path,
    _default_kill_switch_path,
    _kill_switch_active,
    _runtime_state_requires_migration,
    _send_kill_switch_event,
    _runner_lock_path,
    _send_runner_lifecycle_event,
    _sleep_with_kill_switch,
    _write_heartbeat,
)


class RecordingNotifier:
    def __init__(self) -> None:
        self.events = []

    def send_event(self, event, *, reply_to_message_id=None):
        self.events.append((event, reply_to_message_id))
        return NotificationDelivery(
            status="sent",
            attempted=True,
            sent=True,
            message="sent",
            message_id=len(self.events),
            reply_to_message_id=reply_to_message_id,
        )


class LiveRunnerNotificationTests(unittest.TestCase):
    def test_runner_lock_blocks_second_holder_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = _runner_lock_path(Path(tmpdir) / "state.json")
            first = LiveRunnerLock(lock_path)
            first.acquire()
            try:
                second = LiveRunnerLock(lock_path)
                with self.assertRaises(RunnerLockActive):
                    second.acquire()
            finally:
                first.release()

            second = LiveRunnerLock(lock_path)
            second.acquire()
            second.release()

    def test_runner_start_notification_is_journaled_and_sent(self) -> None:
        notifier = RecordingNotifier()
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"

            _send_runner_lifecycle_event(
                journal_path,
                notifier,
                kind="runner_started",
                status="running",
                occurred_at_utc=datetime(2026, 5, 1, 7, 0, tzinfo=timezone.utc),
                requested_cycles=100000000,
                sleep_seconds=30,
                state_path="data/live/lpfs_live_state.json",
                journal_path="data/live/lpfs_live_journal.jsonl",
            )

            rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(notifier.events), 1)
        self.assertEqual(notifier.events[0][0].kind, "runner_started")
        self.assertEqual(rows[0]["event"], "runner_started")
        self.assertIn("LPFS LIVE | RUNNER STARTED", rows[0]["notification"])
        self.assertEqual(rows[0]["notification_delivery"]["message_id"], 1)
        self.assertEqual(rows[0]["notification_event"]["fields"]["sleep_seconds"], 30)

    def test_runner_error_stop_notification_is_journaled_and_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"

            _send_runner_lifecycle_event(
                journal_path,
                None,
                kind="runner_stopped",
                status="error",
                occurred_at_utc=datetime(2026, 5, 1, 17, 0, tzinfo=timezone.utc),
                requested_cycles=100000000,
                completed_cycles=12,
                runtime_seconds=360,
                state_saved=False,
                message="RuntimeError: MT5 disconnected",
            )

            rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["event"], "runner_stopped")
        self.assertIn("LPFS LIVE | RUNNER STOPPED", rows[0]["notification"])
        self.assertIn("Reason: Stopped after error", rows[0]["notification"])
        self.assertIn("State saved: no", rows[0]["notification"])
        self.assertIn("RuntimeError: MT5 disconnected", rows[0]["notification"])
        self.assertIsNone(rows[0]["notification_delivery"])

    def test_default_control_paths_are_state_adjacent(self) -> None:
        state_path = Path("C:/TradeAutomationRuntime/data/live/lpfs_live_state.json")

        self.assertEqual(_default_kill_switch_path(state_path), state_path.parent / "KILL_SWITCH")
        self.assertEqual(_default_heartbeat_path(state_path), state_path.parent / "lpfs_live_heartbeat.json")

    def test_heartbeat_writes_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            heartbeat_path = Path(tmpdir) / "live" / "lpfs_live_heartbeat.json"

            _write_heartbeat(
                heartbeat_path,
                status="running",
                requested_cycles=12,
                completed_cycles=3,
                last_cycle={"frames_processed": 140, "orders_sent": 1},
            )
            payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["requested_cycles"], 12)
        self.assertEqual(payload["completed_cycles"], 3)
        self.assertEqual(payload["last_cycle"]["frames_processed"], 140)
        self.assertIn("updated_at_utc", payload)
        self.assertIn("pid", payload)

    def test_kill_switch_active_and_sleep_short_circuit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kill_switch_path = Path(tmpdir) / "KILL_SWITCH"
            self.assertFalse(_kill_switch_active(kill_switch_path))

            kill_switch_path.write_text("maintenance stop\n", encoding="utf-8")

            self.assertTrue(_kill_switch_active(kill_switch_path))
            self.assertTrue(_sleep_with_kill_switch(10.0, kill_switch_path, check_interval_seconds=0.01))

    def test_runtime_root_requires_explicit_state_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_state = Path(tmpdir) / "repo" / "data" / "live" / "lpfs_live_state.json"
            runtime_state = Path(tmpdir) / "runtime" / "data" / "live" / "lpfs_live_state.json"
            original_state.parent.mkdir(parents=True)
            original_state.write_text("{}", encoding="utf-8")

            self.assertTrue(_runtime_state_requires_migration(original_state, runtime_state))

            runtime_state.parent.mkdir(parents=True)
            runtime_state.write_text("{}", encoding="utf-8")

            self.assertFalse(_runtime_state_requires_migration(original_state, runtime_state))
            self.assertFalse(_runtime_state_requires_migration(original_state, original_state))

    def test_kill_switch_event_is_journaled_and_sent(self) -> None:
        notifier = RecordingNotifier()
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            kill_switch_path = Path(tmpdir) / "KILL_SWITCH"
            kill_switch_path.write_text("operator stop\n", encoding="utf-8")

            _send_kill_switch_event(
                journal_path,
                notifier,
                kill_switch_path=kill_switch_path,
                stage="before_live_cycle",
            )
            rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(notifier.events), 1)
        self.assertEqual(notifier.events[0][0].kind, "kill_switch_activated")
        self.assertEqual(rows[0]["event"], "kill_switch_activated")
        self.assertIn("LPFS LIVE | KILL SWITCH", rows[0]["notification"])
        self.assertIn("Action: No new live cycles will run", rows[0]["notification"])

    def test_runner_kill_switch_stop_notification_is_journaled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"

            _send_runner_lifecycle_event(
                journal_path,
                None,
                kind="runner_stopped",
                status="kill_switch",
                occurred_at_utc=datetime(2026, 5, 3, 17, 0, tzinfo=timezone.utc),
                requested_cycles=100000000,
                completed_cycles=2,
                runtime_seconds=60,
                state_saved=True,
                message="Kill switch active at data/live/KILL_SWITCH",
            )
            rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]

        self.assertIn("Reason: Kill switch active", rows[0]["notification"])
        self.assertIn("State saved: yes", rows[0]["notification"])


if __name__ == "__main__":
    unittest.main()
