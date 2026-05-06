"""Send an LPFS VPS startup/restart Telegram alert without touching MT5."""

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

from lp_force_strike_strategy_lab.ops_alerts import send_vps_startup_alert  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config JSON path.")
    parser.add_argument("--runtime-root", default="", help="Production runtime root for audit journaling.")
    parser.add_argument(
        "--runtime-journal-file-name",
        default="lpfs_live_journal.jsonl",
        help="Journal filename under <runtime-root>/data/live.",
    )
    parser.add_argument("--instance-label", default="LPFS LIVE", help="Telegram card prefix, e.g. LPFS FTMO LIVE.")
    parser.add_argument("--runner-task-name", default="LPFS_Live", help="Trading runner task this alert protects.")
    parser.add_argument("--max-attempts", type=int, default=20, help="Telegram delivery attempts while network comes up.")
    parser.add_argument("--retry-seconds", type=float, default=30.0, help="Delay between failed Telegram attempts.")
    parser.add_argument("--initial-delay-seconds", type=float, default=60.0, help="Startup delay before collecting/sending.")
    args = parser.parse_args()

    if args.initial_delay_seconds > 0:
        time.sleep(args.initial_delay_seconds)

    row = send_vps_startup_alert(
        config_path=args.config,
        runtime_root=args.runtime_root or None,
        runtime_journal_file_name=args.runtime_journal_file_name,
        instance_label=args.instance_label,
        runner_task_name=args.runner_task_name,
        max_attempts=args.max_attempts,
        retry_seconds=args.retry_seconds,
    )
    delivery = row.get("notification_delivery")
    if isinstance(delivery, dict) and delivery.get("sent"):
        print("startup_alert=sent")
        return 0
    if isinstance(delivery, dict) and delivery.get("status") == "dry_run":
        print("startup_alert=dry_run")
        return 0
    if row.get("notification_warning"):
        print(f"startup_alert=not_configured warning={row['notification_warning']}", file=sys.stderr)
        return 2
    print("startup_alert=failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
