"""Fail-closed offline verification for LPFS operational command evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable


SCHEMA_VERSION = 1
SAFE_STEP_RE = re.compile(r"^[A-Za-z0-9_.\-/]+$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _safe_step_path(packet_root: Path, step_name: str) -> Path:
    normalized = step_name.replace("\\", "/").strip("/")
    if not normalized or not SAFE_STEP_RE.fullmatch(normalized):
        raise ValueError(f"Invalid step name: {step_name!r}.")
    candidate = packet_root.joinpath(*normalized.split("/"))
    if candidate.resolve().parent != packet_root.resolve() and packet_root.resolve() not in candidate.resolve().parents:
        raise ValueError(f"Step escapes packet root: {step_name!r}.")
    return candidate


def _artifact_receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def verify_manifest(packet_root: str | Path) -> dict[str, Any]:
    root = Path(packet_root)
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256.txt"
    failures: list[str] = []
    files_checked = 0
    bad_payloads: list[str] = []
    manifest: dict[str, Any] | None = None

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
            "files_checked": files_checked,
            "bad_payloads": bad_payloads,
            "packet_result": None,
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append(f"manifest.json is not valid JSON: {type(exc).__name__}: {exc}")
    try:
        expected_manifest_hash = sidecar_path.read_text(encoding="ascii").strip().lower()
    except Exception as exc:
        expected_manifest_hash = ""
        failures.append(f"manifest.sha256.txt is unreadable: {type(exc).__name__}: {exc}")

    actual_manifest_hash = _sha256(manifest_path)
    if expected_manifest_hash != actual_manifest_hash:
        failures.append(
            f"manifest SHA-256 mismatch: expected={expected_manifest_hash!r} actual={actual_manifest_hash!r}"
        )

    if isinstance(manifest, dict):
        entries = manifest.get("files")
        if not isinstance(entries, list):
            failures.append("manifest files must be a list")
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                bad_payloads.append("<non-object manifest entry>")
                continue
            relative = str(entry.get("path") or "")
            try:
                path = _safe_step_path(root, relative)
            except ValueError:
                bad_payloads.append(relative or "<missing path>")
                continue
            if not path.is_file():
                bad_payloads.append(relative)
                continue
            files_checked += 1
            expected_bytes = entry.get("bytes")
            expected_hash = str(entry.get("sha256") or "").lower()
            if path.stat().st_size != expected_bytes or _sha256(path) != expected_hash:
                bad_payloads.append(relative)
        declared_count = manifest.get("file_count")
        if declared_count is not None and int(declared_count) != len(entries):
            failures.append(f"manifest file_count mismatch: declared={declared_count!r} entries={len(entries)}")
    if bad_payloads:
        failures.append(f"{len(bad_payloads)} payload file(s) failed hash/size validation")

    return {
        "status": "PASS" if not failures else "STOPPED",
        "reason": "manifest and declared payloads verified" if not failures else "; ".join(failures),
        "failures": failures,
        "packet_root": str(root),
        "manifest_sha256": actual_manifest_hash,
        "files_checked": files_checked,
        "bad_payloads": bad_payloads,
        "packet_result": manifest.get("result") if isinstance(manifest, dict) else None,
    }


def verify_command_bundle(packet_root: str | Path, step_name: str, marker: str) -> dict[str, Any]:
    root = Path(packet_root)
    base = _safe_step_path(root, step_name)
    paths = {
        "command": base.with_name(base.name + ".command.txt"),
        "stdout": base.with_name(base.name + ".stdout.txt"),
        "stderr": base.with_name(base.name + ".stderr.txt"),
        "exit_code": base.with_name(base.name + ".exit_code.txt"),
    }
    failures: list[str] = []
    receipts: dict[str, Any] = {}
    texts: dict[str, str] = {}

    for label, path in paths.items():
        if not path.is_file():
            failures.append(f"missing {label} artifact: {path.name}")
            continue
        receipts[label] = _artifact_receipt(path)
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            texts[label] = path.read_text(encoding="utf-8-sig")
        except Exception as exc:
            failures.append(f"unreadable {label} artifact: {type(exc).__name__}: {exc}")

    if failures:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "STOPPED",
            "reason": "; ".join(failures),
            "step": step_name,
            "marker": marker,
            "failures": failures,
            "artifacts": receipts,
            "structured_payload": None,
        }

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
    marker_lines = [line for line in nonempty_stdout if line.startswith(marker)]
    if len(nonempty_stdout) != 1:
        failures.append(f"stdout must contain exactly one nonempty structured line; found {len(nonempty_stdout)}")
    if len(marker_lines) != 1:
        failures.append(f"stdout must contain exactly one {marker!r} line; found {len(marker_lines)}")

    payload: dict[str, Any] | None = None
    if len(marker_lines) == 1:
        try:
            decoded = json.loads(marker_lines[0][len(marker) :])
            if not isinstance(decoded, dict):
                failures.append("structured marker payload must be a JSON object")
            else:
                payload = decoded
        except Exception as exc:
            failures.append(f"structured marker payload is invalid JSON: {type(exc).__name__}: {exc}")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "STOPPED",
        "reason": "all command artifacts and structured output verified" if not failures else "; ".join(failures),
        "step": step_name,
        "marker": marker,
        "failures": failures,
        "artifacts": receipts,
        "structured_payload": payload,
    }


def verify_packet(
    packet_root: str | Path,
    steps: Iterable[tuple[str, str]],
    *,
    expected_packet_result: str | None = None,
) -> dict[str, Any]:
    root = Path(packet_root)
    manifest = verify_manifest(root)
    step_results = [verify_command_bundle(root, step_name, marker) for step_name, marker in steps]
    failures = list(manifest["failures"])
    for result in step_results:
        failures.extend(f"{result['step']}: {failure}" for failure in result["failures"])

    packet_result = None
    summary_path = root / "validation_summary.json"
    if expected_packet_result is not None:
        if manifest.get("packet_result") != expected_packet_result:
            failures.append(
                "manifest result mismatch: "
                f"expected={expected_packet_result!r} actual={manifest.get('packet_result')!r}"
            )
        if not summary_path.is_file():
            failures.append("missing validation_summary.json required for expected packet result check")
        else:
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                packet_result = summary.get("result")
                if packet_result != expected_packet_result:
                    failures.append(
                        f"validation_summary result mismatch: expected={expected_packet_result!r} actual={packet_result!r}"
                    )
            except Exception as exc:
                failures.append(f"validation_summary.json is invalid: {type(exc).__name__}: {exc}")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "STOPPED",
        "reason": "packet manifest, command bundles, and expected result verified" if not failures else "; ".join(failures),
        "packet_root": str(root),
        "expected_packet_result": expected_packet_result,
        "packet_result": packet_result,
        "failures": failures,
        "manifest": manifest,
        "steps": step_results,
    }


def _parse_step(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--step must be STEP=MARKER")
    step, marker = value.split("=", 1)
    if not step.strip() or not marker.strip():
        raise argparse.ArgumentTypeError("--step must include a nonempty step and marker")
    return step.strip(), marker.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, help="Offline packet directory to verify.")
    parser.add_argument("--step", action="append", type=_parse_step, default=[], help="Repeatable STEP=MARKER check.")
    parser.add_argument("--expected-packet-result", choices=("PASS", "STOPPED"))
    parser.add_argument("--output", help="Optional atomic JSON receipt path.")
    args = parser.parse_args()

    result = verify_packet(
        args.packet,
        args.step,
        expected_packet_result=args.expected_packet_result,
    )
    if args.output:
        _atomic_write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
