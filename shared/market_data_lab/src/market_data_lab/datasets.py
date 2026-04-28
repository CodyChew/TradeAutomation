"""Config-driven dataset pulls and coverage reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .mt5 import account_metadata, ensure_symbol, pull_symbol_rates, symbol_metadata, terminal_metadata
from .storage import build_dataset_manifest, dataset_status, write_dataset_manifest, write_rates_parquet
from .symbols import FOREX_MAJOR_CROSS_PAIRS
from .timeframes import get_timeframe_spec, normalize_timeframe


@dataclass(frozen=True)
class DatasetConfig:
    """One repeatable market-data dataset request."""

    dataset_name: str
    data_root: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    history_years: int | None = None
    date_start_utc: str | None = None
    date_end_utc: str | None = None
    source: str = "mt5"


@dataclass(frozen=True)
class DatasetPullItem:
    """Result for one symbol/timeframe pull attempt."""

    symbol: str
    timeframe: str
    status: str
    rows: int = 0
    data_path: str | None = None
    manifest_path: str | None = None
    coverage_start_utc: str | None = None
    coverage_end_utc: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _symbol_universe(name: str | None) -> tuple[str, ...]:
    if name is None:
        return ()
    normalized = name.strip().lower()
    if normalized == "forex_major_cross_pairs":
        return FOREX_MAJOR_CROSS_PAIRS
    raise ValueError(f"Unsupported symbol_universe {name!r}.")


def load_dataset_config(path: str | Path) -> DatasetConfig:
    """Load a dataset config JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    explicit_symbols = tuple(str(symbol).upper() for symbol in payload.get("symbols", []))
    universe_symbols = _symbol_universe(payload.get("symbol_universe"))
    symbols = explicit_symbols or universe_symbols
    if not symbols:
        raise ValueError("Dataset config must define symbols or symbol_universe.")

    timeframes = tuple(normalize_timeframe(timeframe) for timeframe in payload.get("timeframes", []))
    if not timeframes:
        raise ValueError("Dataset config must define at least one timeframe.")

    history_years = payload.get("history_years")
    return DatasetConfig(
        dataset_name=str(payload.get("dataset_name", Path(path).stem)),
        data_root=str(payload.get("data_root", "data/raw")),
        symbols=symbols,
        timeframes=timeframes,
        history_years=None if history_years in (None, "") else int(history_years),
        date_start_utc=None if payload.get("date_start_utc") in (None, "") else str(payload["date_start_utc"]),
        date_end_utc=None if payload.get("date_end_utc") in (None, "") else str(payload["date_end_utc"]),
        source=str(payload.get("source", "mt5")),
    )


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _boundary_tolerance(timeframe: str) -> pd.Timedelta:
    """Allow normal market-closure gaps at requested dataset boundaries."""

    expected = get_timeframe_spec(timeframe).expected_delta
    market_closure = pd.Timedelta(days=3)
    if expected < pd.Timedelta(days=7):
        return max(expected, market_closure)
    return expected


