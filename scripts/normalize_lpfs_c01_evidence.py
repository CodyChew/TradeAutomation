"""Normalize allowlisted legacy LPFS journal timestamps without mutating source evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any


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

from lp_force_strike_strategy_lab.timestamp_semantics import (  # noqa: E402
    LEGACY_HELSINKI_RELOCALIZED_V1,
    MT5_EPOCH_UTC_V2,
    SUPPORTED_TIMESTAMP_SEMANTICS,
    canonical_signal_key,
    mt5_epoch_to_utc,
    normalize_recorded_timestamp,
)


SCHEMA_VERSION = 2
AFFECTED_TIMESTAMP_FIELDS = {
    "broker_backstop_expiration_utc",
    "broker_backstop_expiration_time_utc",
    "close_time_utc",
    "closed_utc",
    "expiration_utc",
    "expiration_time_utc",
    "first_expired_bar_time_utc",
    "first_touch_time_utc",
    "fs_signal_time_utc",
    "last_seen_close_time_utc",
    "latest_closed_candle_time_utc",
    "lp_break_time_utc",
    "market_time_utc",
    "new_broker_backstop_expiration_utc",
    "old_expiration_utc",
    "opened_time_utc",
    "opened_utc",
    "signal_closed_time_utc",
    "signal_time_utc",
    "stop_touched_time_utc",
    "target_touched_time_utc",
}
UNAFFECTED_TIMESTAMP_FIELDS = {
    "boot_time_utc",
    "collected_at_utc",
    "detected_at_utc",
    "occurred_at_utc",
    "placed_time_utc",
    "restart_event_time_utc",
}
SIGNAL_KEY_PATTERN = re.compile(
    r"lpfs:[^:]+:[^:]+:[^:]+:[^:]+:[^:]+:"
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


class C01NormalizationError(ValueError):
    """Raised when historical evidence cannot be normalized without guessing."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _get_path(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _set_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    target: Any = payload
    keys = dotted_path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value


