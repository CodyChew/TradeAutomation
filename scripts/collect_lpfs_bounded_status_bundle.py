#!/usr/bin/env python3
"""Collect one bounded LPFS status bundle using an embedded reviewed script."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Sequence


BOUNDED_STATUS_BUNDLE_KIND = "hash_approved_bounded_status_v1"
COMPACT_CONTAINMENT_BUNDLE_KIND = "hash_approved_compact_containment_v1"
EXECUTION_SCHEMA_VERSION = 1
READ_ONLY_ACKNOWLEDGEMENT = "I_ACCEPT_HASH_APPROVED_READ_ONLY_STATUS_COLLECTION"
SAFE_STEP_RE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
EMBEDDED_SCRIPT_SOURCE = "embedded_hash_approved_scriptblock"
STDIN_SCRIPT_SOURCE = "stdin_hash_approved_scriptblock"
COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH = 4000


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(payload: str) -> str:
    return _sha256_bytes(payload.encode("utf-8"))


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _encode_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _status_parameters(
    *,
    runtime_root: str,
    state_file_name: str,
    journal_file_name: str,
    heartbeat_file_name: str,
    log_filter: str,
    journal_lines: int,
    log_lines: int,
) -> str:
    values: tuple[tuple[str, str | int], ...] = (
        ("RuntimeRoot", runtime_root),
        ("StateFileName", state_file_name),
        ("JournalFileName", journal_file_name),
        ("HeartbeatFileName", heartbeat_file_name),
        ("LogFilter", log_filter),
        ("JournalLines", journal_lines),
        ("LogLines", log_lines),
    )
    assignments = []
    for key, value in values:
        rendered = str(value) if isinstance(value, int) else _powershell_quote(value)
        assignments.append(f"    {key} = {rendered}")
    return "@{\n" + "\n".join(assignments) + "\n}"


def build_remote_status_command(
    *,
    ssh_alias: str,
    status_implementation: bytes,
    expected_status_sha256: str,
    runtime_root: str,
    state_file_name: str,
    journal_file_name: str,
    heartbeat_file_name: str,
    log_filter: str,
    journal_lines: int,
    log_lines: int,
) -> list[str]:
    """Build a read-only SSH command that executes reviewed status bytes in memory."""
    expected = expected_status_sha256.lower()
    if not SHA256_RE.fullmatch(expected):
        raise ValueError("expected status SHA-256 must be 64 lowercase hexadecimal characters")
    actual = _sha256_bytes(status_implementation)
    if actual != expected:
        raise ValueError(f"status implementation SHA-256 mismatch: expected={expected} actual={actual}")
    if not ssh_alias or any(character.isspace() for character in ssh_alias):
        raise ValueError("SSH alias must be a nonempty token without whitespace")
    if journal_lines < 0 or log_lines < 0:
        raise ValueError("journal and log line counts must be nonnegative")

    params = _status_parameters(
        runtime_root=runtime_root,
        state_file_name=state_file_name,
        journal_file_name=journal_file_name,
        heartbeat_file_name=heartbeat_file_name,
        log_filter=log_filter,
        journal_lines=journal_lines,
        log_lines=log_lines,
    )
    bootstrap = f"""$ErrorActionPreference = 'Stop'
$EncodedImplementation = [Console]::In.ReadToEnd()
$ImplementationBytes = [Convert]::FromBase64String($EncodedImplementation)
$Hasher = [Security.Cryptography.SHA256]::Create()
try {{
    $ActualHash = ([BitConverter]::ToString($Hasher.ComputeHash($ImplementationBytes))).Replace('-', '').ToLowerInvariant()
}} finally {{
    $Hasher.Dispose()
}}
if ($ActualHash -ne '{expected}') {{
    throw "LPFS status implementation hash mismatch: $ActualHash"
}}
Write-Output 'LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={expected}'
$ImplementationText = [Text.Encoding]::UTF8.GetString($ImplementationBytes)
$StatusBlock = [ScriptBlock]::Create($ImplementationText)
$StatusParams = {params}
& $StatusBlock @StatusParams
"""
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        _encode_powershell(bootstrap),
    ]


def build_remote_compact_containment_command(
    *,
    ssh_alias: str,
    expected_compact_script_sha256: str,
) -> list[str]:
    """Build a short read-only SSH command that executes reviewed script bytes from stdin."""
    expected = expected_compact_script_sha256.lower()
    if not SHA256_RE.fullmatch(expected):
        raise ValueError("expected compact script SHA-256 must be 64 lowercase hexadecimal characters")
    if not ssh_alias or any(character.isspace() for character in ssh_alias):
        raise ValueError("SSH alias must be a nonempty token without whitespace")

    bootstrap = f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$EncodedScript = [Console]::In.ReadToEnd()
$ScriptBytes = [Convert]::FromBase64String($EncodedScript)
$Hasher = [Security.Cryptography.SHA256]::Create()
try {{
    $ActualHash = ([BitConverter]::ToString($Hasher.ComputeHash($ScriptBytes))).Replace('-', '').ToLowerInvariant()
}} finally {{
    $Hasher.Dispose()
}}
if ($ActualHash -ne '{expected}') {{
    throw "LPFS compact containment script hash mismatch: $ActualHash"
}}
Write-Output 'LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={expected}'
$ScriptText = [Text.Encoding]::UTF8.GetString($ScriptBytes)
$ScriptBlock = [ScriptBlock]::Create($ScriptText)
& $ScriptBlock
"""
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        ssh_alias,
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        _encode_powershell(bootstrap),
    ]


