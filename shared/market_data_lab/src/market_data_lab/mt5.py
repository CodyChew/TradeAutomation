"""MT5 rates pull helpers for the shared market-data layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .schema import normalize_rates_frame, validate_rates_frame
from .storage import build_dataset_manifest, write_dataset_manifest, write_rates_parquet
from .timeframes import mt5_timeframe_value, normalize_timeframe


@dataclass(frozen=True)
class MT5PullResult:
    """Result metadata for one MT5 dataset pull."""

    symbol: str
    timeframe: str
    rows: int
    data_path: str
    manifest_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MT5SymbolAvailability:
    """Availability status for one requested MT5 symbol."""

    symbol: str
    available: bool
    visible: bool = False
    selected: bool = False
    symbol_metadata: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _optional_object_fields(obj: Any, fields: list[str]) -> dict[str, Any]:
    if obj is None:
        return {}
    return {field: getattr(obj, field, None) for field in fields}


def ensure_symbol(mt5_module: Any, symbol: str) -> Any:
    """Select one MT5 symbol and return its symbol_info object."""

    info = mt5_module.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"symbol_info unavailable for {symbol}: {mt5_module.last_error()}")
    if not getattr(info, "visible", True) and not mt5_module.symbol_select(symbol, True):
        raise RuntimeError(f"symbol_select failed for {symbol}: {mt5_module.last_error()}")
    return info


def symbol_metadata(info: Any, symbol: str) -> dict[str, Any]:
    """Extract stable symbol fields useful for backtest assumptions."""

    return {
        "symbol": str(symbol).upper(),
        "visible": bool(getattr(info, "visible", False)),
        "digits": _safe_int(getattr(info, "digits", None)),
        "point": _safe_float(getattr(info, "point", None)),
        "spread_points": _safe_int(getattr(info, "spread", None)),
        "spread_float": bool(getattr(info, "spread_float", False)),
        "trade_tick_value": _safe_float(getattr(info, "trade_tick_value", None)),
        "trade_tick_size": _safe_float(getattr(info, "trade_tick_size", None)),
        "volume_min": _safe_float(getattr(info, "volume_min", None)),
        "volume_max": _safe_float(getattr(info, "volume_max", None)),
        "volume_step": _safe_float(getattr(info, "volume_step", None)),
        "trade_contract_size": _safe_float(getattr(info, "trade_contract_size", None)),
        "trade_stops_level": _safe_int(getattr(info, "trade_stops_level", None)),
        "trade_freeze_level": _safe_int(getattr(info, "trade_freeze_level", None)),
        "trade_mode": _safe_int(getattr(info, "trade_mode", None)),
    }


def account_metadata(account: Any) -> dict[str, Any]:
    """Extract a non-sensitive subset of MT5 account metadata."""

    return _optional_object_fields(account, ["login", "server", "currency", "leverage", "company"])


def terminal_metadata(terminal: Any) -> dict[str, Any]:
    """Extract a useful subset of MT5 terminal metadata."""

    return _optional_object_fields(terminal, ["name", "company", "path", "data_path", "build"])


def query_mt5_symbol(mt5_module: Any, symbol: str) -> dict[str, Any]:
    """Return broker availability and symbol metadata for one MT5 symbol."""

    info = ensure_symbol(mt5_module, symbol)
    return {
        "available": True,
        "symbol_metadata": symbol_metadata(info, symbol),
    }


def pull_symbol_rates(
    mt5_module: Any,
    *,
    symbol: str,
    timeframe: str | int | float,
    start: datetime | str | pd.Timestamp,
    end: datetime | str | pd.Timestamp,
) -> pd.DataFrame:
    """Pull one symbol/timeframe from MT5 and return a canonical rates frame."""

    start_utc = _to_utc_timestamp(start).to_pydatetime()
    end_utc = _to_utc_timestamp(end).to_pydatetime()
    if end_utc <= start_utc:
        raise ValueError("end must be later than start.")

    raw = mt5_module.copy_rates_range(symbol, mt5_timeframe_value(mt5_module, timeframe), start_utc, end_utc)
    if raw is None:
        raise RuntimeError(f"copy_rates_range failed for {symbol} {timeframe}: {mt5_module.last_error()}")
    frame = normalize_rates_frame(pd.DataFrame(raw), symbol=symbol, timeframe=timeframe)
    validate_rates_frame(frame, symbol=symbol, timeframe=timeframe)
    return frame


def _load_mt5_module(mt5_module: Any | None) -> Any:
    if mt5_module is not None:
        return mt5_module
    import MetaTrader5 as mt5_module  # type: ignore

    return mt5_module


def check_mt5_symbols(symbols: list[str] | tuple[str, ...], *, mt5_module: Any | None = None) -> list[MT5SymbolAvailability]:
    """Check whether requested symbols are available in the MT5 terminal."""

    module = _load_mt5_module(mt5_module)
    if not module.initialize():
        raise RuntimeError(f"MetaTrader5 initialize failed: {module.last_error()}")

    results: list[MT5SymbolAvailability] = []
    try:
        for symbol in symbols:
            normalized = str(symbol).upper()
            info = module.symbol_info(normalized)
            if info is None:
                results.append(
                    MT5SymbolAvailability(
                        symbol=normalized,
                        available=False,
                        error=f"symbol_info unavailable: {module.last_error()}",
                    )
                )
                continue

            visible = bool(getattr(info, "visible", True))
            selected = visible or bool(module.symbol_select(normalized, True))
            results.append(
                MT5SymbolAvailability(
                    symbol=normalized,
                    available=selected,
                    visible=visible,
                    selected=selected,
                    symbol_metadata=symbol_metadata(info, normalized),
                    error=None if selected else f"symbol_select failed: {module.last_error()}",
                )
            )
    finally:
        module.shutdown()
    return results


def pull_mt5_rates(
    *,
    data_root: str | Path,
    symbol: str,
    timeframe: str | int | float,
    start: datetime | str | pd.Timestamp,
    end: datetime | str | pd.Timestamp,
    mt5_module: Any | None = None,
) -> MT5PullResult:
    """Pull, validate, store, and manifest one MT5 rates dataset."""

    module = _load_mt5_module(mt5_module)
    if not module.initialize():
        raise RuntimeError(f"MetaTrader5 initialize failed: {module.last_error()}")

    try:
        info = ensure_symbol(module, symbol)
        frame = pull_symbol_rates(module, symbol=symbol, timeframe=timeframe, start=start, end=end)
        data_path = write_rates_parquet(data_root, frame, symbol=symbol, timeframe=timeframe)
        manifest = build_dataset_manifest(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            source="mt5",
            data_path=data_path,
            requested_start_utc=start,
            requested_end_utc=end,
            symbol_metadata=symbol_metadata(info, symbol),
            account_metadata=account_metadata(module.account_info()),
            terminal_metadata=terminal_metadata(module.terminal_info()),
        )
        manifest_file = write_dataset_manifest(data_root, manifest)
        return MT5PullResult(
            symbol=str(symbol).upper(),
            timeframe=normalize_timeframe(timeframe),
            rows=int(len(frame)),
            data_path=str(data_path),
            manifest_path=str(manifest_file),
        )
    finally:
        module.shutdown()