def resolve_date_window(config: DatasetConfig, *, now: datetime | pd.Timestamp | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Resolve the UTC pull window from explicit dates or history_years."""

    end = _to_utc_timestamp(now or datetime.now(timezone.utc))
    if config.date_end_utc is not None:
        end = _to_utc_timestamp(config.date_end_utc)

    if config.date_start_utc is not None:
        start = _to_utc_timestamp(config.date_start_utc)
    else:
        years = 10 if config.history_years is None else config.history_years
        start = end - pd.Timedelta(days=int(years) * 365)

    if end <= start:
        raise ValueError("Resolved date_end_utc must be later than date_start_utc.")
    return start, end


def _load_mt5_module(mt5_module: Any | None) -> Any:
    if mt5_module is not None:
        return mt5_module
    import MetaTrader5 as mt5_module  # type: ignore

    return mt5_module


def pull_mt5_dataset(
    config: DatasetConfig,
    *,
    mt5_module: Any | None = None,
    stop_on_error: bool = False,
    now: datetime | pd.Timestamp | None = None,
) -> list[DatasetPullItem]:
    """Pull all symbol/timeframe datasets from MT5 with per-item status."""

    if config.source.lower() != "mt5":
        raise ValueError("Only source='mt5' is supported for dataset pulls.")

    module = _load_mt5_module(mt5_module)
    if not module.initialize():
        raise RuntimeError(f"MetaTrader5 initialize failed: {module.last_error()}")

    start, end = resolve_date_window(config, now=now)
    account = account_metadata(module.account_info())
    terminal = terminal_metadata(module.terminal_info())
    results: list[DatasetPullItem] = []
    try:
        for symbol in config.symbols:
            for timeframe in config.timeframes:
                label = normalize_timeframe(timeframe)
                try:
                    info = ensure_symbol(module, symbol)
                    frame = pull_symbol_rates(
                        module,
                        symbol=symbol,
                        timeframe=label,
                        start=start.to_pydatetime(),
                        end=end.to_pydatetime(),
                    )
                    data_path = write_rates_parquet(config.data_root, frame, symbol=symbol, timeframe=label)
                    manifest = build_dataset_manifest(
                        frame,
                        symbol=symbol,
                        timeframe=label,
                        source="mt5",
                        data_path=data_path,
                        requested_start_utc=start,
                        requested_end_utc=end,
                        symbol_metadata=symbol_metadata(info, symbol),
                        account_metadata=account,
                        terminal_metadata=terminal,
                    )
                    manifest_path = write_dataset_manifest(config.data_root, manifest)
                    results.append(
                        DatasetPullItem(
                            symbol=str(symbol).upper(),
                            timeframe=label,
                            status="ok",
                            rows=int(len(frame)),
                            data_path=str(data_path),
                            manifest_path=str(manifest_path),
                            coverage_start_utc=manifest["coverage_start_utc"],
                            coverage_end_utc=manifest["coverage_end_utc"],
                        )
                    )
                except Exception as exc:
                    if stop_on_error:
                        raise
                    results.append(
                        DatasetPullItem(
                            symbol=str(symbol).upper(),
                            timeframe=label,
                            status="failed",
                            error=str(exc),
                        )
                    )
    finally:
        module.shutdown()
    return results


def dataset_coverage_report(
    config: DatasetConfig,
    *,
    now: datetime | pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Return coverage readiness rows for all configured datasets."""

    start, end = resolve_date_window(config, now=now)
    rows = dataset_status(config.data_root, symbols=list(config.symbols), timeframes=list(config.timeframes))
    report: list[dict[str, Any]] = []
    for row in rows:
        coverage_start = row.get("coverage_start_utc")
        coverage_end = row.get("coverage_end_utc")
        start_ok = False
        end_ok = False
        label = str(row["timeframe"])
        tolerance = _boundary_tolerance(label)
        start_gap_hours = None
        end_gap_hours = None
        if coverage_start:
            start_gap = _to_utc_timestamp(coverage_start) - start
            start_gap_hours = max(float(start_gap / pd.Timedelta(hours=1)), 0.0)
            start_ok = start_gap <= tolerance
        if coverage_end:
            end_gap = end - _to_utc_timestamp(coverage_end)
            end_gap_hours = max(float(end_gap / pd.Timedelta(hours=1)), 0.0)
            end_ok = end_gap <= tolerance
        ready = bool(row.get("data_exists") and row.get("manifest_exists") and start_ok and end_ok)
        report.append(
            {
                **row,
                "requested_start_utc": start.isoformat(),
                "requested_end_utc": end.isoformat(),
                "boundary_tolerance_hours": float(tolerance / pd.Timedelta(hours=1)),
                "coverage_start_gap_hours": start_gap_hours,
                "coverage_end_gap_hours": end_gap_hours,
                "coverage_start_ok": start_ok,
                "coverage_end_ok": end_ok,
                "backtest_ready": ready,
            }
        )
    return report
