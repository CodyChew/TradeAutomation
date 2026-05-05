"""Run one or more LP + Force Strike MT5 live-send cycles."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


KILL_SWITCH_EXIT_CODE = 3
RUNTIME_STATE_MIGRATION_EXIT_CODE = 4
DEFAULT_RUNTIME_LIVE_DIR = Path("data/live")
DEFAULT_STATE_NAME = "lpfs_live_state.json"
DEFAULT_JOURNAL_NAME = "lpfs_live_journal.jsonl"
DEFAULT_HEARTBEAT_NAME = "lpfs_live_heartbeat.json"


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


def _default_kill_switch_path(state_path: str | Path) -> Path:
    return Path(state_path).parent / "KILL_SWITCH"


def _default_heartbeat_path(state_path: str | Path) -> Path:
    return Path(state_path).parent / DEFAULT_HEARTBEAT_NAME


def _settings_with_runtime_root(
    settings,
    runtime_root: str | Path | None,
    *,
    state_file_name: str = DEFAULT_STATE_NAME,
    journal_file_name: str = DEFAULT_JOURNAL_NAME,
):
    if runtime_root in (None, ""):
        return settings
    live_dir = Path(runtime_root) / DEFAULT_RUNTIME_LIVE_DIR
    state_name = str(state_file_name or DEFAULT_STATE_NAME)
    journal_name = str(journal_file_name or DEFAULT_JOURNAL_NAME)
    return replace(
        settings,
        executor=replace(
            settings.executor,
            journal_path=str(live_dir / journal_name),
            state_path=str(live_dir / state_name),
        ),
    )


def _runtime_state_requires_migration(original_state_path: str | Path, runtime_state_path: str | Path) -> bool:
    original = Path(original_state_path)
    runtime = Path(runtime_state_path)
    if _same_path(original, runtime):
        return False
    return original.exists() and not runtime.exists()


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def _kill_switch_active(path: str | Path) -> bool:
    return Path(path).exists()


def _kill_switch_detail(path: str | Path) -> str:
    kill_path = Path(path)
    try:
        text = kill_path.read_text(encoding="utf-8").strip()
    except OSError:
        return f"Kill switch active at {kill_path}"
    first_line = text.splitlines()[0].strip() if text else ""
    if first_line:
        return f"Kill switch active at {kill_path}: {first_line}"
    return f"Kill switch active at {kill_path}"


def _write_heartbeat(path: str | Path, **payload: Any) -> None:
    heartbeat_path = Path(path)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        **payload,
    }
    text = json.dumps(body, indent=2, sort_keys=True, default=str) + "\n"
    temp_path = heartbeat_path.with_name(f".{heartbeat_path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, heartbeat_path)
    except OSError:
        heartbeat_path.write_text(text, encoding="utf-8")
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _sleep_with_kill_switch(seconds: float, kill_switch_path: str | Path, *, check_interval_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(seconds))
    while True:
        if _kill_switch_active(kill_switch_path):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(0.1, float(check_interval_seconds)), remaining))


def _mt5_account_fields(mt5_module: Any) -> dict[str, Any]:
    account = mt5_module.account_info()
    if account is None:
        return {}
    return {
        "account_login": getattr(account, "login", None),
        "account_server": getattr(account, "server", None),
        "account_currency": getattr(account, "currency", None),
    }


def _send_kill_switch_event(
    audit_journal_path: str | Path,
    notifier,
    *,
    kill_switch_path: str | Path,
    stage: str,
) -> None:
    detail = _kill_switch_detail(kill_switch_path)
    event = NotificationEvent(
        kind="kill_switch_activated",
        mode="LIVE",
        title="Kill switch active",
        severity="warning",
        status="kill_switch",
        occurred_at_utc=datetime.now(timezone.utc).isoformat(),
        fields={"kill_switch_path": str(kill_switch_path), "stage": stage},
        message=detail,
    )
    delivery = deliver_notification_best_effort(notifier, event)
    append_audit_event(
        audit_journal_path,
        "kill_switch_activated",
        kill_switch_path=str(kill_switch_path),
        stage=stage,
        message=detail,
        notification=format_notification_message(event),
        notification_event=event.to_dict(),
        notification_delivery=None if delivery is None else delivery.to_dict(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config JSON path.")
    parser.add_argument("--cycles", type=int, default=1, help="Finite live-send cycles to execute.")
    parser.add_argument("--sleep-seconds", type=float, default=30.0, help="Delay between cycles when cycles > 1.")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Optional production runtime root. Overrides live state/journal to <root>/data/live.",
    )
    parser.add_argument(
        "--runtime-state-file-name",
        default=DEFAULT_STATE_NAME,
        help=f"State filename to use inside --runtime-root data/live. Defaults to {DEFAULT_STATE_NAME}.",
    )
    parser.add_argument(
        "--runtime-journal-file-name",
        default=DEFAULT_JOURNAL_NAME,
        help=f"Journal filename to use inside --runtime-root data/live. Defaults to {DEFAULT_JOURNAL_NAME}.",
    )
    parser.add_argument(
        "--kill-switch-path",
        default="",
        help="Optional kill switch path. Defaults to KILL_SWITCH beside the live state file.",
    )
    parser.add_argument(
        "--heartbeat-path",
        default="",
        help=f"Optional heartbeat JSON path. Defaults to {DEFAULT_HEARTBEAT_NAME} beside the live state file.",
    )
    parser.add_argument(
        "--allow-empty-runtime-state",
        action="store_true",
        help="Allow --runtime-root to start with an empty live state even when the config state file exists.",
    )
    args = parser.parse_args()

    original_settings = load_live_send_settings(args.config)
    settings = _settings_with_runtime_root(
        original_settings,
        args.runtime_root,
        state_file_name=args.runtime_state_file_name,
        journal_file_name=args.runtime_journal_file_name,
    )
    validate_live_send_settings(settings)
    if (
        str(args.runtime_root).strip()
        and not args.allow_empty_runtime_state
        and _runtime_state_requires_migration(original_settings.executor.state_path, settings.executor.state_path)
    ):
        message = (
            "Refusing to start with an empty runtime-root live state while the configured live state exists. "
            f"Copy {original_settings.executor.state_path} to {settings.executor.state_path}, "
            "or rerun with --allow-empty-runtime-state only if you intentionally want a clean production state."
        )
        print(message, file=sys.stderr)
        append_audit_event(
            settings.executor.journal_path,
            "runtime_state_migration_required",
            original_state_path=original_settings.executor.state_path,
            runtime_state_path=settings.executor.state_path,
            message=message,
        )
        return RUNTIME_STATE_MIGRATION_EXIT_CODE
    kill_switch_path = (
        Path(args.kill_switch_path)
        if str(args.kill_switch_path).strip()
        else _default_kill_switch_path(settings.executor.state_path)
    )
    heartbeat_path = (
        Path(args.heartbeat_path)
        if str(args.heartbeat_path).strip()
        else _default_heartbeat_path(settings.executor.state_path)
    )
    notifier, telegram_warning = telegram_notifier_from_settings(DryRunSettings(local=settings.local, executor=settings.executor))
    if telegram_warning:
        append_audit_event(settings.executor.journal_path, telegram_warning)

    requested_cycles = max(1, int(args.cycles))
    sleep_seconds = float(args.sleep_seconds)
    if _kill_switch_active(kill_switch_path):
        _send_kill_switch_event(
            settings.executor.journal_path,
            notifier,
            kill_switch_path=kill_switch_path,
            stage="before_mt5_initialization",
        )
        _write_heartbeat(
            heartbeat_path,
            status="kill_switch",
            requested_cycles=requested_cycles,
            completed_cycles=0,
            config_path=args.config,
            state_path=settings.executor.state_path,
            journal_path=settings.executor.journal_path,
            kill_switch_path=str(kill_switch_path),
            detail=_kill_switch_detail(kill_switch_path),
        )
        return KILL_SWITCH_EXIT_CODE

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
        _write_heartbeat(
            heartbeat_path,
            status="starting",
            requested_cycles=requested_cycles,
            completed_cycles=0,
            config_path=args.config,
            state_path=settings.executor.state_path,
            journal_path=settings.executor.journal_path,
            kill_switch_path=str(kill_switch_path),
        )
        import MetaTrader5 as mt5

        initialize_mt5_session(mt5, settings.local)
        account_fields = _mt5_account_fields(mt5)

        state = load_live_state(settings.executor.state_path)
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
        _write_heartbeat(
            heartbeat_path,
            status="running",
            requested_cycles=requested_cycles,
            completed_cycles=completed_cycles,
            started_at_utc=started_at.isoformat(),
            sleep_seconds=sleep_seconds,
            config_path=args.config,
            state_path=settings.executor.state_path,
            journal_path=settings.executor.journal_path,
            kill_switch_path=str(kill_switch_path),
            **account_fields,
        )
        try:
            for cycle_index in range(requested_cycles):
                if _kill_switch_active(kill_switch_path):
                    stop_status = "kill_switch"
                    stop_detail = _kill_switch_detail(kill_switch_path)
                    return_code = KILL_SWITCH_EXIT_CODE
                    _send_kill_switch_event(
                        settings.executor.journal_path,
                        notifier,
                        kill_switch_path=kill_switch_path,
                        stage="before_live_cycle",
                    )
                    break
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
                _write_heartbeat(
                    heartbeat_path,
                    status="running",
                    requested_cycles=requested_cycles,
                    completed_cycles=completed_cycles,
                    started_at_utc=started_at.isoformat(),
                    last_cycle={
                        "cycle_index": cycle_index,
                        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "frames_processed": result.frames_processed,
                        "orders_sent": result.orders_sent,
                        "setups_rejected": result.setups_rejected,
                        "setups_blocked": result.setups_blocked,
                    },
                    sleep_seconds=sleep_seconds,
                    config_path=args.config,
                    state_path=settings.executor.state_path,
                    journal_path=settings.executor.journal_path,
                    kill_switch_path=str(kill_switch_path),
                    **account_fields,
                )
                if cycle_index + 1 < requested_cycles:
                    if _sleep_with_kill_switch(sleep_seconds, kill_switch_path):
                        stop_status = "kill_switch"
                        stop_detail = _kill_switch_detail(kill_switch_path)
                        return_code = KILL_SWITCH_EXIT_CODE
                        _send_kill_switch_event(
                            settings.executor.journal_path,
                            notifier,
                            kill_switch_path=kill_switch_path,
                            stage="between_live_cycles",
                        )
                        break
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
                _write_heartbeat(
                    heartbeat_path,
                    status=stop_status,
                    requested_cycles=requested_cycles,
                    completed_cycles=completed_cycles,
                    started_at_utc=started_at.isoformat(),
                    stopped_at_utc=stopped_at.isoformat(),
                    runtime_seconds=runtime_seconds,
                    state_saved=state_saved,
                    config_path=args.config,
                    state_path=settings.executor.state_path,
                    journal_path=settings.executor.journal_path,
                    kill_switch_path=str(kill_switch_path),
                    detail=stop_detail,
                    **account_fields,
                )
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
