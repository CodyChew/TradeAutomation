"""File-backed rates storage and dataset manifests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import normalize_rates_frame, validate_rates_frame
from .timeframes import normalize_timeframe


def symbol_timeframe_dir(root: str | Path, symbol: str, timeframe: str | int | float) -> Path:
    """Return the canonical directory for one symbol/timeframe dataset."""

    return Path(root) / str(symbol).upper() / normalize_timeframe(timeframe)


def rates_csv_path(root: str | Path, symbol: str, timeframe: str | int | float) -> Path:
    """Return the canonical CSV path for one symbol/timeframe dataset."""

    label = normalize_timeframe(timeframe)
    return symbol_timeframe_dir(root, symbol, label) / f"{str(symbol).upper()}_{label}.csv"


def rates_parquet_path(root: str | Path, symbol: str, timeframe: str | int | float) -> Path:
    """Return the canonical Parquet path for one symbol/timeframe dataset."""

    label = normalize_timeframe(timeframe)
    return symbol_timeframe_dir(root, symbol, label) / f"{str(symbol).upper()}_{label}.parquet"


def manifest_path(root: str | Path, symbol: str, timeframe: str | int | float) -> Path:
    """Return the canonical manifest path for one symbol/timeframe dataset."""

    return symbol_timeframe_dir(root, symbol, timeframe) / "manifest.json"


def write_rates_csv(root: str | Path, frame: pd.DataFrame, *, symbol: str, timeframe: str | int | float) -> Path:
    """Validate and write one canonical rates CSV."""

    data = normalize_rates_frame(frame, symbol=symbol, timeframe=timeframe)
    validate_rates_frame(data, symbol=symbol, timeframe=timeframe)
    target = rates_csv_path(root, symbol, timeframe)
    target.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(target, index=False)
    return target


def load_rates_csv(root: str | Path, *, symbol: str, timeframe: str | int | float) -> pd.DataFrame:
    """Load, normalize, and validate one canonical rates CSV."""

    path = rates_csv_path(root, symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")
    data = normalize_rates_frame(pd.read_csv(path), symbol=symbol, timeframe=timeframe)
    validate_rates_frame(data, symbol=symbol, timeframe=timeframe)
    return data


def write_rates_parquet(root: str | Path, frame: pd.DataFrame, *, symbol: str, timeframe: str | int | float) -> Path:
    """Validate and write one canonical rates Parquet dataset."""

    data = normalize_rates_frame(frame, symbol=symbol, timeframe=timeframe)
    validate_rates_frame(data, symbol=symbol, timeframe=timeframe)
    target = rates_parquet_path(root, symbol, timeframe)
    target.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(target, index=False)
    return target


def load_rates_parquet(root: str | Path, *, symbol: str, timeframe: str | int | float) -> pd.DataFrame:
    """Load, normalize, and validate one canonical rates Parquet dataset."""

    path = rates_parquet_path(root, symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")
    data = normalize_rates_frame(pd.read_parquet(path), symbol=symbol, timeframe=timeframe)
    validate_rates_frame(data, symbol=symbol, timeframe=timeframe)
    return data


def _iso_or_none(value: Any) -> str | None:
    if value is None or value is pd.NA:
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def build_dataset_manifest(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str | int | float,
    source: str,
    data_path: str | Path,
    requested_start_utc: Any | None = None,
    requested_end_utc: Any | None = None,
    symbol_metadata: dict[str, Any] | None = None,
    account_metadata: dict[str, Any] | None = None,
    terminal_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable dataset manifest."""

    data = normalize_rates_frame(frame, symbol=symbol, timeframe=timeframe)
    validate_rates_frame(data, symbol=symbol, timeframe=timeframe)
    return {
        "symbol": str(symbol).upper(),
        "timeframe": normalize_timeframe(timeframe),
        "source": source,
        "requested_start_utc": _iso_or_none(requested_start_utc),
        "requested_end_utc": _iso_or_none(requested_end_utc),
        "coverage_start_utc": _iso_or_none(data["time_utc"].iloc[0]),
        "coverage_end_utc": _iso_or_none(data["time_utc"].iloc[-1]),
        "rows": int(len(data)),
        "storage_format": Path(data_path).suffix.lower().lstrip("."),
        "path": str(data_path),
        "symbol_metadata": symbol_metadata or {},
        "account_metadata": account_metadata or {},
        "terminal_metadata": terminal_metadata or {},
        "pulled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write a JSON payload using stable formatting."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def read_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON object from disk."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_dataset_manifest(root: str | Path, manifest: dict[str, Any]) -> Path:
    """Write one dataset manifest to the canonical manifest path."""

    target = manifest_path(root, str(manifest["symbol"]), str(manifest["timeframe"]))
    return write_json(target, manifest)


def dataset_status(root: str | Path, *, symbols: list[str], timeframes: list[str | int | float]) -> list[dict[str, Any]]:
    """Return file existence and manifest coverage for requested datasets."""

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            label = normalize_timeframe(timeframe)
            parquet_path = rates_parquet_path(root, symbol, label)
            csv_path = rates_csv_path(root, symbol, label)
            json_path = manifest_path(root, symbol, label)
            manifest = read_json(json_path) if json_path.exists() else {}
            manifest_data_path = Path(str(manifest.get("path", ""))) if manifest.get("path") else None
            data_path = manifest_data_path or parquet_path
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "timeframe": label,
                    "data_exists": data_path.exists(),
                    "data_path": str(data_path),
                    "storage_format": manifest.get("storage_format"),
                    "parquet_exists": parquet_path.exists(),
                    "csv_exists": csv_path.exists(),
                    "manifest_exists": json_path.exists(),
                    "parquet_path": str(parquet_path),
                    "csv_path": str(csv_path),
                    "manifest_path": str(json_path),
                    "rows": manifest.get("rows"),
                    "coverage_start_utc": manifest.get("coverage_start_utc"),
                    "coverage_end_utc": manifest.get("coverage_end_utc"),
                }
            )
    return rows
