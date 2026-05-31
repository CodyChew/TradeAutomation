"""Print or post a compact LPFS recent live-trade summary."""

from __future__ import annotations

import argparse
import sys
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

from lp_force_strike_strategy_lab import load_live_send_settings, telegram_notifier_from_settings  # noqa: E402
from lp_force_strike_strategy_lab.live_trade_summary import (  # noqa: E402
    build_recent_trade_summary_message,
    load_live_journal_events,
)
from lpfs_journal_snapshot import (  # noqa: E402
    SnapshotError,
    require_snapshot_period_coverage,
    validate_manifest_backed_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--config", default="config.local.json", help="Ignored local config JSON path.")
    parser.add_argument(
        "--journal-snapshot",
        required=True,
        help="Collector-produced local journal snapshot with a matching sibling manifest.json.",
    )
    period = parser.add_mutually_exclusive_group()
    period.add_argument("--days", type=int, default=None, help="Summarize trades closed in the last N days.")
    period.add_argument("--weeks", type=int, default=None, help="Summarize trades closed in the last N weeks.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Fallback latest-trade count when --days/--weeks is omitted; also caps --include-trades details.",
    )
    parser.add_argument("--include-trades", action="store_true", help="Append the old per-trade detail list.")
    parser.add_argument("--post-telegram", action="store_true", help="Post the summary to the configured Telegram chat.")
    args = parser.parse_args()
    if args.days is not None and args.days <= 0:
        parser.error("--days must be positive")
    if args.weeks is not None and args.weeks <= 0:
        parser.error("--weeks must be positive")

    try:
        journal_path, _, manifest_entry = validate_manifest_backed_snapshot(args.journal_snapshot)
        require_snapshot_period_coverage(manifest_entry, days=args.days, weeks=args.weeks)
        events = load_live_journal_events(journal_path)
    except (FileNotFoundError, SnapshotError) as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Hint: collect a bounded local snapshot with scripts\\collect_lpfs_live_journal_snapshots.py, "
            "then pass its JSONL file with --journal-snapshot.",
            file=sys.stderr,
        )
        return 2
    message = build_recent_trade_summary_message(
        events=events,
        limit=args.limit,
        days=args.days,
        weeks=args.weeks,
        include_trades=args.include_trades,
    )
    print(message)

    if not args.post_telegram:
        return 0

    settings = load_live_send_settings(args.config)
    notifier, warning = telegram_notifier_from_settings(settings)  # type: ignore[arg-type]
    if notifier is None:
        print(f"Telegram not configured: {warning or 'disabled'}", file=sys.stderr)
        return 2
    delivery = notifier.send_message(message)
    if not delivery.sent:
        print(f"Telegram summary delivery failed: {delivery.error or delivery.status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
