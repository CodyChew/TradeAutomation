"""Run one or more LP + Force Strike MT5 live-send cycles."""

from __future__ import annotations

import argparse
import sys
import time
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
    initialize_mt5_session,
    load_live_send_settings,
    load_live_state,
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
    try:
        for cycle_index in range(max(1, int(args.cycles))):
            result = run_live_send_cycle(mt5, config=settings.executor, state=state, notifier=notifier)
            state = result.state
            append_audit_event(
                settings.executor.journal_path,
                "live_send_cycle_complete",
                cycle_index=cycle_index,
                frames_processed=result.frames_processed,
                orders_sent=result.orders_sent,
                setups_rejected=result.setups_rejected,
                setups_blocked=result.setups_blocked,
            )
            if cycle_index + 1 < int(args.cycles):
                time.sleep(float(args.sleep_seconds))
    finally:
        save_live_state(settings.executor.state_path, state)
        mt5.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
