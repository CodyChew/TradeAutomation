"""Fail-closed offline verification for LPFS operational command evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 2
SAFE_STEP_RE = re.compile(r"^[A-Za-z0-9_.\-/]+$")
SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_PACKET_RESULTS = {"PASS", "STOPPED"}
SAFETY_PROFILE_SCHEMA_VERSION = 1
SUPPORTED_SAFETY_PROFILE_VERSIONS = {1, 2}
STRUCTURED_STEP_CONTRACT_VERSION = 1
BOUNDED_STATUS_STEP_CONTRACT_VERSION = 2
COMPACT_CONTAINMENT_STEP_CONTRACT_VERSION = 3
BOUNDED_STATUS_BUNDLE_KIND = "hash_approved_bounded_status_v1"
COMPACT_CONTAINMENT_BUNDLE_KIND = "hash_approved_compact_containment_v1"
BOUNDED_STATUS_EXECUTION_SCHEMA_VERSION = 1
COMPACT_CONTAINMENT_EXECUTION_SCHEMA_VERSION = 1
BOUNDED_STATUS_SOURCE = "embedded_hash_approved_scriptblock"
COMPACT_CONTAINMENT_SOURCE = "stdin_hash_approved_scriptblock"
COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH = 4000
PINNED_SAFETY_PROFILE_DOCUMENT_SHA256S = {
    "1666fe6bbfe73c4d85746c8bb49d413a0e2011b0979d9ca49308709ff3f2e1a5",
    "61ba3084457e6466cfdd484d568a5c6f2c2f3f44c2103dde204a1e10b0a71f43",
    "532a80cdf727e424fafb09365ecb3c6fe3fa677ab877f27634f7a14f60df849f",
}


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_nonstandard_json_constant,
    )


def _strict_json_file(path: Path) -> Any:
    return _strict_json_loads(path.read_text(encoding="utf-8"))


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise ValueError(f"{label} keys mismatch: missing={missing!r} unknown={unknown!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _safe_step_path(packet_root: Path, step_name: str) -> Path:
    normalized = step_name.replace("\\", "/").strip("/")
    if not normalized or not SAFE_STEP_RE.fullmatch(normalized):
        raise ValueError(f"Invalid packet-relative path: {step_name!r}.")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError(f"Packet-relative path must be canonical: {step_name!r}.")
    root = packet_root.resolve()
    candidate = root.joinpath(*normalized.split("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Path escapes packet root: {step_name!r}.")
    return candidate


def _relative_artifact_path(packet_root: Path, path: Path) -> str:
    return path.resolve().relative_to(packet_root.resolve()).as_posix()


def _artifact_receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _stopped_receipt(
    reason: str,
    *,
    packet_root: str | Path | None = None,
    expected_packet_result: str | None = None,
    failures: Iterable[str] | None = None,
) -> dict[str, Any]:
    failure_list = list(failures or [reason])
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_scope": "post_execution_evidence_only",
        "proves_command_was_safe_to_run": False,
        "pre_execution_read_only_contract_required": True,
        "status": "STOPPED",
        "reason": reason,
        "packet_root": str(packet_root) if packet_root is not None else None,
        "expected_packet_result": expected_packet_result,
        "packet_result": None,
        "failures": failure_list,
        "manifest": None,
        "steps": [],
    }


def verify_manifest(packet_root: str | Path) -> dict[str, Any]:
    root = Path(packet_root)
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256.txt"
    failures: list[str] = []
    files_checked = 0
    bad_payloads: list[str] = []
    declarations: dict[str, dict[str, Any]] = {}
    manifest: dict[str, Any] | None = None
    actual_manifest_hash: str | None = None

    if not root.is_dir():
        failures.append("packet root is not a directory")
    if not manifest_path.is_file():
        failures.append("missing manifest.json")
    if not sidecar_path.is_file():
        failures.append("missing manifest.sha256.txt")
    if failures:
        return {
            "status": "STOPPED",
            "reason": "; ".join(failures),
            "failures": failures,
            "packet_root": str(root),
            "manifest_sha256": actual_manifest_hash,
            "files_checked": files_checked,
            "bad_payloads": bad_payloads,
            "packet_result": None,
            "declared_artifacts": declarations,
        }

    try:
        decoded_manifest = _strict_json_file(manifest_path)
        if not isinstance(decoded_manifest, dict):
            failures.append("manifest.json must contain a JSON object")
        else:
            manifest = decoded_manifest
    except Exception as exc:
        failures.append(f"manifest.json is not valid JSON: {type(exc).__name__}: {exc}")

    try:
        sidecar_text = sidecar_path.read_text(encoding="ascii").strip().lower()
        expected_manifest_hash = sidecar_text.split()[0] if sidecar_text else ""
        if not SHA256_RE.fullmatch(expected_manifest_hash):
            failures.append("manifest.sha256.txt must begin with one valid SHA-256 value")
    except Exception as exc:
        expected_manifest_hash = ""
        failures.append(f"manifest.sha256.txt is unreadable: {type(exc).__name__}: {exc}")

    try:
        actual_manifest_hash = _sha256(manifest_path)
        if expected_manifest_hash != actual_manifest_hash:
            failures.append(
                f"manifest SHA-256 mismatch: expected={expected_manifest_hash!r} actual={actual_manifest_hash!r}"
            )
    except Exception as exc:
        failures.append(f"manifest.json hash could not be calculated: {type(exc).__name__}: {exc}")

    packet_result = None
    if manifest is not None:
        packet_result = manifest.get("result")
        if packet_result not in VALID_PACKET_RESULTS:
            failures.append(f"manifest result must be one of {sorted(VALID_PACKET_RESULTS)}")

        entries = manifest.get("files")
        if not isinstance(entries, list):
            failures.append("manifest files must be a list")
            entries = []

        declared_count = manifest.get("file_count")
        if isinstance(declared_count, bool) or not isinstance(declared_count, int):
            failures.append("manifest file_count must be an integer")
        elif declared_count != len(entries):
            failures.append(f"manifest file_count mismatch: declared={declared_count!r} entries={len(entries)}")

        for index, entry in enumerate(entries):
            label = f"manifest files[{index}]"
            if not isinstance(entry, dict):
                failures.append(f"{label} must be an object")
                bad_payloads.append(f"<non-object entry {index}>")
                continue

            relative = entry.get("path")
            expected_bytes = entry.get("bytes")
            expected_hash = entry.get("sha256")
            entry_valid = True

            if not isinstance(relative, str) or not relative:
                failures.append(f"{label}.path must be a nonempty string")
                entry_valid = False
                normalized_relative = f"<invalid path {index}>"
            else:
                try:
                    path = _safe_step_path(root, relative)
                    normalized_relative = _relative_artifact_path(root, path)
                except (ValueError, OSError) as exc:
                    failures.append(f"{label}.path is invalid: {exc}")
                    entry_valid = False
                    normalized_relative = relative

            if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
                failures.append(f"{label}.bytes must be a nonnegative integer")
                entry_valid = False
            if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash.lower()):
                failures.append(f"{label}.sha256 must be a valid SHA-256 value")
                entry_valid = False

            if normalized_relative in declarations:
                failures.append(f"manifest contains duplicate path: {normalized_relative!r}")
                entry_valid = False

            if not entry_valid:
                bad_payloads.append(normalized_relative)
                continue

            expected_hash = expected_hash.lower()
            declarations[normalized_relative] = {
                "path": normalized_relative,
                "bytes": expected_bytes,
                "sha256": expected_hash,
            }
            if not path.is_file():
                bad_payloads.append(normalized_relative)
                continue
            try:
                actual_bytes = path.stat().st_size
                actual_hash = _sha256(path)
            except Exception as exc:
                failures.append(f"{normalized_relative} could not be read: {type(exc).__name__}: {exc}")
                bad_payloads.append(normalized_relative)
                continue
            files_checked += 1
            if actual_bytes != expected_bytes or actual_hash != expected_hash:
                bad_payloads.append(normalized_relative)

    if bad_payloads:
        failures.append(f"{len(bad_payloads)} payload file(s) failed declaration/hash/size validation")

    return {
        "status": "PASS" if not failures else "STOPPED",
        "reason": "manifest and declared payloads verified" if not failures else "; ".join(failures),
        "failures": failures,
        "packet_root": str(root),
        "manifest_sha256": actual_manifest_hash,
        "files_checked": files_checked,
        "bad_payloads": bad_payloads,
        "packet_result": packet_result,
        "declared_artifacts": declarations,
    }


def _lookup_field(payload: Mapping[str, Any], dotted_field: str) -> tuple[bool, Any]:
    current: Any = payload
    for part in dotted_field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _values_match(field: str, actual: Any, expected: Any) -> tuple[bool, str]:
    if field in {"strategy_orders", "strategy_positions"}:
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False, "exact_inventory_order_independent"
        actual_rows = sorted(json.dumps(item, sort_keys=True, allow_nan=False) for item in actual)
        expected_rows = sorted(json.dumps(item, sort_keys=True, allow_nan=False) for item in expected)
        return actual_rows == expected_rows, "exact_inventory_order_independent"
    return type(actual) is type(expected) and actual == expected, "exact_json_type_and_value"


def verify_command_bundle(
    packet_root: str | Path,
    step_name: str,
    marker: str,
    *,
    expectations: Mapping[str, Any] | None,
    required_expectation_fields: Iterable[str] | None,
    declared_artifacts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    root = Path(packet_root)
    failures: list[str] = []
    receipts: dict[str, Any] = {}
    texts: dict[str, str] = {}
    expectation_results: list[dict[str, Any]] = []

    try:
        base = _safe_step_path(root, step_name)
    except ValueError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STOPPED",
            "reason": str(exc),
            "step": step_name,
            "marker": marker,
            "failures": [str(exc)],
            "artifacts": receipts,
            "expectations": expectation_results,
            "structured_payload": None,
        }

    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
    }

    marker_valid = isinstance(marker, str) and bool(marker)
    if not marker_valid:
        failures.append("structured marker must be a nonempty string")
    if not expectations:
        failures.append("step must declare at least one explicit safety expectation")
    required_fields = list(required_expectation_fields or [])
    if not required_fields:
        failures.append("step must declare mandatory required expectation fields")
    elif len(set(required_fields)) != len(required_fields):
        failures.append("step mandatory required expectation fields contain duplicates")
    elif not expectations or set(required_fields) != set(expectations):
        missing = sorted(set(required_fields) - set(expectations or {}))
        undeclared = sorted(set(expectations or {}) - set(required_fields))
        failures.append(f"step expectation set mismatch: missing={missing!r} undeclared={undeclared!r}")
    if declared_artifacts is None:
        failures.append("manifest declarations are required for command-bundle verification")

    for label, path in paths.items():
        try:
            relative = _relative_artifact_path(root, path)
        except (ValueError, OSError) as exc:
            failures.append(f"invalid {label} artifact path: {exc}")
            continue
        declaration = declared_artifacts.get(relative) if declared_artifacts is not None else None
        if declaration is None:
            failures.append(f"undeclared {label} artifact: {relative}")
        if not path.is_file():
            failures.append(f"missing {label} artifact: {relative}")
            continue
        try:
            receipt = _artifact_receipt(path)
            receipts[label] = receipt
            if declaration is not None and (
                receipt["bytes"] != declaration.get("bytes")
                or receipt["sha256"] != declaration.get("sha256")
            ):
                failures.append(f"{label} artifact no longer matches manifest declaration: {relative}")
            try:
                texts[label] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                texts[label] = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            failures.append(f"unreadable {label} artifact: {type(exc).__name__}: {exc}")

    required_texts = {"command", "stdout", "stderr", "exit_code"}
    if required_texts.issubset(texts):
        if not texts["command"].strip():
            failures.append("command artifact is empty")
        if texts["stderr"].strip():
            failures.append("stderr artifact is not empty")
        try:
            exit_code = int(texts["exit_code"].strip())
        except ValueError:
            exit_code = None
            failures.append(f"exit code is not an integer: {texts['exit_code'].strip()!r}")
        if exit_code is not None and exit_code != 0:
            failures.append(f"exit code is nonzero: {exit_code}")

        nonempty_stdout = [line.strip() for line in texts["stdout"].splitlines() if line.strip()]
        marker_lines = [line for line in nonempty_stdout if marker_valid and line.startswith(marker)]
        if len(nonempty_stdout) != 1:
            failures.append(f"stdout must contain exactly one nonempty structured line; found {len(nonempty_stdout)}")
        if len(marker_lines) != 1:
            failures.append(f"stdout must contain exactly one {marker!r} line; found {len(marker_lines)}")
    else:
        marker_lines = []

    payload: dict[str, Any] | None = None
    if len(marker_lines) == 1:
        try:
            decoded = _strict_json_loads(marker_lines[0][len(marker) :])
            if not isinstance(decoded, dict):
                failures.append("structured marker payload must be a JSON object")
            else:
                payload = decoded
        except Exception as exc:
            failures.append(f"structured marker payload is invalid JSON: {type(exc).__name__}: {exc}")

    if expectations:
        for field, expected in expectations.items():
            field_valid = isinstance(field, str) and SAFE_FIELD_RE.fullmatch(field)
            present, actual = _lookup_field(payload, field) if field_valid and payload is not None else (False, None)
            matched, comparison = (
                _values_match(field, actual, expected) if present else (False, "exact_json_type_and_value")
            )
            expectation_results.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "present": present,
                    "matched": matched,
                    "comparison": comparison,
                }
            )
            if not field_valid:
                failures.append(f"invalid safety expectation field: {field!r}")
            elif not present:
                failures.append(f"safety expectation field is missing: {field!r}")
            elif not matched:
                failures.append(
                    f"safety expectation mismatch for {field!r}: expected={expected!r} actual={actual!r}"
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "STOPPED",
        "reason": (
            "manifest-bound command artifacts and explicit safety expectations verified"
            if not failures
            else "; ".join(failures)
        ),
        "step": step_name,
        "marker": marker,
        "required_expectation_fields": required_fields,
        "failures": failures,
        "artifacts": receipts,
        "expectations": expectation_results,
        "structured_payload": payload,
    }


def verify_bounded_status_bundle(
    packet_root: str | Path,
    step_name: str,
    *,
    expected_command_sha256: str,
    expected_status_implementation_sha256: str,
    required_stdout_substrings: Iterable[str],
    declared_artifacts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    root = Path(packet_root)
    failures: list[str] = []
    receipts: dict[str, Any] = {}
    texts: dict[str, str] = {}
    execution: dict[str, Any] | None = None

    try:
        base = _safe_step_path(root, step_name)
    except ValueError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STOPPED",
            "reason": str(exc),
            "step": step_name,
            "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
            "failures": [str(exc)],
            "artifacts": receipts,
            "execution": None,
        }

    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
        "timeout": base.with_name(base.name + ".timeout.txt"),
        "status_implementation": base.with_name(base.name + ".status_implementation.ps1"),
        "execution": base.with_name(base.name + ".execution.json"),
    }
    expected_hashes = {
        "command": expected_command_sha256,
        "status_implementation": expected_status_implementation_sha256,
    }
    for label, expected_hash in expected_hashes.items():
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            failures.append(f"expected {label} SHA-256 must be valid lowercase hexadecimal")
    required_substrings = list(required_stdout_substrings)
    if not required_substrings or any(not isinstance(value, str) or not value for value in required_substrings):
        failures.append("bounded-status required stdout substrings must be nonempty strings")
    elif len(set(required_substrings)) != len(required_substrings):
        failures.append("bounded-status required stdout substrings must not contain duplicates")
    if declared_artifacts is None:
        failures.append("manifest declarations are required for bounded-status verification")

    for label, path in paths.items():
        try:
            relative = _relative_artifact_path(root, path)
        except (ValueError, OSError) as exc:
            failures.append(f"invalid {label} artifact path: {exc}")
            continue
        declaration = declared_artifacts.get(relative) if declared_artifacts is not None else None
        if declaration is None:
            failures.append(f"undeclared {label} artifact: {relative}")
        if not path.is_file():
            failures.append(f"missing {label} artifact: {relative}")
            continue
        try:
            receipt = _artifact_receipt(path)
            receipts[label] = receipt
            if declaration is not None and (
                receipt["bytes"] != declaration.get("bytes")
                or receipt["sha256"] != declaration.get("sha256")
            ):
                failures.append(f"{label} artifact no longer matches manifest declaration: {relative}")
            if label != "status_implementation":
                try:
                    texts[label] = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    texts[label] = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            failures.append(f"unreadable {label} artifact: {type(exc).__name__}: {exc}")

    for label, expected_hash in expected_hashes.items():
        receipt = receipts.get(label)
        if receipt is not None and receipt.get("sha256") != expected_hash:
            failures.append(
                f"{label} artifact SHA-256 mismatch: expected={expected_hash!r} actual={receipt.get('sha256')!r}"
            )

    command_text = texts.get("command", "")
    stdout_text = texts.get("stdout", "")
    stderr_text = texts.get("stderr", "")
    if not command_text.strip():
        failures.append("command artifact is empty")
    else:
        if "-EncodedCommand" not in command_text:
            failures.append("bounded-status command must execute an encoded reviewed implementation")
        if "Get-LpfsLiveStatus.ps1" in command_text:
            failures.append("bounded-status command must not execute an unverified VPS-resident status script")
    if not stdout_text.strip():
        failures.append("bounded-status stdout artifact is empty")
    for required in required_substrings:
        if required not in stdout_text:
            failures.append(f"bounded-status stdout is missing required substring: {required!r}")
    verification_marker = (
        f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={expected_status_implementation_sha256}"
    )
    verification_marker_count = sum(
        1 for line in stdout_text.splitlines() if line.strip() == verification_marker
    )
    if verification_marker_count != 1:
        failures.append(
            "bounded-status stdout must contain exactly one implementation verification marker; "
            f"found {verification_marker_count}"
        )
    if stderr_text.strip():
        failures.append("stderr artifact is not empty")

    exit_code: int | None = None
    if "exit_code" in texts:
        try:
            exit_code = int(texts["exit_code"].strip())
        except ValueError:
            failures.append(f"exit code is not an integer: {texts['exit_code'].strip()!r}")
        if exit_code is not None and exit_code != 0:
            failures.append(f"exit code is nonzero: {exit_code}")
    timeout_value = texts.get("timeout", "").strip().lower()
    if timeout_value not in {"true", "false"}:
        failures.append(f"timeout artifact must be exactly true or false: {timeout_value!r}")
    elif timeout_value != "false":
        failures.append("bounded-status command timed out")

    if "execution" in texts:
        try:
            decoded_execution = _strict_json_loads(texts["execution"])
            if not isinstance(decoded_execution, dict):
                failures.append("bounded-status execution artifact must contain a JSON object")
            else:
                execution = decoded_execution
                _require_exact_keys(
                    execution,
                    {
                        "bundle_kind",
                        "command_hash_matches_expected",
                        "command_sha256",
                        "execution_attempted",
                        "exit_code",
                        "expected_command_sha256",
                        "remote_status_implementation_sha256_verified",
                        "schema_version",
                        "status_implementation_sha256",
                        "status_implementation_source",
                        "stderr_empty",
                        "stdout_nonempty",
                        "timed_out",
                        "timeout_seconds",
                    },
                    "bounded-status execution artifact",
                )
        except Exception as exc:
            failures.append(f"bounded-status execution artifact is invalid JSON: {type(exc).__name__}: {exc}")

    expected_execution = {
        "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
        "command_hash_matches_expected": True,
        "command_sha256": expected_command_sha256,
        "execution_attempted": True,
        "exit_code": 0,
        "expected_command_sha256": expected_command_sha256,
        "remote_status_implementation_sha256_verified": True,
        "schema_version": BOUNDED_STATUS_EXECUTION_SCHEMA_VERSION,
        "status_implementation_sha256": expected_status_implementation_sha256,
        "status_implementation_source": BOUNDED_STATUS_SOURCE,
        "stderr_empty": True,
        "stdout_nonempty": True,
        "timed_out": False,
    }
    if execution is not None:
        for field, expected in expected_execution.items():
            actual = execution.get(field)
            if type(actual) is not type(expected) or actual != expected:
                failures.append(
                    f"bounded-status execution mismatch for {field!r}: expected={expected!r} actual={actual!r}"
                )
        timeout_seconds = execution.get("timeout_seconds")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            failures.append("bounded-status execution timeout_seconds must be a positive integer")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "STOPPED",
        "reason": (
            "manifest-bound bounded-status command and hash-approved implementation verified"
            if not failures
            else "; ".join(failures)
        ),
        "step": step_name,
        "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
        "failures": failures,
        "artifacts": receipts,
        "execution": execution,
    }


def verify_compact_containment_bundle(
    packet_root: str | Path,
    step_name: str,
    marker: str,
    *,
    expectations: Mapping[str, Any] | None,
    required_expectation_fields: Iterable[str] | None,
    expected_command_sha256: str,
    expected_compact_script_sha256: str,
    declared_artifacts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    root = Path(packet_root)
    failures: list[str] = []
    receipts: dict[str, Any] = {}
    texts: dict[str, str] = {}
    execution: dict[str, Any] | None = None
    expectation_results: list[dict[str, Any]] = []

    try:
        base = _safe_step_path(root, step_name)
    except ValueError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STOPPED",
            "reason": str(exc),
            "step": step_name,
            "bundle_kind": COMPACT_CONTAINMENT_BUNDLE_KIND,
            "marker": marker,
            "failures": [str(exc)],
            "artifacts": receipts,
            "expectations": expectation_results,
            "structured_payload": None,
            "execution": None,
        }

    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
        "timeout": base.with_name(base.name + ".timeout.txt"),
        "compact_script": base.with_name(base.name + ".remote.ps1"),
        "execution": base.with_name(base.name + ".execution.json"),
    }
    expected_hashes = {
        "command": expected_command_sha256,
        "compact_script": expected_compact_script_sha256,
    }
    for label, expected_hash in expected_hashes.items():
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            failures.append(f"expected {label} SHA-256 must be valid lowercase hexadecimal")

    marker_valid = isinstance(marker, str) and bool(marker)
    if not marker_valid:
        failures.append("structured marker must be a nonempty string")
    if not expectations:
        failures.append("step must declare at least one explicit safety expectation")
    required_fields = list(required_expectation_fields or [])
    if not required_fields:
        failures.append("step must declare mandatory required expectation fields")
    elif len(set(required_fields)) != len(required_fields):
        failures.append("step mandatory required expectation fields contain duplicates")
    elif not expectations or set(required_fields) != set(expectations):
        missing = sorted(set(required_fields) - set(expectations or {}))
        undeclared = sorted(set(expectations or {}) - set(required_fields))
        failures.append(f"step expectation set mismatch: missing={missing!r} undeclared={undeclared!r}")
    if declared_artifacts is None:
        failures.append("manifest declarations are required for compact-containment verification")

    for label, path in paths.items():
        try:
            relative = _relative_artifact_path(root, path)
        except (ValueError, OSError) as exc:
            failures.append(f"invalid {label} artifact path: {exc}")
            continue
        declaration = declared_artifacts.get(relative) if declared_artifacts is not None else None
        if declaration is None:
            failures.append(f"undeclared {label} artifact: {relative}")
        if not path.is_file():
            failures.append(f"missing {label} artifact: {relative}")
            continue
        try:
            receipt = _artifact_receipt(path)
            receipts[label] = receipt
            if declaration is not None and (
                receipt["bytes"] != declaration.get("bytes")
                or receipt["sha256"] != declaration.get("sha256")
            ):
                failures.append(f"{label} artifact no longer matches manifest declaration: {relative}")
            try:
                texts[label] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                texts[label] = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            failures.append(f"unreadable {label} artifact: {type(exc).__name__}: {exc}")

    for label, expected_hash in expected_hashes.items():
        receipt = receipts.get(label)
        if receipt is not None and receipt.get("sha256") != expected_hash:
            failures.append(
                f"{label} artifact SHA-256 mismatch: expected={expected_hash!r} actual={receipt.get('sha256')!r}"
            )

    command_text = texts.get("command", "")
    compact_script_text = texts.get("compact_script", "")
    stdout_text = texts.get("stdout", "")
    stderr_text = texts.get("stderr", "")
    if not command_text.strip():
        failures.append("command artifact is empty")
    else:
        if len(command_text) >= COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH:
            failures.append(
                f"compact-containment command length {len(command_text)} exceeds safe threshold "
                f"{COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH}"
            )
        if "Get-LpfsLiveStatus.ps1" in command_text:
            failures.append("compact-containment command must not execute an unverified VPS-resident status script")
        if compact_script_text.strip() and compact_script_text.strip() in command_text:
            failures.append("compact-containment command must not inline the full compact script")
    if not compact_script_text.strip():
        failures.append("compact script artifact is empty")
    if not stdout_text.strip():
        failures.append("compact-containment stdout artifact is empty")
    verification_marker = f"LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={expected_compact_script_sha256}"
    verification_marker_count = sum(
        1 for line in stdout_text.splitlines() if line.strip() == verification_marker
    )
    if verification_marker_count != 1:
        failures.append(
            "compact-containment stdout must contain exactly one script verification marker; "
            f"found {verification_marker_count}"
        )
    if stderr_text.strip():
        failures.append("stderr artifact is not empty")

    exit_code: int | None = None
    if "exit_code" in texts:
        try:
            exit_code = int(texts["exit_code"].strip())
        except ValueError:
            failures.append(f"exit code is not an integer: {texts['exit_code'].strip()!r}")
        if exit_code is not None and exit_code != 0:
            failures.append(f"exit code is nonzero: {exit_code}")
    timeout_value = texts.get("timeout", "").strip().lower()
    if timeout_value not in {"true", "false"}:
        failures.append(f"timeout artifact must be exactly true or false: {timeout_value!r}")
    elif timeout_value != "false":
        failures.append("compact-containment command timed out")

    nonempty_stdout = [line.strip() for line in stdout_text.splitlines() if line.strip()]
    marker_lines = [line for line in nonempty_stdout if marker_valid and line.startswith(marker)]
    if stdout_text and len(nonempty_stdout) != 2:
        failures.append(f"stdout must contain exactly two nonempty compact-containment lines; found {len(nonempty_stdout)}")
    if len(marker_lines) != 1:
        failures.append(f"stdout must contain exactly one {marker!r} line; found {len(marker_lines)}")

    payload: dict[str, Any] | None = None
    if len(marker_lines) == 1:
        try:
            decoded = _strict_json_loads(marker_lines[0][len(marker) :])
            if not isinstance(decoded, dict):
                failures.append("structured marker payload must be a JSON object")
            else:
                payload = decoded
        except Exception as exc:
            failures.append(f"structured marker payload is invalid JSON: {type(exc).__name__}: {exc}")

    if "execution" in texts:
        try:
            decoded_execution = _strict_json_loads(texts["execution"])
            if not isinstance(decoded_execution, dict):
                failures.append("compact-containment execution artifact must contain a JSON object")
            else:
                execution = decoded_execution
                _require_exact_keys(
                    execution,
                    {
                        "bundle_kind",
                        "command_hash_matches_expected",
                        "command_length",
                        "command_length_within_safe_threshold",
                        "command_sha256",
                        "compact_script_hash_matches_expected",
                        "compact_script_sha256",
                        "compact_script_source",
                        "execution_attempted",
                        "exit_code",
                        "expected_command_sha256",
                        "expected_compact_script_sha256",
                        "remote_compact_script_sha256_verified",
                        "schema_version",
                        "stderr_empty",
                        "stdout_nonempty",
                        "timed_out",
                        "timeout_seconds",
                    },
                    "compact-containment execution artifact",
                )
        except Exception as exc:
            failures.append(f"compact-containment execution artifact is invalid JSON: {type(exc).__name__}: {exc}")

    expected_execution = {
        "bundle_kind": COMPACT_CONTAINMENT_BUNDLE_KIND,
        "command_hash_matches_expected": True,
        "command_length": len(command_text),
        "command_length_within_safe_threshold": True,
        "command_sha256": expected_command_sha256,
        "compact_script_hash_matches_expected": True,
        "compact_script_sha256": expected_compact_script_sha256,
        "compact_script_source": COMPACT_CONTAINMENT_SOURCE,
        "execution_attempted": True,
        "exit_code": 0,
        "expected_command_sha256": expected_command_sha256,
        "expected_compact_script_sha256": expected_compact_script_sha256,
        "remote_compact_script_sha256_verified": True,
        "schema_version": COMPACT_CONTAINMENT_EXECUTION_SCHEMA_VERSION,
        "stderr_empty": True,
        "stdout_nonempty": True,
        "timed_out": False,
    }
    if execution is not None:
        for field, expected in expected_execution.items():
            actual = execution.get(field)
            if type(actual) is not type(expected) or actual != expected:
                failures.append(
                    f"compact-containment execution mismatch for {field!r}: "
                    f"expected={expected!r} actual={actual!r}"
                )
        timeout_seconds = execution.get("timeout_seconds")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            failures.append("compact-containment execution timeout_seconds must be a positive integer")

    if expectations:
        for field, expected in expectations.items():
            field_valid = isinstance(field, str) and SAFE_FIELD_RE.fullmatch(field)
            present, actual = _lookup_field(payload, field) if field_valid and payload is not None else (False, None)
            matched, comparison = (
                _values_match(field, actual, expected) if present else (False, "exact_json_type_and_value")
            )
            expectation_results.append(
                {
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                    "present": present,
                    "matched": matched,
                    "comparison": comparison,
                }
            )
            if not field_valid:
                failures.append(f"invalid safety expectation field: {field!r}")
            elif not present:
                failures.append(f"safety expectation field is missing: {field!r}")
            elif not matched:
                failures.append(
                    f"safety expectation mismatch for {field!r}: expected={expected!r} actual={actual!r}"
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "STOPPED",
        "reason": (
            "manifest-bound compact-containment command, script, execution metadata, and expectations verified"
            if not failures
            else "; ".join(failures)
        ),
        "step": step_name,
        "bundle_kind": COMPACT_CONTAINMENT_BUNDLE_KIND,
        "marker": marker,
        "required_expectation_fields": required_fields,
        "failures": failures,
        "artifacts": receipts,
        "expectations": expectation_results,
        "structured_payload": payload,
        "execution": execution,
    }


def _validate_unique_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a nonempty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must contain nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return value


def load_safety_profile(
    profile_path: str | Path,
    profile_id: str,
    *,
    expected_document_sha256: str | None = None,
) -> dict[str, Any]:
    path = Path(profile_path)
    actual_document_sha256 = _sha256(path)
    accepted_hashes = (
        {expected_document_sha256}
        if expected_document_sha256 is not None
        else PINNED_SAFETY_PROFILE_DOCUMENT_SHA256S
    )
    if actual_document_sha256 not in accepted_hashes:
        raise ValueError(
            "safety profile document SHA-256 does not match the pinned reviewed candidate: "
            f"expected_one_of={sorted(accepted_hashes)!r} actual={actual_document_sha256!r}"
        )
    document = _strict_json_file(path)
    if not isinstance(document, dict):
        raise ValueError("safety profile document must be a JSON object")
    _require_exact_keys(document, {"schema_version", "profiles"}, "safety profile document")
    if document.get("schema_version") != SAFETY_PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported safety profile schema_version: {document.get('schema_version')!r}"
        )
    profiles = document.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("safety profile document profiles must be a nonempty object")
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        raise ValueError(f"unknown safety profile: {profile_id!r}")
    profile_version = profile.get("profile_version")
    if profile_version not in SUPPORTED_SAFETY_PROFILE_VERSIONS:
        raise ValueError(f"unsupported safety profile profile_version: {profile.get('profile_version')!r}")
    profile_keys = {"profile_version", "gate", "expected_packet_result", "required_steps", "steps"}
    if profile_version >= 2:
        profile_keys.add("runtime_integrity_steps")
    _require_exact_keys(profile, profile_keys, "safety profile")
    if not isinstance(profile.get("gate"), str) or not profile["gate"]:
        raise ValueError("safety profile gate must be a nonempty string")
    if profile.get("expected_packet_result") not in VALID_PACKET_RESULTS:
        raise ValueError(
            f"safety profile expected_packet_result must be one of {sorted(VALID_PACKET_RESULTS)}"
        )

    required_steps = _validate_unique_string_list(profile.get("required_steps"), "safety profile required_steps")
    steps = profile.get("steps")
    if not isinstance(steps, dict) or not steps:
        raise ValueError("safety profile steps must be a nonempty object")
    if set(required_steps) != set(steps):
        missing = sorted(set(required_steps) - set(steps))
        undeclared = sorted(set(steps) - set(required_steps))
        raise ValueError(
            f"safety profile step set mismatch: missing={missing!r} undeclared={undeclared!r}"
        )

    validated_steps: dict[str, dict[str, Any]] = {}
    for step_name in required_steps:
        normalized = step_name.replace("\\", "/").strip("/")
        if (
            normalized != step_name
            or not SAFE_STEP_RE.fullmatch(normalized)
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise ValueError(f"safety profile contains invalid step name: {step_name!r}")
        step = steps[step_name]
        if not isinstance(step, dict):
            raise ValueError(f"safety profile step {step_name!r} must be an object")
        contract_version = step.get("contract_version")
        if contract_version == STRUCTURED_STEP_CONTRACT_VERSION:
            _require_exact_keys(
                step,
                {"contract_version", "marker", "required_expectation_fields", "expectations"},
                f"safety profile step {step_name!r}",
            )
            marker = step.get("marker")
            if not isinstance(marker, str) or not marker:
                raise ValueError(f"safety profile step {step_name!r} marker must be a nonempty string")
            required_fields = _validate_unique_string_list(
                step.get("required_expectation_fields"),
                f"safety profile step {step_name!r} required_expectation_fields",
            )
            if any(not SAFE_FIELD_RE.fullmatch(field) for field in required_fields):
                raise ValueError(f"safety profile step {step_name!r} contains an invalid expectation field")
            expectations = step.get("expectations")
            if not isinstance(expectations, dict) or not expectations:
                raise ValueError(f"safety profile step {step_name!r} expectations must be a nonempty object")
            if set(required_fields) != set(expectations):
                missing = sorted(set(required_fields) - set(expectations))
                undeclared = sorted(set(expectations) - set(required_fields))
                raise ValueError(
                    f"safety profile step {step_name!r} expectation set mismatch: "
                    f"missing={missing!r} undeclared={undeclared!r}"
                )
            validated_steps[step_name] = {
                "step": step_name,
                "contract_version": contract_version,
                "marker": marker,
                "required_expectation_fields": required_fields,
                "expectations": expectations,
            }
        elif contract_version == BOUNDED_STATUS_STEP_CONTRACT_VERSION:
            _require_exact_keys(
                step,
                {
                    "bundle_kind",
                    "contract_version",
                    "expected_command_sha256",
                    "expected_status_implementation_sha256",
                    "required_stdout_substrings",
                },
                f"safety profile step {step_name!r}",
            )
            if step.get("bundle_kind") != BOUNDED_STATUS_BUNDLE_KIND:
                raise ValueError(
                    f"unsupported safety profile step {step_name!r} bundle_kind: {step.get('bundle_kind')!r}"
                )
            expected_command_sha256 = step.get("expected_command_sha256")
            expected_status_sha256 = step.get("expected_status_implementation_sha256")
            if not isinstance(expected_command_sha256, str) or not SHA256_RE.fullmatch(expected_command_sha256):
                raise ValueError(f"safety profile step {step_name!r} expected_command_sha256 must be valid")
            if not isinstance(expected_status_sha256, str) or not SHA256_RE.fullmatch(expected_status_sha256):
                raise ValueError(
                    f"safety profile step {step_name!r} expected_status_implementation_sha256 must be valid"
                )
            required_stdout_substrings = _validate_unique_string_list(
                step.get("required_stdout_substrings"),
                f"safety profile step {step_name!r} required_stdout_substrings",
            )
            verified_marker = f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={expected_status_sha256}"
            if verified_marker not in required_stdout_substrings:
                raise ValueError(
                    f"safety profile step {step_name!r} must require the exact implementation verification marker"
                )
            validated_steps[step_name] = {
                "step": step_name,
                "contract_version": contract_version,
                "bundle_kind": BOUNDED_STATUS_BUNDLE_KIND,
                "expected_command_sha256": expected_command_sha256,
                "expected_status_implementation_sha256": expected_status_sha256,
                "required_stdout_substrings": required_stdout_substrings,
            }
        elif contract_version == COMPACT_CONTAINMENT_STEP_CONTRACT_VERSION:
            _require_exact_keys(
                step,
                {
                    "bundle_kind",
                    "contract_version",
                    "expected_command_sha256",
                    "expected_compact_script_sha256",
                    "marker",
                    "required_expectation_fields",
                    "expectations",
                },
                f"safety profile step {step_name!r}",
            )
            if step.get("bundle_kind") != COMPACT_CONTAINMENT_BUNDLE_KIND:
                raise ValueError(
                    f"unsupported safety profile step {step_name!r} bundle_kind: {step.get('bundle_kind')!r}"
                )
            expected_command_sha256 = step.get("expected_command_sha256")
            expected_script_sha256 = step.get("expected_compact_script_sha256")
            if not isinstance(expected_command_sha256, str) or not SHA256_RE.fullmatch(expected_command_sha256):
                raise ValueError(f"safety profile step {step_name!r} expected_command_sha256 must be valid")
            if not isinstance(expected_script_sha256, str) or not SHA256_RE.fullmatch(expected_script_sha256):
                raise ValueError(
                    f"safety profile step {step_name!r} expected_compact_script_sha256 must be valid"
                )
            marker = step.get("marker")
            if not isinstance(marker, str) or not marker:
                raise ValueError(f"safety profile step {step_name!r} marker must be a nonempty string")
            required_fields = _validate_unique_string_list(
                step.get("required_expectation_fields"),
                f"safety profile step {step_name!r} required_expectation_fields",
            )
            if any(not SAFE_FIELD_RE.fullmatch(field) for field in required_fields):
                raise ValueError(f"safety profile step {step_name!r} contains an invalid expectation field")
            expectations = step.get("expectations")
            if not isinstance(expectations, dict) or not expectations:
                raise ValueError(f"safety profile step {step_name!r} expectations must be a nonempty object")
            if set(required_fields) != set(expectations):
                missing = sorted(set(required_fields) - set(expectations))
                undeclared = sorted(set(expectations) - set(required_fields))
                raise ValueError(
                    f"safety profile step {step_name!r} expectation set mismatch: "
                    f"missing={missing!r} undeclared={undeclared!r}"
                )
            validated_steps[step_name] = {
                "step": step_name,
                "contract_version": contract_version,
                "bundle_kind": COMPACT_CONTAINMENT_BUNDLE_KIND,
                "expected_command_sha256": expected_command_sha256,
                "expected_compact_script_sha256": expected_script_sha256,
                "marker": marker,
                "required_expectation_fields": required_fields,
                "expectations": expectations,
            }
        else:
            raise ValueError(
                f"unsupported safety profile step {step_name!r} contract_version: "
                f"{contract_version!r}"
            )

    runtime_integrity_steps: list[str] = []
    if profile_version >= 2:
        runtime_integrity_steps = _validate_unique_string_list(
            profile.get("runtime_integrity_steps"),
            "safety profile runtime_integrity_steps",
        )
        for step_name in runtime_integrity_steps:
            if step_name not in validated_steps:
                raise ValueError(f"runtime-integrity step is not required by the profile: {step_name!r}")
            step = validated_steps[step_name]
            if step["contract_version"] not in {
                STRUCTURED_STEP_CONTRACT_VERSION,
                COMPACT_CONTAINMENT_STEP_CONTRACT_VERSION,
            }:
                raise ValueError(f"runtime-integrity step must be a structured containment step: {step_name!r}")
            expectations = step["expectations"]
            if "repo_head" not in expectations:
                raise ValueError(f"runtime-integrity step must require repo_head: {step_name!r}")
            tracked_clean = (
                expectations.get("tracked_worktree_clean") is True
                and expectations.get("tracked_worktree_status") == []
            )
            critical_hashes = expectations.get("critical_runtime_file_hashes")
            valid_critical_hashes = (
                isinstance(critical_hashes, dict)
                and bool(critical_hashes)
                and all(
                    isinstance(relative, str)
                    and relative
                    and isinstance(file_hash, str)
                    and SHA256_RE.fullmatch(file_hash)
                    for relative, file_hash in critical_hashes.items()
                )
            )
            if not tracked_clean and not valid_critical_hashes:
                raise ValueError(
                    f"runtime-integrity step must require tracked_worktree_clean=true or exact critical hashes: "
                    f"{step_name!r}"
                )

    return {
        "profile_id": profile_id,
        "profile_version": profile_version,
        "gate": profile["gate"],
        "expected_packet_result": profile["expected_packet_result"],
        "profile_path": str(path),
        "profile_sha256": actual_document_sha256,
        "runtime_integrity_steps": runtime_integrity_steps,
        "steps": validated_steps,
    }


def _verify_packet_with_profile(
    packet_root: str | Path,
    *,
    safety_profile: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(packet_root)
    failures: list[str] = []
    manifest = verify_manifest(root)
    failures.extend(manifest["failures"])

    expected_packet_result = safety_profile.get("expected_packet_result")
    profile_steps = safety_profile.get("steps")
    if not isinstance(profile_steps, Mapping) or not profile_steps:
        failures.append("validated mandatory safety profile steps are required")
        profile_steps = {}

    step_results: list[dict[str, Any]] = []
    for step_name, spec in profile_steps.items():
        try:
            if spec["contract_version"] == STRUCTURED_STEP_CONTRACT_VERSION:
                result = verify_command_bundle(
                    root,
                    step_name,
                    spec["marker"],
                    expectations=spec["expectations"],
                    required_expectation_fields=spec["required_expectation_fields"],
                    declared_artifacts=manifest["declared_artifacts"],
                )
            elif spec["contract_version"] == BOUNDED_STATUS_STEP_CONTRACT_VERSION:
                result = verify_bounded_status_bundle(
                    root,
                    step_name,
                    expected_command_sha256=spec["expected_command_sha256"],
                    expected_status_implementation_sha256=spec["expected_status_implementation_sha256"],
                    required_stdout_substrings=spec["required_stdout_substrings"],
                    declared_artifacts=manifest["declared_artifacts"],
                )
            elif spec["contract_version"] == COMPACT_CONTAINMENT_STEP_CONTRACT_VERSION:
                result = verify_compact_containment_bundle(
                    root,
                    step_name,
                    spec["marker"],
                    expectations=spec["expectations"],
                    required_expectation_fields=spec["required_expectation_fields"],
                    expected_command_sha256=spec["expected_command_sha256"],
                    expected_compact_script_sha256=spec["expected_compact_script_sha256"],
                    declared_artifacts=manifest["declared_artifacts"],
                )
            else:
                raise ValueError(f"unsupported validated step contract version: {spec['contract_version']!r}")
        except Exception as exc:
            result = {
                "schema_version": SCHEMA_VERSION,
                "status": "STOPPED",
                "reason": f"invalid mandatory safety profile step: {type(exc).__name__}: {exc}",
                "step": step_name,
                "marker": None,
                "failures": [f"invalid mandatory safety profile step: {type(exc).__name__}: {exc}"],
                "artifacts": {},
                "expectations": [],
                "structured_payload": None,
            }
        step_results.append(result)
        failures.extend(f"{result['step']}: {failure}" for failure in result["failures"])

    packet_result = None
    summary_path = root / "validation_summary.json"
    if expected_packet_result in VALID_PACKET_RESULTS:
        if manifest.get("packet_result") != expected_packet_result:
            failures.append(
                "manifest result mismatch: "
                f"expected={expected_packet_result!r} actual={manifest.get('packet_result')!r}"
            )
        summary_relative = "validation_summary.json"
        declaration = manifest["declared_artifacts"].get(summary_relative)
        if declaration is None:
            failures.append("validation_summary.json is not declared by the packet manifest")
        if not summary_path.is_file():
            failures.append("missing validation_summary.json required for expected packet result check")
        else:
            try:
                summary_receipt = _artifact_receipt(summary_path)
                if declaration is not None and (
                    summary_receipt["bytes"] != declaration.get("bytes")
                    or summary_receipt["sha256"] != declaration.get("sha256")
                ):
                    failures.append("validation_summary.json no longer matches manifest declaration")
                summary = _strict_json_file(summary_path)
                if not isinstance(summary, dict):
                    failures.append("validation_summary.json must contain a JSON object")
                else:
                    packet_result = summary.get("result")
                    if packet_result not in VALID_PACKET_RESULTS:
                        failures.append(
                            f"validation_summary result must be one of {sorted(VALID_PACKET_RESULTS)}"
                        )
                    elif packet_result != expected_packet_result:
                        failures.append(
                            f"validation_summary result mismatch: "
                            f"expected={expected_packet_result!r} actual={packet_result!r}"
                        )
            except Exception as exc:
                failures.append(f"validation_summary.json is invalid: {type(exc).__name__}: {exc}")

    return {
        "schema_version": SCHEMA_VERSION,
        "proof_scope": "post_execution_evidence_only",
        "proves_command_was_safe_to_run": False,
        "pre_execution_read_only_contract_required": True,
        "status": "PASS" if not failures else "STOPPED",
        "reason": (
            "packet manifest, mandatory safety profile, post-execution evidence, and expected result verified"
            if not failures
            else "; ".join(failures)
        ),
        "packet_root": str(root),
        "expected_packet_result": expected_packet_result,
        "packet_result": packet_result,
        "failures": failures,
        "manifest": manifest,
        "safety_profile": {
            "profile_id": safety_profile.get("profile_id"),
            "profile_version": safety_profile.get("profile_version"),
            "gate": safety_profile.get("gate"),
            "profile_path": safety_profile.get("profile_path"),
            "profile_sha256": safety_profile.get("profile_sha256"),
            "runtime_integrity_steps": safety_profile.get("runtime_integrity_steps", []),
        },
        "steps": step_results,
    }


def verify_packet(
    packet_root: str | Path,
    *,
    safety_profile_path: str | Path,
    profile_id: str,
    expected_profile_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        safety_profile = load_safety_profile(
            safety_profile_path,
            profile_id,
            expected_document_sha256=expected_profile_sha256,
        )
    except Exception as exc:
        result = _stopped_receipt(
            f"mandatory safety profile is invalid: {type(exc).__name__}: {exc}",
            packet_root=packet_root,
            failures=[f"mandatory safety profile is invalid: {type(exc).__name__}: {exc}"],
        )
        result["safety_profile"] = {
            "profile_id": profile_id,
            "profile_path": str(safety_profile_path),
        }
        return result
    return _verify_packet_with_profile(packet_root, safety_profile=safety_profile)


def _option_hint(argv: list[str], option: str) -> Path | None:
    for index, value in enumerate(argv):
        if value == option and index + 1 < len(argv):
            return Path(argv[index + 1])
        if value.startswith(option + "="):
            return Path(value.split("=", 1)[1])
    return None


def _fallback_receipt_path() -> Path:
    return Path(tempfile.gettempdir()) / f"lpfs_structured_verifier_stopped_{os.getpid()}.json"


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_parent = parent.resolve()
    except OSError:
        return False
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def _write_and_print_receipt(result: dict[str, Any], output_path: Path) -> int:
    result["receipt_path"] = str(output_path)
    try:
        _atomic_write_json(output_path, result)
    except Exception as exc:
        result["status"] = "STOPPED"
        result["failures"].append(f"receipt write failed: {type(exc).__name__}: {exc}")
        result["reason"] = "; ".join(result["failures"])
        fallback_path = _fallback_receipt_path()
        result["receipt_path"] = str(fallback_path)
        try:
            _atomic_write_json(fallback_path, result)
        except Exception as fallback_exc:
            result["failures"].append(
                f"fallback receipt write failed: {type(fallback_exc).__name__}: {fallback_exc}"
            )
            result["reason"] = "; ".join(result["failures"])
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == "PASS" else 2


def main(argv: list[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    packet_hint = _option_hint(cli_args, "--packet")
    output_path = _option_hint(cli_args, "--output") or _fallback_receipt_path()
    if packet_hint is not None and _path_is_within(output_path, packet_hint):
        output_path = _fallback_receipt_path()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, help="Offline packet directory to verify.")
    parser.add_argument("--safety-profile", required=True, help="Reviewed versioned safety-profile JSON path.")
    parser.add_argument("--profile-id", required=True, help="Mandatory safety profile identifier.")
    parser.add_argument("--output", required=True, help="Atomic JSON receipt path outside the immutable packet.")

    try:
        args = parser.parse_args(cli_args)
        output_path = Path(args.output)
        if _path_is_within(output_path, Path(args.packet)):
            output_path = _fallback_receipt_path()
            raise ValueError("--output must be outside the immutable packet root")
        result = verify_packet(
            args.packet,
            safety_profile_path=args.safety_profile,
            profile_id=args.profile_id,
        )
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        result = _stopped_receipt(
            "malformed verifier invocation",
            failures=["argument parsing failed; see preserved invocation stderr"],
        )
    except Exception as exc:
        result = _stopped_receipt(
            f"malformed verifier input: {type(exc).__name__}: {exc}",
            failures=[f"malformed verifier input: {type(exc).__name__}: {exc}"],
        )
    return _write_and_print_receipt(result, output_path)


if __name__ == "__main__":
    raise SystemExit(main())
