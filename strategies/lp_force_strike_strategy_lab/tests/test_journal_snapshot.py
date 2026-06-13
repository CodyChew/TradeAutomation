from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from lpfs_journal_snapshot import (  # noqa: E402
    DEFAULT_MAX_SOURCE_BYTES,
    RemoteJournalSpec,
    RemoteReadResult,
    SnapshotError,
    build_remote_shared_suffix_reader_script,
    collect_snapshots,
    parse_remote_shared_suffix_output,
    parse_ssh_journal,
    prepare_snapshot_payload,
    require_snapshot_period_coverage,
    validate_manifest_backed_snapshot,
    validate_unique_labels,
)


class JournalSnapshotTests(unittest.TestCase):
    def test_parse_ssh_journal_preserves_windows_path_and_builds_safe_filename(self) -> None:
        spec = parse_ssh_journal(r"FTMO-Live=lpfs-vps:C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl")

        self.assertEqual(spec.label, "FTMO-Live")
        self.assertEqual(spec.ssh_alias, "lpfs-vps")
        self.assertEqual(spec.source_path, r"C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl")
        self.assertEqual(spec.snapshot_filename, "ftmo_live_lpfs_journal_snapshot.jsonl")
        with self.assertRaisesRegex(SnapshotError, "LABEL"):
            parse_ssh_journal(r"bad label=lpfs-vps:C:\journal.jsonl")
        with self.assertRaisesRegex(SnapshotError, "SSH alias"):
            parse_ssh_journal(r"FTMO=C:\journal.jsonl")
        with self.assertRaisesRegex(SnapshotError, "unique"):
            validate_unique_labels(
                [
                    RemoteJournalSpec("FTMO", "a", r"C:\a.jsonl"),
                    RemoteJournalSpec("ftmo", "b", r"C:\b.jsonl"),
                ]
            )
        with self.assertRaisesRegex(SnapshotError, "normalization"):
            validate_unique_labels(
                [
                    RemoteJournalSpec("FTMO-Live", "a", r"C:\a.jsonl"),
                    RemoteJournalSpec("FTMO_Live", "b", r"C:\b.jsonl"),
                ]
            )

    def test_generated_remote_reader_is_shared_read_only_and_bounded(self) -> None:
        script = build_remote_shared_suffix_reader_script(
            r"C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl",
            max_source_bytes=DEFAULT_MAX_SOURCE_BYTES,
        )

        self.assertIn("[System.IO.FileShare]::ReadWrite", script)
        self.assertIn("$MaxSourceBytes = 67108864", script)
        self.assertIn("source_start_offset", script)
        self.assertIn("source_end_offset", script)
        self.assertNotIn("OpenText", script)
        self.assertNotIn("Get-Content", script)
        self.assertNotIn("Set-Content", script)
        self.assertNotIn("Add-Content", script)
        self.assertNotIn("Out-File", script)
        self.assertNotIn("MetaTrader5", script)
        with self.assertRaisesRegex(SnapshotError, "positive"):
            build_remote_shared_suffix_reader_script(r"C:\journal.jsonl", max_source_bytes=0)
        self.assertIn(
            "$MaxSourceBytes = 0",
            build_remote_shared_suffix_reader_script(r"C:\journal.jsonl", max_source_bytes=None),
        )

    def test_collector_cli_rejects_missing_invalid_and_duplicate_inputs_before_remote_access(self) -> None:
        script = SCRIPTS_ROOT / "collect_lpfs_live_journal_snapshots.py"
        cases = [
            ([], "provide at least one --ssh-journal"),
            (["--ssh-journal", r"FTMO=C:\journal.jsonl"], "SSH alias"),
            (
                [
                    "--ssh-journal",
                    r"FTMO=lane-a:C:\journal.jsonl",
                    "--ssh-journal",
                    r"ftmo=lane-b:C:\journal.jsonl",
                ],
                "unique",
            ),
            (
                [
                    "--ssh-journal",
                    r"FTMO=lane-a:C:\journal.jsonl",
                    "--max-source-bytes",
                    "0",
                ],
                "--max-source-bytes must be positive",
            ),
        ]
        for extra_args, expected in cases:
            with self.subTest(args=extra_args):
                result = subprocess.run(
                    [sys.executable, str(script), *extra_args],
                    cwd=WORKSPACE_ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)

        help_result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=WORKSPACE_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn("--output-root", help_result.stdout)

    def test_prepare_snapshot_payload_discards_boundaries_and_filters_market_snapshots(self) -> None:
        payload = (
            b'partial-row\n'
            b'{"event":"order_sent","occurred_at_utc":"2026-05-01T00:00:00+00:00"}\n'
            b'{"event":"market_snapshot","occurred_at_utc":"2026-05-01T00:01:00+00:00"}\n'
            b'{"event":"position_opened","occurred_at_utc":"2026-05-01T00:02:00+00:00"}\n'
            b'partial-trailing'
        )
        result = _remote_result(payload, source_start_offset=100)

        snapshot, metadata = prepare_snapshot_payload(result, include_market_snapshots=False)

        self.assertEqual(
            snapshot.splitlines(),
            [
                b'{"event":"order_sent","occurred_at_utc":"2026-05-01T00:00:00+00:00"}',
                b'{"event":"position_opened","occurred_at_utc":"2026-05-01T00:02:00+00:00"}',
            ],
        )
        self.assertEqual(metadata["source_start_offset"], 100)
        self.assertEqual(metadata["source_end_offset"], 100 + len(payload))
        self.assertEqual(metadata["captured_row_count"], 2)
        self.assertFalse(metadata["reached_source_start"])

        included, included_metadata = prepare_snapshot_payload(result, include_market_snapshots=True)
        self.assertEqual(len(included.splitlines()), 3)
        self.assertEqual(included_metadata["captured_row_count"], 3)

    def test_prepare_snapshot_payload_rejects_malformed_complete_rows(self) -> None:
        with self.assertRaisesRegex(SnapshotError, "malformed"):
            prepare_snapshot_payload(_remote_result(b'{"event":"ok"}\nnot-json\n'), include_market_snapshots=False)
        with self.assertRaisesRegex(SnapshotError, "invalid metadata"):
            prepare_snapshot_payload(
                RemoteReadResult(payload=b"", before={}, after={}),
                include_market_snapshots=False,
            )

    def test_collect_snapshots_publishes_atomically_with_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "snapshots"
            specs = [
                RemoteJournalSpec("FTMO", "lpfs-vps", r"C:\ftmo.jsonl"),
                RemoteJournalSpec("IC", "lpfs-ic-vps", r"C:\ic.jsonl"),
            ]

            def fetcher(spec: RemoteJournalSpec, *, max_source_bytes: int | None) -> RemoteReadResult:
                self.assertEqual(max_source_bytes, 100)
                row = json.dumps({"event": "order_sent", "occurred_at_utc": f"2026-05-01T00:00:0{len(spec.label)}Z"})
                return _remote_result((row + "\n").encode("utf-8"))

            output_dir = collect_snapshots(
                specs,
                output_root=output_root,
                max_source_bytes=100,
                collected_at_utc=datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
                fetcher=fetcher,
            )

            self.assertEqual(output_dir.name, "20260531_150000")
            self.assertFalse(list(output_root.glob(".*.tmp")))
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(len(manifest["snapshots"]), 2)
            entry = manifest["snapshots"][0]
            snapshot_path = output_dir / entry["snapshot_filename"]
            self.assertEqual(entry["scan_mode"], "bounded_suffix")
            self.assertEqual(entry["max_source_bytes"], 100)
            self.assertFalse(entry["include_market_snapshots"])
            self.assertEqual(entry["source_start_offset"], 0)
            self.assertEqual(entry["source_end_offset"], snapshot_path.stat().st_size)
            self.assertEqual(entry["source_size_bytes_before"], snapshot_path.stat().st_size)
            self.assertEqual(entry["source_size_bytes_after"], snapshot_path.stat().st_size)
            self.assertFalse(entry["source_changed_during_collection"])
            self.assertTrue(entry["reached_source_start"])
            self.assertEqual(entry["captured_row_count"], 1)
            self.assertTrue(entry["first_event_timestamp"])
            self.assertTrue(entry["last_event_timestamp"])
            self.assertEqual(entry["snapshot_sha256"], hashlib.sha256(snapshot_path.read_bytes()).hexdigest())
            self.assertEqual(validate_manifest_backed_snapshot(snapshot_path)[2], entry)

    def test_collect_snapshots_cleans_staging_after_multi_lane_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "snapshots"
            specs = [
                RemoteJournalSpec("FTMO", "lpfs-vps", r"C:\ftmo.jsonl"),
                RemoteJournalSpec("IC", "lpfs-ic-vps", r"C:\ic.jsonl"),
            ]

            def fetcher(spec: RemoteJournalSpec, *, max_source_bytes: int | None) -> RemoteReadResult:
                if spec.label == "IC":
                    raise SnapshotError("simulated fetch failure")
                return _remote_result(b'{"event":"order_sent"}\n')

            with self.assertRaisesRegex(SnapshotError, "simulated"):
                collect_snapshots(
                    specs,
                    output_root=output_root,
                    collected_at_utc=datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
                    fetcher=fetcher,
                )

            self.assertFalse(list(output_root.iterdir()))

    def test_manifest_validation_detects_tampering_and_period_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = _write_snapshot_fixture(
                Path(tmpdir),
                reached_source_start=False,
                first_event_timestamp="2026-05-20T00:00:00+00:00",
            )
            _, _, entry = validate_manifest_backed_snapshot(snapshot_path)
            with self.assertRaisesRegex(SnapshotError, "cannot prove coverage"):
                require_snapshot_period_coverage(
                    entry,
                    days=14,
                    weeks=None,
                    now_utc=datetime(2026, 5, 31, tzinfo=timezone.utc),
                )
            require_snapshot_period_coverage(
                entry,
                days=7,
                weeks=None,
                now_utc=datetime(2026, 5, 31, tzinfo=timezone.utc),
            )

            snapshot_path.write_text('{"event":"tampered"}\n', encoding="utf-8")
            with self.assertRaisesRegex(SnapshotError, "SHA-256"):
                validate_manifest_backed_snapshot(snapshot_path)

            (snapshot_path.parent / "manifest.json").write_text('{"schema_version":"bad"}', encoding="utf-8")
            with self.assertRaisesRegex(SnapshotError, "schema"):
                validate_manifest_backed_snapshot(snapshot_path)

    def test_windows_shared_reader_allows_append_while_handle_is_open(self) -> None:
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows PowerShell is required for shared-read concurrency coverage.")

        with tempfile.TemporaryDirectory() as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            journal.write_text('{"event":"seed"}\n', encoding="utf-8")
            script = build_remote_shared_suffix_reader_script(
                str(journal),
                max_source_bytes=DEFAULT_MAX_SOURCE_BYTES,
                hold_open_milliseconds=1000,
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            process = subprocess.Popen(
                [powershell, "-NoProfile", "-EncodedCommand", encoded],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            lines: list[str] = []
            try:
                while True:
                    line = process.stdout.readline()
                    self.assertTrue(line, "PowerShell reader exited before opening the shared handle")
                    lines.append(line)
                    if line.strip() == "LPFS_READER_OPEN=1":
                        break
                with journal.open("a", encoding="utf-8") as handle:
                    handle.write('{"event":"appended"}\n')
                stdout, stderr = process.communicate(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
            self.assertEqual(process.returncode, 0, stderr)
            result = parse_remote_shared_suffix_output("".join(lines) + stdout)
            snapshot, _ = prepare_snapshot_payload(result, include_market_snapshots=False)
            self.assertEqual(snapshot, b'{"event":"seed"}\n')
            self.assertIn('{"event":"appended"}', journal.read_text(encoding="utf-8"))

    def test_existing_weekly_and_status_read_contracts_remain_visible(self) -> None:
        weekly = (WORKSPACE_ROOT / "scripts" / "build_lpfs_live_weekly_performance.py").read_text(encoding="utf-8")
        status = (WORKSPACE_ROOT / "scripts" / "Get-LpfsLiveStatus.ps1").read_text(encoding="utf-8")

        self.assertIn("CreateFileW", weekly)
        self.assertIn("file_share_write", weekly)
        self.assertIn("Get-Content -LiteralPath $JournalPath -Tail $JournalLines", status)
        self.assertIn("Get-Content -LiteralPath $LatestLog.FullName -Tail $LogLines", status)


def _remote_result(payload: bytes, *, source_start_offset: int = 0) -> RemoteReadResult:
    source_end_offset = source_start_offset + len(payload)
    return RemoteReadResult(
        payload=payload,
        before={
            "source_size_bytes_before": source_end_offset,
            "source_last_write_utc_before": "2026-05-31T00:00:00.0000000Z",
            "source_start_offset": source_start_offset,
            "source_end_offset": source_end_offset,
        },
        after={
            "source_size_bytes_after": source_end_offset,
            "source_last_write_utc_after": "2026-05-31T00:00:00.0000000Z",
        },
    )


def _write_snapshot_fixture(
    root: Path,
    *,
    reached_source_start: bool,
    first_event_timestamp: str,
) -> Path:
    snapshot_path = root / "ftmo_lpfs_journal_snapshot.jsonl"
    snapshot = b'{"event":"order_sent","occurred_at_utc":"2026-05-30T00:00:00+00:00"}\n'
    snapshot_path.write_bytes(snapshot)
    manifest = {
        "schema_version": 1,
        "snapshots": [
            {
                "snapshot_filename": snapshot_path.name,
                "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
                "snapshot_bytes": len(snapshot),
                "reached_source_start": reached_source_start,
                "first_event_timestamp": first_event_timestamp,
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return snapshot_path


if __name__ == "__main__":
    unittest.main()
