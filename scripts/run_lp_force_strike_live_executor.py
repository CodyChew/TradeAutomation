"""Run one or more LP + Force Strike MT5 live-send cycles."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config JSON path.")
    parser.add_argument("--cycles", type=int, default=1, help="Finite live-send cycles to execute.")
    parser.add_argument("--sleep-seconds", type=float, default=30.0, help="Delay between cycles when cycles > 1.")
    args = parser.parse_args()

    settings = load_live_send_settings(args.config)
    validate_live_send_settings(settings)

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