def render_command(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command)) + "\n"


def _safe_step_base(output_root: Path, step_name: str) -> Path:
    normalized = step_name.replace("\\", "/").strip("/")
    if (
        normalized != step_name
        or not SAFE_STEP_RE.fullmatch(normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ValueError(f"invalid bundle step name: {step_name!r}")
    root = output_root.resolve()
    base = (root / Path(*normalized.split("/"))).resolve()
    if root != base and root not in base.parents:
        raise ValueError("bundle step resolves outside output root")
    base.parent.mkdir(parents=True, exist_ok=True)
    return base


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, payload: str) -> None:
    _atomic_write_bytes(path, payload.encode("utf-8"))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def collect_status_bundle(
    *,
    output_root: str | Path,
    step_name: str,
    ssh_alias: str,
    status_script_path: str | Path,
    expected_status_sha256: str,
    expected_command_sha256: str,
    runtime_root: str,
    state_file_name: str,
    journal_file_name: str,
    heartbeat_file_name: str,
    log_filter: str,
    journal_lines: int,
    log_lines: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    expected_command = expected_command_sha256.lower()
    if not SHA256_RE.fullmatch(expected_command):
        raise ValueError("expected command SHA-256 must be 64 lowercase hexadecimal characters")

    status_path = Path(status_script_path)
    implementation = status_path.read_bytes()
    command = build_remote_status_command(
        ssh_alias=ssh_alias,
        status_implementation=implementation,
        expected_status_sha256=expected_status_sha256,
        runtime_root=runtime_root,
        state_file_name=state_file_name,
        journal_file_name=journal_file_name,
        heartbeat_file_name=heartbeat_file_name,
        log_filter=log_filter,
        journal_lines=journal_lines,
        log_lines=log_lines,
    )
    command_text = render_command(command)
    command_sha256 = _sha256_text(command_text)
    expected = expected_status_sha256.lower()
    verification_marker = f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={expected}"
    base = _safe_step_base(Path(output_root), step_name)
    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
        "timeout": base.with_name(base.name + ".timeout.txt"),
        "status_implementation": base.with_name(base.name + ".status_implementation.ps1"),
        "execution": base.with_name(base.name + ".execution.json"),
    }

    if command_sha256 != expected_command:
        execution = {
            "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
            "command_hash_matches_expected": False,
            "command_sha256": command_sha256,
            "execution_attempted": False,
            "exit_code": None,
            "expected_command_sha256": expected_command,
            "remote_status_implementation_sha256_verified": False,
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "status_implementation_sha256": _sha256_bytes(implementation),
            "status_implementation_source": EMBEDDED_SCRIPT_SOURCE,
            "stderr_empty": True,
            "stdout_nonempty": False,
            "timed_out": False,
            "timeout_seconds": timeout_seconds,
        }
        _atomic_write_text(paths["command"], command_text)
        _atomic_write_text(paths["stdout"], "")
        _atomic_write_text(paths["stderr"], "")
        _atomic_write_text(paths["exit_code"], "NOT_EXECUTED\n")
        _atomic_write_text(paths["timeout"], "false\n")
        _atomic_write_bytes(paths["status_implementation"], implementation)
        _atomic_write_json(paths["execution"], execution)
        return {
            "schema_version": 1,
            "status": "STOPPED",
            "reason": (
                "generated SSH command SHA-256 does not match the reviewed expected command SHA-256; "
                "SSH was not invoked"
            ),
            "step": step_name,
            "execution": execution,
            "artifacts": {key: str(value) for key, value in paths.items()},
        }

    timed_out = False
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            input=base64.b64encode(implementation).decode("ascii"),
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        exit_code = 124

    execution = {
        "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
        "command_hash_matches_expected": True,
        "command_sha256": command_sha256,
        "execution_attempted": True,
        "exit_code": exit_code,
        "expected_command_sha256": expected_command,
        "remote_status_implementation_sha256_verified": verification_marker in stdout.splitlines(),
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "status_implementation_sha256": _sha256_bytes(implementation),
        "status_implementation_source": EMBEDDED_SCRIPT_SOURCE,
        "stderr_empty": not bool(stderr.strip()),
        "stdout_nonempty": bool(stdout.strip()),
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
    }

    _atomic_write_text(paths["command"], command_text)
    _atomic_write_text(paths["stdout"], stdout)
    _atomic_write_text(paths["stderr"], stderr)
    _atomic_write_text(paths["exit_code"], f"{exit_code}\n")
    _atomic_write_text(paths["timeout"], f"{str(timed_out).lower()}\n")
    _atomic_write_bytes(paths["status_implementation"], implementation)
    _atomic_write_json(paths["execution"], execution)

    passed = (
        not timed_out
        and exit_code == 0
        and bool(stdout.strip())
        and not bool(stderr.strip())
        and execution["remote_status_implementation_sha256_verified"]
    )
    return {
        "schema_version": 1,
        "status": "PASS" if passed else "STOPPED",
        "reason": (
            "bounded status command completed with the embedded reviewed implementation"
            if passed
            else "bounded status command failed one or more mandatory safety checks"
        ),
        "step": step_name,
        "execution": execution,
        "artifacts": {key: str(value) for key, value in paths.items()},
    }


def collect_compact_containment_bundle(
    *,
    output_root: str | Path,
    step_name: str,
    ssh_alias: str,
    compact_script_path: str | Path,
    expected_compact_script_sha256: str,
    expected_command_sha256: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    expected_command = expected_command_sha256.lower()
    expected_script = expected_compact_script_sha256.lower()
    if not SHA256_RE.fullmatch(expected_command):
        raise ValueError("expected command SHA-256 must be 64 lowercase hexadecimal characters")
    if not SHA256_RE.fullmatch(expected_script):
        raise ValueError("expected compact script SHA-256 must be 64 lowercase hexadecimal characters")

    script_path = Path(compact_script_path)
    script_bytes = script_path.read_bytes()
    actual_script_sha256 = _sha256_bytes(script_bytes)
    command = build_remote_compact_containment_command(
        ssh_alias=ssh_alias,
        expected_compact_script_sha256=expected_script,
    )
    command_text = render_command(command)
    command_sha256 = _sha256_text(command_text)
    command_length = len(command_text)
    verification_marker = f"LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={expected_script}"
    base = _safe_step_base(Path(output_root), step_name)
    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
        "timeout": base.with_name(base.name + ".timeout.txt"),
        "compact_script": base.with_name(base.name + ".remote.ps1"),
        "execution": base.with_name(base.name + ".execution.json"),
    }

    preflight_failures: list[str] = []
    if command_sha256 != expected_command:
        preflight_failures.append("generated SSH command SHA-256 does not match the reviewed expected command")
    if actual_script_sha256 != expected_script:
        preflight_failures.append("compact script SHA-256 does not match the reviewed expected script")
    if command_length >= COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH:
        preflight_failures.append(
            f"generated SSH command length {command_length} exceeds safe threshold "
            f"{COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH}"
        )

    def execution_payload(*, attempted: bool, exit_code: int | None, timed_out: bool, stdout: str, stderr: str) -> dict[str, Any]:
        return {
            "bundle_kind": COMPACT_CONTAINMENT_BUNDLE_KIND,
            "command_hash_matches_expected": command_sha256 == expected_command,
            "command_length": command_length,
            "command_length_within_safe_threshold": command_length < COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH,
            "command_sha256": command_sha256,
            "compact_script_hash_matches_expected": actual_script_sha256 == expected_script,
            "compact_script_sha256": actual_script_sha256,
            "compact_script_source": STDIN_SCRIPT_SOURCE,
            "execution_attempted": attempted,
            "exit_code": exit_code,
            "expected_command_sha256": expected_command,
            "expected_compact_script_sha256": expected_script,
            "remote_compact_script_sha256_verified": verification_marker in stdout.splitlines(),
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "stderr_empty": not bool(stderr.strip()),
            "stdout_nonempty": bool(stdout.strip()),
            "timed_out": timed_out,
            "timeout_seconds": timeout_seconds,
        }

    if preflight_failures:
        execution = execution_payload(attempted=False, exit_code=None, timed_out=False, stdout="", stderr="")
        _atomic_write_text(paths["command"], command_text)
        _atomic_write_text(paths["stdout"], "")
        _atomic_write_text(paths["stderr"], "")
        _atomic_write_text(paths["exit_code"], "NOT_EXECUTED\n")
        _atomic_write_text(paths["timeout"], "false\n")
        _atomic_write_bytes(paths["compact_script"], script_bytes)
        _atomic_write_json(paths["execution"], execution)
        return {
            "schema_version": 1,
            "status": "STOPPED",
            "reason": "; ".join(preflight_failures) + "; SSH was not invoked",
            "step": step_name,
            "execution": execution,
            "artifacts": {key: str(value) for key, value in paths.items()},
        }

    timed_out = False
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            input=base64.b64encode(script_bytes).decode("ascii"),
            text=True,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _timeout_text(exc.stdout)
        stderr = _timeout_text(exc.stderr)
        exit_code = 124

    execution = execution_payload(
        attempted=True,
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
    )

    _atomic_write_text(paths["command"], command_text)
    _atomic_write_text(paths["stdout"], stdout)
    _atomic_write_text(paths["stderr"], stderr)
    _atomic_write_text(paths["exit_code"], f"{exit_code}\n")
    _atomic_write_text(paths["timeout"], f"{str(timed_out).lower()}\n")
    _atomic_write_bytes(paths["compact_script"], script_bytes)
    _atomic_write_json(paths["execution"], execution)

    passed = (
        not timed_out
        and exit_code == 0
        and bool(stdout.strip())
        and not bool(stderr.strip())
        and execution["remote_compact_script_sha256_verified"]
    )
    return {
        "schema_version": 1,
        "status": "PASS" if passed else "STOPPED",
        "reason": (
            "compact containment command completed with the embedded reviewed script"
            if passed
            else "compact containment command failed one or more mandatory safety checks"
        ),
        "step": step_name,
        "execution": execution,
        "artifacts": {key: str(value) for key, value in paths.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bounded-status", "compact-containment"), default="bounded-status")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--step-name", required=True)
    parser.add_argument("--ssh-alias", required=True)
    parser.add_argument("--status-script")
    parser.add_argument("--expected-status-sha256")
    parser.add_argument("--compact-script")
    parser.add_argument("--expected-compact-script-sha256")
    parser.add_argument("--expected-command-sha256", required=True)
    parser.add_argument("--runtime-root")
    parser.add_argument("--state-file-name")
    parser.add_argument("--journal-file-name")
    parser.add_argument("--heartbeat-file-name")
    parser.add_argument("--log-filter")
    parser.add_argument("--journal-lines", type=int)
    parser.add_argument("--log-lines", type=int)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--acknowledgement", required=True)
    return parser


def _require_args(args: argparse.Namespace, names: Sequence[str]) -> None:
    missing = [f"--{name.replace('_', '-')}" for name in names if getattr(args, name) is None]
    if missing:
        raise SystemExit(f"{args.mode} mode requires: {', '.join(missing)}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.acknowledgement != READ_ONLY_ACKNOWLEDGEMENT:
        raise SystemExit("exact read-only collection acknowledgement is required")
    if args.mode == "bounded-status":
        _require_args(
            args,
            [
                "status_script",
                "expected_status_sha256",
                "runtime_root",
                "state_file_name",
                "journal_file_name",
                "heartbeat_file_name",
                "log_filter",
                "journal_lines",
                "log_lines",
            ],
        )
        result = collect_status_bundle(
            output_root=args.output_root,
            step_name=args.step_name,
            ssh_alias=args.ssh_alias,
            status_script_path=args.status_script,
            expected_status_sha256=args.expected_status_sha256,
            expected_command_sha256=args.expected_command_sha256,
            runtime_root=args.runtime_root,
            state_file_name=args.state_file_name,
            journal_file_name=args.journal_file_name,
            heartbeat_file_name=args.heartbeat_file_name,
            log_filter=args.log_filter,
            journal_lines=args.journal_lines,
            log_lines=args.log_lines,
            timeout_seconds=args.timeout_seconds,
        )
    else:
        _require_args(args, ["compact_script", "expected_compact_script_sha256"])
        result = collect_compact_containment_bundle(
            output_root=args.output_root,
            step_name=args.step_name,
            ssh_alias=args.ssh_alias,
            compact_script_path=args.compact_script,
            expected_compact_script_sha256=args.expected_compact_script_sha256,
            expected_command_sha256=args.expected_command_sha256,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
