"""Safely collect and validate local snapshots of active LPFS JSONL journals."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Sequence


DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "live_ops" / "lpfs_journal_snapshots"
MANIFEST_SCHEMA_VERSION = 1
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SnapshotError(RuntimeError):
    """Raised when a journal snapshot cannot be safely collected or validated."""


@dataclass(frozen=True)
class RemoteJournalSpec:
    """One remote journal selected for shared-read snapshot collection."""

    label: str
    ssh_alias: str
    source_path: str

    @property
    def snapshot_filename(self) -> str:
        safe_label = self.label.lower().replace("-", "_")
        return f"{safe_label}_lpfs_journal_snapshot.jsonl"


@dataclass(frozen=True)
class RemoteReadResult:
    """Fixed-range bytes and source metadata returned by a remote shared read."""

    payload: bytes
    before: dict[str, Any]
    after: dict[str, Any]


def parse_ssh_journal(value: str) -> RemoteJournalSpec:
    """Parse LABEL=ssh-alias:C:\\path without splitting the Windows drive."""

    if "=" not in value:
        raise SnapshotError("--ssh-journal must be LABEL=ssh-alias:C:\\path\\journal.jsonl")
    label, remote = value.split("=", 1)
    label = label.strip()
    if not _LABEL_RE.fullmatch(label):
        raise SnapshotError("--ssh-journal LABEL must contain only letters, digits, underscores, or hyphens")
    if ":" not in remote:
        raise SnapshotError("--ssh-journal must include both an SSH alias and a Windows journal path")
    ssh_alias, source_path = remote.split(":", 1)
    ssh_alias = ssh_alias.strip()
    source_path = source_path.strip()
    if not ssh_alias or not source_path:
        raise SnapshotError("--ssh-journal must include both an SSH alias and a Windows journal path")
    if not re.match(r"^[A-Za-z]:[\\/]", source_path):
        raise SnapshotError("--ssh-journal must include both an SSH alias and a Windows journal path")
    return RemoteJournalSpec(label=label, ssh_alias=ssh_alias, source_path=source_path)


def validate_unique_labels(specs: Sequence[RemoteJournalSpec]) -> None:
    """Reject ambiguous output filenames before any remote access occurs."""

    labels = [spec.label.lower() for spec in specs]
    if len(set(labels)) != len(labels):
        raise SnapshotError("--ssh-journal labels must be unique, ignoring case")
    filenames = [spec.snapshot_filename for spec in specs]
    if len(set(filenames)) != len(filenames):
        raise SnapshotError("--ssh-journal labels must produce unique snapshot filenames after normalization")


def build_remote_shared_suffix_reader_script(
    source_path: str,
    *,
    max_source_bytes: int | None,
    hold_open_milliseconds: int = 0,
) -> str:
    """Return read-only PowerShell that emits a fixed source byte range as base64 chunks."""

    if max_source_bytes is not None and max_source_bytes <= 0:
        raise SnapshotError("max_source_bytes must be positive when bounded")
    if hold_open_milliseconds < 0:
        raise SnapshotError("hold_open_milliseconds must be zero or positive")
    byte_limit = 0 if max_source_bytes is None else int(max_source_bytes)
    path_literal = _powershell_single_quoted(source_path)
    return f"""