def _leaf_paths(payload: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            paths.extend(_leaf_paths(value, path))
        else:
            paths.append(path)
    return paths


def _parent_path(path: str) -> str:
    return path.rsplit(".", 1)[0] if "." in path else ""


def _child_path(parent: str, child: str) -> str:
    return f"{parent}.{child}" if parent else child


def _timestamp_semantics(payload: dict[str, Any], path: str) -> str:
    parent = _parent_path(path)
    field = path.rsplit(".", 1)[-1]
    specific = field.removesuffix("_utc") + "_timestamp_semantics_version"
    candidates = [
        _child_path(parent, specific),
        _child_path(parent, "timestamp_semantics_version"),
        "diagnostics.timestamp_semantics_version",
        "notification_event.fields.diagnostics.timestamp_semantics_version",
        "timestamp_semantics_version",
    ]
    for candidate in candidates:
        value = _get_path(payload, candidate)
        if value in (None, ""):
            continue
        semantics = str(value)
        if semantics not in SUPPORTED_TIMESTAMP_SEMANTICS:
            raise C01NormalizationError(f"{path}: unsupported timestamp semantics {semantics!r}.")
        return semantics
    return LEGACY_HELSINKI_RELOCALIZED_V1


def _raw_epoch_utc(payload: dict[str, Any], path: str) -> tuple[str | None, str | None]:
    parent = _parent_path(path)
    field = path.rsplit(".", 1)[-1]
    stem = field.removesuffix("_utc")
    for suffix, unit in (("raw_mt5_time_msc", "ms"), ("raw_mt5_time", "s")):
        for candidate in (_child_path(parent, f"{stem}_{suffix}"), _child_path(parent, suffix)):
            raw = _get_path(payload, candidate)
            if raw in (None, "", 0):
                continue
            timestamp = mt5_epoch_to_utc(raw, unit=unit)
            return (None if timestamp is None else timestamp.isoformat(), candidate)
    return None, None


def _normalize_timestamp_path(
    payload: dict[str, Any],
    path: str,
    *,
    broker_timezone: str,
    changes: list[dict[str, str]],
) -> None:
    raw = _get_path(payload, path)
    if raw in (None, ""):
        return
    raw_epoch_utc, raw_epoch_path = _raw_epoch_utc(payload, path)
    semantics = _timestamp_semantics(payload, path)
    if raw_epoch_utc is not None:
        canonical = raw_epoch_utc
        source = str(raw_epoch_path)
    elif semantics == MT5_EPOCH_UTC_V2:
        canonical = normalize_recorded_timestamp(raw, MT5_EPOCH_UTC_V2).isoformat()
        source = MT5_EPOCH_UTC_V2
    else:
        canonical = normalize_recorded_timestamp(raw, semantics, broker_timezone=broker_timezone).isoformat()
        source = semantics
    if str(raw) == canonical:
        return
    _set_path(payload, path, canonical)
    changes.append({"path": path, "raw": str(raw), "canonical_utc": canonical, "source": source})


def _normalize_signal_key(raw: str, semantics: str, *, broker_timezone: str) -> str:
    return canonical_signal_key(str(raw), semantics, broker_timezone=broker_timezone)


def _normalize_embedded_signal_keys(raw: str, semantics: str, *, broker_timezone: str) -> str:
    matches = list(SIGNAL_KEY_PATTERN.finditer(str(raw)))
    if not matches:
        raise C01NormalizationError(f"Malformed LPFS embedded event_key {raw!r}.")
    return SIGNAL_KEY_PATTERN.sub(
        lambda match: _normalize_signal_key(match.group(0), semantics, broker_timezone=broker_timezone),
        str(raw),
    )


def _normalize_trade_key(raw: str, semantics: str, *, broker_timezone: str) -> str:
    parts = str(raw).split("|", 5)
    if len(parts) != 6 or not parts[-1]:
        raise C01NormalizationError(f"Malformed LPFS diagnostic trade_key {raw!r}.")
    parts[-1] = normalize_recorded_timestamp(parts[-1], semantics, broker_timezone=broker_timezone).isoformat()
    return "|".join(parts)


def normalize_row(row: dict[str, Any], *, broker_timezone: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one immutable normalized view and its explicit provenance record."""

    normalized = json.loads(json.dumps(row))
    changes: list[dict[str, str]] = []
    warnings: list[str] = []
    leaf_paths = sorted(_leaf_paths(normalized))
    for path in leaf_paths:
        field = path.rsplit(".", 1)[-1]
        if field in AFFECTED_TIMESTAMP_FIELDS:
            _normalize_timestamp_path(normalized, path, broker_timezone=broker_timezone, changes=changes)
        elif field.endswith("_utc") and field not in UNAFFECTED_TIMESTAMP_FIELDS:
            warnings.append(f"{path}: unresolved unsupported timestamp-bearing path")
    for path in leaf_paths:
        field = path.rsplit(".", 1)[-1]
        raw = _get_path(normalized, path)
        if raw in (None, ""):
            continue
        if field == "signal_key":
            semantics = _timestamp_semantics(normalized, path)
            canonical = _normalize_signal_key(str(raw), semantics, broker_timezone=broker_timezone)
        elif field == "trade_key":
            semantics = _timestamp_semantics(normalized, path)
            canonical = _normalize_trade_key(str(raw), semantics, broker_timezone=broker_timezone)
        elif field == "event_key" and "lpfs:" in str(raw):
            semantics = _timestamp_semantics(normalized, path)
            canonical = _normalize_embedded_signal_keys(str(raw), semantics, broker_timezone=broker_timezone)
        else:
            continue
        if str(raw) == canonical:
            continue
        _set_path(normalized, path, canonical)
        changes.append({"path": path, "raw": str(raw), "canonical_utc": canonical, "source": semantics})
    provenance = {
        "source_timestamp_semantics_version": "mixed_per_field",
        "normalized_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
        "changes": changes,
        "unresolved_warnings": warnings,
    }
    normalized["c01_normalization"] = provenance
    return normalized, provenance


def normalize_journal(source: Path, output_root: Path, *, broker_timezone: str) -> Path:
    """Publish a normalized packet beside a manifest, leaving the source untouched."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    final_dir = output_root / stamp
    staging_dir = output_root / f".{stamp}.{os.getpid()}.tmp"
    staging_dir.mkdir(parents=True)
    try:
        normalized_lines: list[str] = []
        warning_count = 0
        unresolved_warning_inventory: dict[str, int] = {}
        row_count = 0
        for line_number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {source}:{line_number}: {exc}") from exc
            normalized, provenance = normalize_row(row, broker_timezone=broker_timezone)
            warning_count += len(provenance["unresolved_warnings"])
            for warning in provenance["unresolved_warnings"]:
                unresolved_warning_inventory[warning] = unresolved_warning_inventory.get(warning, 0) + 1
            row_count += 1
            normalized_lines.append(json.dumps(normalized, sort_keys=True, default=str))
        normalized_path = staging_dir / "normalized_journal.jsonl"
        _atomic_write(normalized_path, "\n".join(normalized_lines) + ("\n" if normalized_lines else ""))
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "source_path": str(source.resolve()),
            "source_sha256": _sha256(source),
            "broker_timezone": broker_timezone,
            "affected_timestamp_fields": sorted(AFFECTED_TIMESTAMP_FIELDS),
            "unaffected_timestamp_fields": sorted(UNAFFECTED_TIMESTAMP_FIELDS),
            "row_count": row_count,
            "warning_count": warning_count,
            "unresolved_warning_inventory": unresolved_warning_inventory,
            "safe_for_strategy_analysis": warning_count == 0,
            "normalized_file": normalized_path.name,
            "normalized_sha256": _sha256(normalized_path),
        }
        _atomic_write(staging_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.replace(staging_dir, final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return final_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, help="Local immutable legacy journal JSONL copy.")
    parser.add_argument("--broker-timezone", default="Europe/Helsinki")
    parser.add_argument("--output-root", default="reports/live_ops/lpfs_c01_normalized")
    args = parser.parse_args()
    print(normalize_journal(Path(args.journal), Path(args.output_root), broker_timezone=args.broker_timezone))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
