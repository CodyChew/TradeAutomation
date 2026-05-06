"""Build a read-only LPFS live gate-attribution report from JSONL journals."""

from __future__ import annotations

import argparse
import base64
from collections import deque
import subprocess
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

from lp_force_strike_strategy_lab.live_gate_attribution import (  # noqa: E402
    build_gate_attribution_report,
    load_jsonl_events,
    parse_jsonl_lines,
    render_gate_attribution_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal",
        action="append",
        default=[],
        help="Local journal path, or LABEL=path. Repeat for multiple sources.",
    )
    parser.add_argument(
        "--ssh-journal",
        action="append",
        default=[],
        help="Remote journal as LABEL=ssh-alias:C:\\path\\journal.jsonl. Repeat for multiple sources.",
    )
    parser.add_argument(
        "--weekly-open-window-hours",
        type=int,
        default=12,
        help="Hours after Sunday 21:00 UTC counted as weekly-open conditions.",
    )
    parser.add_argument("--detail-limit", type=int, default=20, help="Max notable signal rows per source; 0 means all.")
    parser.add_argument("--tail-lines", type=int, default=None, help="Read only the last N JSONL rows from each journal.")
    parser.add_argument(
        "--include-market-snapshots",
        action="store_true",
        help="Include high-volume market_snapshot rows in event counts.",
    )
    parser.add_argument("--output", default=None, help="Optional Markdown output path.")
    args = parser.parse_args()

    if args.weekly_open_window_hours < 0:
        parser.error("--weekly-open-window-hours must be zero or positive")
    if args.tail_lines is not None and args.tail_lines <= 0:
        parser.error("--tail-lines must be positive")
    if not args.journal and not args.ssh_journal:
        parser.error("provide at least one --journal or --ssh-journal")

    reports = []
    for raw in args.journal:
        label, path = _split_label(raw)
        events = _filter_events(
            _load_local_jsonl(path, tail_lines=args.tail_lines),
            include_market_snapshots=args.include_market_snapshots,
        )
        reports.append(
            build_gate_attribution_report(
                events,
                source=label or Path(path).name,
                weekly_open_window_hours=args.weekly_open_window_hours,
            )
        )
    for raw in args.ssh_journal:
        label, alias, remote_path = _split_ssh_journal(raw)
        events = _filter_events(
            _load_ssh_jsonl(alias, remote_path, tail_lines=args.tail_lines, include_market_snapshots=args.include_market_snapshots),
            include_market_snapshots=args.include_market_snapshots,
        )
        reports.append(
            build_gate_attribution_report(
                events,
                source=label or alias,
                weekly_open_window_hours=args.weekly_open_window_hours,
            )
        )

    markdown = render_gate_attribution_markdown(reports, detail_limit=args.detail_limit)
    print(markdown, end="")
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"\nreport_path={output_path}")
    return 0


def _split_label(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        return "", raw
    label, value = raw.split("=", 1)
    return label.strip(), value.strip()


def _split_ssh_journal(raw: str) -> tuple[str, str, str]:
    label, value = _split_label(raw)
    if ":" not in value:
        raise ValueError("--ssh-journal must be LABEL=ssh-alias:C:\\path\\journal.jsonl")
    alias, remote_path = value.split(":", 1)
    alias = alias.strip()
    remote_path = remote_path.strip()
    if not alias or not remote_path:
        raise ValueError("--ssh-journal must include both ssh alias and remote path")
    return label, alias, remote_path


def _load_local_jsonl(path: str, *, tail_lines: int | None) -> list[dict[str, object]]:
    if tail_lines is None:
        return load_jsonl_events(path)
    with Path(path).open("r", encoding="utf-8") as handle:
        return parse_jsonl_lines(deque(handle, maxlen=tail_lines))


def _load_ssh_jsonl(
    alias: str,
    remote_path: str,
    *,
    tail_lines: int | None,
    include_market_snapshots: bool,
) -> list[dict[str, object]]:
    tail_clause = "" if tail_lines is None else f" -Tail {int(tail_lines)}"
    filter_clause = "" if include_market_snapshots else " | Where-Object { $_ -notlike '*\"event\": \"market_snapshot\"*' }"
    remote_command = f"Get-Content -Path '{remote_path}'{tail_clause}{filter_clause}"
    encoded = base64.b64encode(remote_command.encode("utf-16le")).decode("ascii")
    command = ["ssh", alias, "powershell", "-NoProfile", "-EncodedCommand", encoded]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Failed to read remote journal from {alias}:{remote_path}: {message}")
    return parse_jsonl_lines(result.stdout.splitlines())


def _filter_events(events: list[dict[str, object]], *, include_market_snapshots: bool) -> list[dict[str, object]]:
    if include_market_snapshots:
        return events
    return [row for row in events if str(row.get("event") or "") != "market_snapshot"]


if __name__ == "__main__":
    raise SystemExit(main())
