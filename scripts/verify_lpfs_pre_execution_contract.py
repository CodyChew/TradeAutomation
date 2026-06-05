"""Verify staged LPFS read-only commands against separately reviewed hashes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from verify_lpfs_structured_command import (
    SAFE_STEP_RE,
    SHA256_RE,
    _artifact_receipt,
    _atomic_write_json,
    _option_hint,
    _path_is_within,
    _require_exact_keys,
    _safe_step_path,
    _sha256,
    _strict_json_file,
    _validate_unique_string_list,
)


SCHEMA_VERSION = 1
CONTRACT_SCHEMA_VERSION = 1
CONTRACT_VERSION = 1
EXECUTABLE_SUFFIXES = {".bat", ".cmd", ".com", ".exe", ".js", ".ps1", ".psm1", ".py", ".sh", ".vbs"}
PINNED_READ_ONLY_CONTRACT_DOCUMENT_SHA256S = {
    "947105e7a50c46b582f7f0ed336b6a602c38d7a931b9cbc4d1f5d7f4ed72ba10",
    "1a1bbd812fd36ad8627abba1f9591166b27d64cc3b222794ad5ff356f9cfb435",
}


def _fallback_receipt_path() -> Path:
    return Path(tempfile.gettempdir()) / f"lpfs_pre_execution_contract_stopped_{os.getpid()}.json"


def load_read_only_contract(
    contract_path: str | Path,
    contract_id: str,
    *,
    expected_document_sha256: str | None = None,
) -> dict[str, Any]:
    path = Path(contract_path)
    actual_document_sha256 = _sha256(path)
    accepted_hashes = (
        {expected_document_sha256}
        if expected_document_sha256 is not None
        else PINNED_READ_ONLY_CONTRACT_DOCUMENT_SHA256S
    )
    if actual_document_sha256 not in accepted_hashes:
        raise ValueError(
            "read-only contract document SHA-256 does not match the pinned reviewed candidate: "
            f"expected_one_of={sorted(accepted_hashes)!r} actual={actual_document_sha256!r}"
        )
    document = _strict_json_file(path)
    if not isinstance(document, dict):
        raise ValueError("read-only contract document must be a JSON object")
    _require_exact_keys(document, {"schema_version", "contracts"}, "read-only contract document")
    if document.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise ValueError(f"unsupported read-only contract schema_version: {document.get('schema_version')!r}")
    contracts = document.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise ValueError("read-only contract document contracts must be a nonempty object")
    contract = contracts.get(contract_id)
    if not isinstance(contract, dict):
        raise ValueError(f"unknown read-only contract: {contract_id!r}")
    _require_exact_keys(
        contract,
        {"contract_version", "gate", "required_artifacts", "artifacts"},
        "read-only contract",
    )
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"unsupported read-only contract contract_version: {contract.get('contract_version')!r}")
    if not isinstance(contract.get("gate"), str) or not contract["gate"]:
        raise ValueError("read-only contract gate must be a nonempty string")
    required = _validate_unique_string_list(contract.get("required_artifacts"), "read-only required_artifacts")
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("read-only contract artifacts must be a nonempty object")
    if set(required) != set(artifacts):
        missing = sorted(set(required) - set(artifacts))
        undeclared = sorted(set(artifacts) - set(required))
        raise ValueError(f"read-only artifact set mismatch: missing={missing!r} undeclared={undeclared!r}")

    validated: dict[str, dict[str, Any]] = {}
    for relative in required:
        normalized = relative.replace("\\", "/").strip("/")
        if (
            normalized != relative
            or not SAFE_STEP_RE.fullmatch(normalized)
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise ValueError(f"read-only contract contains invalid artifact path: {relative!r}")
        declaration = artifacts[relative]
        if not isinstance(declaration, dict):
            raise ValueError(f"read-only artifact {relative!r} declaration must be an object")
        _require_exact_keys(declaration, {"bytes", "sha256"}, f"read-only artifact {relative!r}")
        expected_bytes = declaration.get("bytes")
        expected_hash = declaration.get("sha256")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ValueError(f"read-only artifact {relative!r} bytes must be a nonnegative integer")
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash.lower()):
            raise ValueError(f"read-only artifact {relative!r} sha256 must be valid")
        validated[relative] = {"bytes": expected_bytes, "sha256": expected_hash.lower()}

    return {
        "contract_id": contract_id,
        "contract_version": contract["contract_version"],
        "gate": contract["gate"],
        "contract_path": str(path),
        "contract_sha256": actual_document_sha256,
        "artifacts": validated,
    }


def _executable_like_artifacts(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.endswith(".command.txt") or path.suffix.lower() in EXECUTABLE_SUFFIXES:
            result.add(relative)
    return result


def verify_pre_execution_contract(artifact_root: str | Path, contract: dict[str, Any]) -> dict[str, Any]:
    root = Path(artifact_root)
    failures: list[str] = []
    receipts: dict[str, Any] = {}
    declarations = contract.get("artifacts")
    if not root.is_dir():
        failures.append("staged artifact root is not a directory")
    if not isinstance(declarations, dict) or not declarations:
        failures.append("validated read-only contract artifacts are required")
        declarations = {}

    if root.is_dir():
        actual_executable_like = _executable_like_artifacts(root)
        if actual_executable_like != set(declarations):
            missing = sorted(set(declarations) - actual_executable_like)
            unapproved = sorted(actual_executable_like - set(declarations))
            failures.append(
                f"staged executable artifact set mismatch: missing={missing!r} unapproved={unapproved!r}"
            )

    for relative, declaration in declarations.items():
        try:
            path = _safe_step_path(root, relative)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if not path.is_file():
            failures.append(f"missing staged read-only artifact: {relative}")
            continue
        try:
            receipt = _artifact_receipt(path)
        except Exception as exc:
            failures.append(f"unreadable staged read-only artifact {relative!r}: {type(exc).__name__}: {exc}")
            continue
        receipts[relative] = receipt
        if receipt["bytes"] != declaration["bytes"] or receipt["sha256"] != declaration["sha256"]:
            failures.append(f"staged read-only artifact hash/size mismatch: {relative}")

    return {
        "schema_version": SCHEMA_VERSION,
        "proof_scope": "pre_execution_reviewed_read_only_hash_match",
        "status": "PASS" if not failures else "STOPPED",
        "reason": (
            "all staged commands and scripts match the separately reviewed read-only hash contract"
            if not failures
            else "; ".join(failures)
        ),
        "approved_read_only_hashes_match": not failures,
        "authorizes_execution": False,
        "does_not_prove_post_execution_behavior": True,
        "artifact_root": str(root),
        "failures": failures,
        "contract": {
            "contract_id": contract.get("contract_id"),
            "contract_version": contract.get("contract_version"),
            "gate": contract.get("gate"),
            "contract_path": contract.get("contract_path"),
            "contract_sha256": contract.get("contract_sha256"),
        },
        "artifacts": receipts,
    }


def _stopped_receipt(reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_scope": "pre_execution_reviewed_read_only_hash_match",
        "status": "STOPPED",
        "reason": reason,
        "approved_read_only_hashes_match": False,
        "authorizes_execution": False,
        "does_not_prove_post_execution_behavior": True,
        "artifact_root": None,
        "failures": [reason],
        "contract": None,
        "artifacts": {},
    }


def _write_and_print_receipt(result: dict[str, Any], output_path: Path) -> int:
    result["receipt_path"] = str(output_path)
    try:
        _atomic_write_json(output_path, result)
    except Exception as exc:
        result["status"] = "STOPPED"
        result["approved_read_only_hashes_match"] = False
        result["failures"].append(f"receipt write failed: {type(exc).__name__}: {exc}")
        result["reason"] = "; ".join(result["failures"])
        output_path = _fallback_receipt_path()
        result["receipt_path"] = str(output_path)
        _atomic_write_json(output_path, result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == "PASS" else 2


def main(argv: list[str] | None = None) -> int:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    root_hint = _option_hint(cli_args, "--artifact-root")
    output_path = _option_hint(cli_args, "--output") or _fallback_receipt_path()
    if root_hint is not None and _path_is_within(output_path, root_hint):
        output_path = _fallback_receipt_path()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, help="Local directory containing staged planned files.")
    parser.add_argument("--contract-file", required=True, help="Separately reviewed read-only contract JSON.")
    parser.add_argument("--contract-id", required=True, help="Read-only contract identifier.")
    parser.add_argument("--output", required=True, help="Atomic receipt path outside the staged artifact root.")
    try:
        args = parser.parse_args(cli_args)
        output_path = Path(args.output)
        if _path_is_within(output_path, Path(args.artifact_root)):
            output_path = _fallback_receipt_path()
            raise ValueError("--output must be outside the staged artifact root")
        contract = load_read_only_contract(args.contract_file, args.contract_id)
        result = verify_pre_execution_contract(args.artifact_root, contract)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        result = _stopped_receipt("malformed pre-execution verifier invocation")
    except Exception as exc:
        result = _stopped_receipt(f"malformed pre-execution contract input: {type(exc).__name__}: {exc}")
    return _write_and_print_receipt(result, output_path)


if __name__ == "__main__":
    raise SystemExit(main())
