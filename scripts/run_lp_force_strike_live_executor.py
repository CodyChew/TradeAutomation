"""Run one or more LP + Force Strike MT5 live-send cycles."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    ROOT / "concepts" / "lp_levels_lab" / "src",
    ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    ROOT / "shared" / "backtest_engine_lab" / "src",
    ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import (  # noqa: E402
    append_audit_event,
    deliver_notification_best_effort,
    format_notification_message,
    initialize_mt5_session,
    load_live_send_settings,
    load_live_state,
    NotificationEvent,
    run_live_send_cycle,
    save_live_state,
    telegram_notifier_from_settings,
    validate_live_send_settings,
)
from lp_force_strike_strategy_lab.dry_run_executor import DryRunSettings  # noqa: E402


class RunnerLockActive(RuntimeError):
    """Raised when another live runner already holds the state lock."""


class LiveRunnerLock:
    """Non-blocking process lock released automatically by the OS on crash."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None
        self._fallback_fd: int | None = None
        self._fallback_created = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._acquire_file_lock()
        except ImportError:
            self._acquire_exclusive_file()

    def release(self) -> None:
        if self._handle is not None:
            try:
                self._unlock_file_handle()
            finally:
                self._handle.close()
                self._handle = None
        if self._fallback_fd is not None:
            os.close(self._fallback_fd)
            self._fallback_fd = None
        if self._fallback_created:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._fallback_created = False

    def _acquire_file_lock(self) -> None:
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            self._lock_file_handle()
        except ImportError:
            self._handle.close()
            self._handle = None
            raise
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise RunnerLockActive(f"LPFS live runner already active; lock is held at {self.path}") from exc
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(f"pid={os.getpid()} started_utc={datetime.now(timezone.utc).isoformat()}\n")
        self._handle.flush()

    def _lock_file_handle(self) -> None:
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            self._handle.write(" ")
            self._handle.flush()
            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_file_handle(self) -> None:
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)

    def _acquire_exclusive_file(self) -> None:
        try:
            self._fallback_fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError as exc:
            raise RunnerLockActive(f"LPFS live runner already active; lock file exists at {self.path}") from exc
        self._fallback_created = True
        os.write(self._fallback_fd, f"pid={os.getpid()} started_utc={datetime.now(timezone.utc).isoformat()}\n".encode("utf-8"))


def _runner_lock_path(state_path: str | Path) -> Path:
    path = Path(state_path)
    return path.with_name(f"{path.name}.lock")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config JSON path.")
    parser.add_argument("--cycles", type=int, default=1, help="Finite live-send cycles to execute.")
    parser.add_argument("--sleep-seconds", type=float, default=30.0, help="Delay between cycles when cycles > 1.")
    args = parser.parse_args()

    settings = load_live_send_settings(args.config)
    validate_live_send_settings(settings)
    runner_lock = LiveRunnerLock(_runner_lock_path(settings.executor.state_path))
    try:
        runner_lock.acquire()
    except RunnerLockActive as exc:
        message = str(exc)
        print(message, file=sys.stderr)
        append_audit_event(
            settings.executor.journal_path,
            "runner_lock_active",
            lock_path=str(runner_lock.path),
            message=message,
        )
        return 2

    try:
        import MetaTrader5 as mt5

        initialize_mt5_session(mt5, settings.local)
        notifier, telegram_warning = telegram_notifier_from_settings(DryRunSettings(local=settings.local, executor=settings.executor))
        if telegram_warning:
            append_audit_event(settings.executor.journal_path, telegram_warning)

        state = load_live_state(settings.executor.state_path)
        requested_cycles = max(1, int(args.cycles))
        sleep_seconds = float(args.sleep_seconds)
        started_at = datetime.now(timezone.utc)
        completed_cycles = 0
        return_code = 0
        stop_status = "completed"
        stop_detail = ""
        _send_runner_lifecycle_event(
            settings.executor.journal_path,
            notifier,
            kind="runner_started",
            status="running",
            occurred_at_utc=started_at,
            requested_cycles=requested_cycles,
            sleep_seconds=sleep_seconds,
            state_path=settings.executor.state_path,
            journal_path=settings.executor.journal_path,
        )
        try:
            for cycle_index in range(requested_cycles):
                result = run_live_send_cycle(mt5, config=settings.executor, state=state, notifier=notifier)
                state = result.state
                completed_cycles = cycle_index + 1
                append_audit_event(
                    settings.executor.journal_path,
                    "live_send_cycle_complete",
                    cycle_index=cycle_index,
                    frames_processed=result.frames_processed,
                    orders_sent=result.orders_sent,
                    setups_rejected=result.setups_rejected,
                    setups_blocked=result.setups_blocked,
                )
                if cycle_index + 1 < requested_cycles:
                    time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            stop_status = "stopped_by_user"
            return_code = 130
        except Exception as exc:
            stop_status = "error"
            stop_detail = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            state_saved = False
            try:
                save_live_state(settings.executor.state_path, state)
                state_saved = True
            except Exception as exc:
                if stop_status != "error":
                    stop_status = "error"
                    stop_detail = f"State save failed: {type(exc).__name__}: {exc}"
                raise
            finally:
                stopped_at = datetime.now(timezone.utc)
                runtime_seconds = max(0.0, (stopped_at - started_at).total_seconds())
                _send_runner_lifecycle_event(
                    settings.executor.journal_path,
                    notifier,
                    kind="runner_stopped",
                    status=stop_status,
                    occurred_at_utc=stopped_at,
                    requested_cycles=requested_cycles,
                    completed_cycles=completed_cycles,
                    runtime_seconds=runtime_seconds,
                    state_saved=state_saved,
                    message=stop_detail,
                )
                mt5.shutdown()

        return return_code
    finally:
        runner_lock.release()


def _send_runner_lifecycle_event(
    audit_journal_path: str | Path,
    notifier,
    *,
    kind: str,
    status: str,
    occurred_at_utc: datetime,
    message: str = "",
    **fields,
) -> None:
    event = NotificationEvent(
        kind=kind,  # type: ignore[arg-type]
        mode="LIVE",
        title=str(kind).replace("_", " ").title(),
        severity="error" if status == "error" else "info",
        status=status,
        occurred_at_utc=occurred_at_utc.isoformat(),
        fields=fields,
        message=message,
    )
    delivery = deliver_notification_best_effort(notifier, event)
    append_audit_event(
        audit_journal_path,
        kind,
        notification=format_notification_message(event),
        notification_event=event.to_dict(),
        notification_delivery=None if delivery is None else delivery.to_dict(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
