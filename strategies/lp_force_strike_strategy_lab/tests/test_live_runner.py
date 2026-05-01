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
    _runner_lock_path,
    _send_runner_lifecycle_event,
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


if __name__ == "__main__":
    unittest.main()
