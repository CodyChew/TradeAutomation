"""Collect bounded, shared-read LPFS journal snapshots for local reporting."""

from __future__ import annotations

import argparse

from lpfs_journal_snapshot import (
    DEFAULT_MAX_SOURCE_BYTES,
    DEFAULT_OUTPUT_ROOT,
    SnapshotError,
    collect_snapshots,
    parse_ssh_journal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--ssh-journal",
        action="append",
        default=[],
        help="Remote journal as LABEL=ssh-alias:C:\\path\\journal.jsonl. Repeat for multiple lanes.",
    )
    parser.add_argument(
        "--max-source-bytes",
        type=int,
        default=DEFAULT_MAX_SOURCE_BYTES,
        help=f"Maximum source suffix bytes per journal. Defaults to {DEFAULT_MAX_SOURCE_BYTES}.",
    )
    parser.add_argument(
        "--allow-full-scan",
        action="store_true",
        help="Explicitly approve an unbounded full remote journal scan.",
    )
    parser.add_argument(
        "--include-market-snapshots",
        action="store_true",
        help="Include high-volume market_snapshot rows for forensic collection.",
    )
    args = parser.parse_args()

    if not args.ssh_journal:
        parser.error("provide at least one --ssh-journal")
    if args.max_source_bytes <= 0:
        parser.error("--max-source-bytes must be positive")
    try:
        specs = [parse_ssh_journal(raw) for raw in args.ssh_journal]
        snapshot_dir = collect_snapshots(
            specs,
            output_root=DEFAULT_OUTPUT_ROOT,
            max_source_bytes=None if args.allow_full_scan else args.max_source_bytes,
            include_market_snapshots=args.include_market_snapshots,
        )
    except SnapshotError as exc:
        parser.error(str(exc))

    print(f"snapshot_dir={snapshot_dir}")
    print(f"manifest={snapshot_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