$ErrorActionPreference = 'Stop'
$Path = {path_literal}
$MaxSourceBytes = {byte_limit}
$HoldOpenMilliseconds = {int(hold_open_milliseconds)}
$BeforeItem = Get-Item -LiteralPath $Path
$stream = [System.IO.FileStream]::new(
  $Path,
  [System.IO.FileMode]::Open,
  [System.IO.FileAccess]::Read,
  [System.IO.FileShare]::ReadWrite
)
try {{
  $SourceEndOffset = [int64]$stream.Length
  if ($MaxSourceBytes -eq 0) {{
    $SourceStartOffset = [int64]0
  }} else {{
    $SourceStartOffset = [Math]::Max([int64]0, $SourceEndOffset - [int64]$MaxSourceBytes)
  }}
  [ordered]@{{
    source_size_bytes_before = [int64]$BeforeItem.Length
    source_last_write_utc_before = $BeforeItem.LastWriteTimeUtc.ToString('o')
    source_start_offset = $SourceStartOffset
    source_end_offset = $SourceEndOffset
  }} | ConvertTo-Json -Compress | ForEach-Object {{ Write-Output "LPFS_META_BEFORE=$_" }}
  Write-Output 'LPFS_READER_OPEN=1'
  if ($HoldOpenMilliseconds -gt 0) {{
    Start-Sleep -Milliseconds $HoldOpenMilliseconds
  }}
  [void]$stream.Seek($SourceStartOffset, [System.IO.SeekOrigin]::Begin)
  $Remaining = $SourceEndOffset - $SourceStartOffset
  $Buffer = New-Object byte[] (48 * 1024)
  while ($Remaining -gt 0) {{
    $Requested = [int][Math]::Min([int64]$Buffer.Length, $Remaining)
    $Read = $stream.Read($Buffer, 0, $Requested)
    if ($Read -le 0) {{
      break
    }}
    Write-Output ("LPFS_CHUNK=" + [Convert]::ToBase64String($Buffer, 0, $Read))
    $Remaining -= $Read
  }}
}} finally {{
  $stream.Close()
}}
$AfterItem = Get-Item -LiteralPath $Path
[ordered]@{{
  source_size_bytes_after = [int64]$AfterItem.Length
  source_last_write_utc_after = $AfterItem.LastWriteTimeUtc.ToString('o')
}} | ConvertTo-Json -Compress | ForEach-Object {{ Write-Output "LPFS_META_AFTER=$_" }}
"""


def run_remote_shared_suffix_read(
    spec: RemoteJournalSpec,
    *,
    max_source_bytes: int | None,
    timeout: int = 180,
) -> RemoteReadResult:
    """Run the generated read-only PowerShell over SSH and decode its fixed-range payload."""

    script = build_remote_shared_suffix_reader_script(spec.source_path, max_source_bytes=max_source_bytes)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["ssh", spec.ssh_alias, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError(f"Timed out collecting {spec.label} journal from {spec.ssh_alias}") from exc
    except OSError as exc:
        raise SnapshotError(f"Could not start SSH collection for {spec.label} journal from {spec.ssh_alias}") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SnapshotError(f"Failed to collect {spec.label} journal from {spec.ssh_alias}: {message}")
    return parse_remote_shared_suffix_output(result.stdout)


def parse_remote_shared_suffix_output(output: str) -> RemoteReadResult:
    """Decode metadata and base64 chunks emitted by the remote reader."""

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    chunks: list[bytes] = []
    for line in output.splitlines():
        if line.startswith("LPFS_META_BEFORE="):
            try:
                before_payload = json.loads(line.removeprefix("LPFS_META_BEFORE="))
            except json.JSONDecodeError as exc:
                raise SnapshotError("Remote journal payload contained invalid before metadata") from exc
            if not isinstance(before_payload, dict):
                raise SnapshotError("Remote journal payload contained invalid before metadata")
            before = dict(before_payload)
        elif line.startswith("LPFS_META_AFTER="):
            try:
                after_payload = json.loads(line.removeprefix("LPFS_META_AFTER="))
            except json.JSONDecodeError as exc:
                raise SnapshotError("Remote journal payload contained invalid after metadata") from exc
            if not isinstance(after_payload, dict):
                raise SnapshotError("Remote journal payload contained invalid after metadata")
            after = dict(after_payload)
        elif line.startswith("LPFS_CHUNK="):
            try:
                chunks.append(base64.b64decode(line.removeprefix("LPFS_CHUNK="), validate=True))
            except ValueError as exc:
                raise SnapshotError("Remote journal payload contained invalid base64") from exc
    if before is None or after is None:
        raise SnapshotError("Remote journal payload did not include required metadata")
    return RemoteReadResult(payload=b"".join(chunks), before=before, after=after)


def prepare_snapshot_payload(
    result: RemoteReadResult,
    *,
    include_market_snapshots: bool,
) -> tuple[bytes, dict[str, Any]]:
    """Validate complete JSONL rows and return the publishable local snapshot bytes."""

    try:
        source_start_offset = int(result.before["source_start_offset"])
        source_end_offset = int(result.before["source_end_offset"])
        source_size_bytes_before = int(result.before["source_size_bytes_before"])
        source_last_write_utc_before = str(result.before["source_last_write_utc_before"])
        source_size_bytes_after = int(result.after["source_size_bytes_after"])
        source_last_write_utc_after = str(result.after["source_last_write_utc_after"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotError("Remote journal payload contained invalid metadata") from exc
    if source_start_offset < 0 or source_end_offset < source_start_offset:
        raise SnapshotError("Remote journal payload contained an invalid source byte range")
    payload = result.payload
    expected_bytes = source_end_offset - source_start_offset
    if len(payload) != expected_bytes:
        raise SnapshotError(f"Remote journal payload length mismatch: expected {expected_bytes}, received {len(payload)}")

    if source_start_offset > 0:
        boundary = payload.find(b"\n")
        payload = b"" if boundary < 0 else payload[boundary + 1 :]
    if payload and not payload.endswith(b"\n"):
        boundary = payload.rfind(b"\n")
        payload = b"" if boundary < 0 else payload[: boundary + 1]

    published_lines: list[bytes] = []
    first_event_timestamp = ""
    last_event_timestamp = ""
    for raw_line in payload.splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotError("Remote journal payload contained a malformed complete JSONL row") from exc
        if not isinstance(row, dict):
            raise SnapshotError("Remote journal payload contained a non-object JSONL row")
        if not include_market_snapshots and str(row.get("event") or "") == "market_snapshot":
            continue
        occurred_at = str(row.get("occurred_at_utc") or "")
        if occurred_at and not first_event_timestamp:
            first_event_timestamp = occurred_at
        if occurred_at:
            last_event_timestamp = occurred_at
        published_lines.append(raw_line + b"\n")

    snapshot = b"".join(published_lines)
    return snapshot, {
        "source_start_offset": source_start_offset,
        "source_end_offset": source_end_offset,
        "source_size_bytes_before": source_size_bytes_before,
        "source_last_write_utc_before": source_last_write_utc_before,
        "source_size_bytes_after": source_size_bytes_after,
        "source_last_write_utc_after": source_last_write_utc_after,
        "source_changed_during_collection": (
            source_size_bytes_before != source_size_bytes_after
            or source_last_write_utc_before != source_last_write_utc_after
        ),
        "reached_source_start": source_start_offset == 0,
        "captured_row_count": len(published_lines),
        "first_event_timestamp": first_event_timestamp,
        "last_event_timestamp": last_event_timestamp,
        "snapshot_bytes": len(snapshot),
        "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
    }


def collect_snapshots(
    specs: Sequence[RemoteJournalSpec],
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    max_source_bytes: int | None = DEFAULT_MAX_SOURCE_BYTES,
    include_market_snapshots: bool = False,
    collected_at_utc: datetime | None = None,
    fetcher: Callable[..., RemoteReadResult] = run_remote_shared_suffix_read,
) -> Path:
    """Collect every requested lane and atomically publish one local snapshot directory."""

    if not specs:
        raise SnapshotError("provide at least one --ssh-journal")
    validate_unique_labels(specs)
    if max_source_bytes is not None and max_source_bytes <= 0:
        raise SnapshotError("--max-source-bytes must be positive")

    output_root = Path(output_root)
    collected_at = collected_at_utc or datetime.now(timezone.utc)
    stamp = collected_at.strftime("%Y%m%d_%H%M%S")
    final_dir = output_root / stamp
    staging_dir = output_root / f".{stamp}.{os.getpid()}.tmp"
    if final_dir.exists() or staging_dir.exists():
        raise SnapshotError(f"snapshot output already exists for timestamp {stamp}")

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir()
    snapshots: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc)
    try:
        for spec in specs:
            result = fetcher(spec, max_source_bytes=max_source_bytes)
            snapshot, metadata = prepare_snapshot_payload(
                result,
                include_market_snapshots=include_market_snapshots,
            )
            snapshot_path = staging_dir / spec.snapshot_filename
            snapshot_path.write_bytes(snapshot)
            snapshots.append(
                {
                    "label": spec.label,
                    "ssh_alias": spec.ssh_alias,
                    "source_path": spec.source_path,
                    "snapshot_filename": spec.snapshot_filename,
                    "scan_mode": "full" if max_source_bytes is None else "bounded_suffix",
                    "max_source_bytes": max_source_bytes,
                    "include_market_snapshots": include_market_snapshots,
                    **metadata,
                }
            )
        completed_at = datetime.now(timezone.utc)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "collection_started_at_utc": started_at.isoformat(),
            "collection_completed_at_utc": completed_at.isoformat(),
            "snapshots": snapshots,
        }
        (staging_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(staging_dir, final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return final_dir


def validate_manifest_backed_snapshot(path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Return a collector snapshot only when its sibling manifest and SHA-256 match."""

    snapshot_path = Path(path)
    manifest_path = snapshot_path.parent / "manifest.json"
    if not snapshot_path.is_file():
        raise SnapshotError(f"Journal snapshot not found: {snapshot_path}")
    if not manifest_path.is_file():
        raise SnapshotError(f"Collector manifest not found beside journal snapshot: {manifest_path}")
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Could not read collector manifest: {manifest_path}") from exc
    if not isinstance(manifest_payload, dict):
        raise SnapshotError(f"Collector manifest must contain a JSON object: {manifest_path}")
    manifest = dict(manifest_payload)
    try:
        schema_version = int(manifest.get("schema_version", 0))
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"Unsupported collector manifest schema: {manifest.get('schema_version')}") from exc
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise SnapshotError(f"Unsupported collector manifest schema: {manifest.get('schema_version')}")
    raw_entries = manifest.get("snapshots", [])
    if not isinstance(raw_entries, list):
        raise SnapshotError(f"Collector manifest snapshots must be a list: {manifest_path}")
    entries = [
        dict(entry)
        for entry in raw_entries
        if isinstance(entry, dict) and entry.get("snapshot_filename") == snapshot_path.name
    ]
    if len(entries) != 1:
        raise SnapshotError(f"Collector manifest must contain exactly one entry for {snapshot_path.name}")
    entry = entries[0]
    try:
        snapshot = snapshot_path.read_bytes()
    except OSError as exc:
        raise SnapshotError(f"Could not read journal snapshot: {snapshot_path}") from exc
    actual_sha256 = hashlib.sha256(snapshot).hexdigest()
    if actual_sha256 != str(entry.get("snapshot_sha256") or ""):
        raise SnapshotError(f"Journal snapshot SHA-256 does not match collector manifest: {snapshot_path}")
    try:
        expected_bytes = int(entry.get("snapshot_bytes", -1))
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"Journal snapshot byte count is invalid in collector manifest: {snapshot_path}") from exc
    if len(snapshot) != expected_bytes:
        raise SnapshotError(f"Journal snapshot byte count does not match collector manifest: {snapshot_path}")
    return snapshot_path, manifest, entry


def require_snapshot_period_coverage(
    entry: dict[str, Any],
    *,
    days: int | None,
    weeks: int | None,
    now_utc: datetime | None = None,
) -> None:
    """Reject historical windows that a truncated suffix snapshot cannot prove it covers."""

    if days is None and weeks is None:
        return
    if bool(entry.get("reached_source_start")):
        return
    window_days = int(days if days is not None else int(weeks or 0) * 7)
    start = (now_utc or datetime.now(timezone.utc)) - timedelta(days=window_days)
    earliest = _parse_timestamp(str(entry.get("first_event_timestamp") or ""))
    if earliest is None or earliest > start:
        raise SnapshotError(
            "Journal snapshot cannot prove coverage for the requested historical period. "
            "Collect a larger bounded snapshot or use --allow-full-scan only with explicit approval."
        )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
