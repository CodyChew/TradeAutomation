"""Versioned LPFS trade diagnostics for journal and report rows."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from backtest_engine_lab import TradeSetup


DIAGNOSTIC_SCHEMA_VERSION = 2
TIMESTAMP_SEMANTICS_VERSION = "mt5_epoch_utc_v2"


def build_setup_diagnostics(
    setup: TradeSetup,
    *,
    config: Any | None = None,
    signal_key: str = "",
) -> dict[str, Any]:
    """Return compact setup diagnostics needed for live-vs-backtest analysis."""

    metadata = dict(getattr(setup, "metadata", {}) or {})
    symbol = str(getattr(setup, "symbol", "") or "").upper()
    timeframe = str(getattr(setup, "timeframe", "") or "").upper()
    side = str(getattr(setup, "side", "") or "")
    candidate_id = _optional_text(metadata.get("candidate_id"))
    signal_time = _optional_text(metadata.get("fs_signal_time_utc"))
    risk_distance = _risk_distance(setup)
    return _clean_dict(
        {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "timestamp_semantics_version": TIMESTAMP_SEMANTICS_VERSION,
            "setup": _clean_dict(
                {
                    "setup_id": getattr(setup, "setup_id", None),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": side,
                    "signal_index": getattr(setup, "signal_index", None),
                    "entry_index": getattr(setup, "entry_index", None),
                    "entry_price": _optional_float(getattr(setup, "entry_price", None)),
                    "stop_price": _optional_float(getattr(setup, "stop_price", None)),
                    "take_profit": _optional_float(getattr(setup, "target_price", None)),
                    "risk_distance": risk_distance,
                    "target_distance": _target_distance(setup),
                    "entry_model": metadata.get("entry_model"),
                    "entry_wait_mode": metadata.get("entry_wait_mode"),
                    "entry_wait_same_bar_priority": metadata.get("entry_wait_same_bar_priority"),
                    "entry_zone": _optional_float(metadata.get("entry_zone")),
                    "stop_model": metadata.get("stop_model"),
                    "exit_model": metadata.get("exit_model"),
                    "target_r": _optional_float(metadata.get("target_r")),
                    "max_risk_atr": _optional_float(metadata.get("max_risk_atr")),
                    "partial_target_r": _optional_float(metadata.get("partial_target_r")),
                    "partial_fraction": _optional_float(metadata.get("partial_fraction")),
                    "lp_price": _optional_float(metadata.get("lp_price")),
                    "lp_break_index": _optional_int(metadata.get("lp_break_index")),
                    "lp_break_time_utc": _optional_text(metadata.get("lp_break_time_utc")),
                    "fs_mother_index": _optional_int(metadata.get("fs_mother_index")),
                    "fs_signal_index": _optional_int(metadata.get("fs_signal_index")),
                    "fs_signal_time_utc": signal_time,
                    "fs_total_bars": _optional_int(metadata.get("fs_total_bars")),
                    "bars_from_lp_break": _optional_int(metadata.get("bars_from_lp_break")),
                    "structure_low": _optional_float(metadata.get("structure_low")),
                    "structure_high": _optional_float(metadata.get("structure_high")),
                    "atr": _optional_float(metadata.get("atr")),
                    "risk_atr": _optional_float(metadata.get("risk_atr")),
                    "pending_from_latest_closed_signal": metadata.get("pending_from_latest_closed_signal"),
                }
            ),
            "strategy": _strategy_diagnostics(config),
            "backtest_join": _clean_dict(
                {
                    "signal_key": signal_key,
                    "setup_id": getattr(setup, "setup_id", None),
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": side,
                    "signal_index": getattr(setup, "signal_index", None),
                    "signal_time_utc": signal_time,
                    "trade_key": _join_key(symbol, timeframe, side, getattr(setup, "signal_index", None), candidate_id, signal_time),
                }
            ),
        }
    )


def enrich_diagnostics(
    diagnostics: Mapping[str, Any] | None,
    *,
    market: Any | None = None,
    spread_gate: Any | None = None,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return diagnostics with additional market/spread/execution context."""

    payload = _deep_dict(diagnostics)
    if not payload:
        payload = {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "timestamp_semantics_version": TIMESTAMP_SEMANTICS_VERSION,
        }
    payload["schema_version"] = payload.get("schema_version") or DIAGNOSTIC_SCHEMA_VERSION
    payload["timestamp_semantics_version"] = payload.get("timestamp_semantics_version") or TIMESTAMP_SEMANTICS_VERSION
    market_payload = _market_diagnostics(market)
    if market_payload:
        payload["market"] = _clean_dict({**_deep_dict(payload.get("market")), **market_payload})
    spread_payload = _spread_gate_diagnostics(spread_gate)
    if spread_payload:
        payload["spread_gate"] = _clean_dict({**_deep_dict(payload.get("spread_gate")), **spread_payload})
    if execution:
        payload["execution"] = _clean_dict({**_deep_dict(payload.get("execution")), **dict(execution)})
    return _clean_dict(payload)


def fields_with_diagnostics(
    fields: Mapping[str, Any] | None,
    diagnostics: Mapping[str, Any] | None,
    *,
    market: Any | None = None,
    spread_gate: Any | None = None,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach diagnostics to notification fields without changing existing keys."""

    payload = dict(fields or {})
    enriched = enrich_diagnostics(diagnostics, market=market, spread_gate=spread_gate, execution=execution)
    payload["diagnostic_schema_version"] = enriched.get("schema_version", DIAGNOSTIC_SCHEMA_VERSION)
    payload["diagnostics"] = enriched
    return payload


def diagnostics_from_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return diagnostics from notification fields, tolerating old rows."""

    if not isinstance(fields, Mapping):
        return {}
    diagnostics = fields.get("diagnostics")
    return _deep_dict(diagnostics) if isinstance(diagnostics, Mapping) else {}


def flatten_diagnostics(diagnostics: Mapping[str, Any] | None) -> dict[str, Any]:
    """Flatten nested diagnostics into stable report columns."""

    flat: dict[str, Any] = {}
    _flatten("", _deep_dict(diagnostics), flat)
    return flat


def _strategy_diagnostics(config: Any | None) -> dict[str, Any]:
    if config is None:
        return {}
    return _clean_dict(
        {
            "pivot_strength": _optional_int(getattr(config, "pivot_strength", None)),
            "max_bars_from_lp_break": _optional_int(getattr(config, "max_bars_from_lp_break", None)),
            "require_lp_pivot_before_fs_mother": getattr(config, "require_lp_pivot_before_fs_mother", None),
            "max_entry_wait_bars": _optional_int(getattr(config, "max_entry_wait_bars", None)),
            "max_spread_risk_fraction": _optional_float(getattr(config, "max_spread_risk_fraction", None)),
            "market_recovery_mode": getattr(config, "market_recovery_mode", None),
            "risk_bucket_scale": _optional_float(getattr(config, "risk_bucket_scale", None)),
            "max_open_risk_pct": _optional_float(getattr(config, "max_open_risk_pct", None)),
            "max_same_symbol_stack": _optional_int(getattr(config, "max_same_symbol_stack", None)),
            "max_concurrent_strategy_trades": _optional_int(getattr(config, "max_concurrent_strategy_trades", None)),
        }
    )


def _market_diagnostics(market: Any | None) -> dict[str, Any]:
    if market is None:
        return {}
    time_value = getattr(market, "time_utc", None)
    return _clean_dict(
        {
            "bid": _optional_float(getattr(market, "bid", None)),
            "ask": _optional_float(getattr(market, "ask", None)),
            "spread_points": _optional_float(getattr(market, "spread_points", None)),
            "market_time_utc": _optional_text(time_value),
            "raw_mt5_time": _optional_int(getattr(market, "raw_mt5_time", None)),
            "raw_mt5_time_msc": _optional_int(getattr(market, "raw_mt5_time_msc", None)),
            "timestamp_semantics_version": getattr(market, "timestamp_semantics_version", None),
            "timestamp_provenance": getattr(market, "timestamp_provenance", None),
        }
    )


def _spread_gate_diagnostics(spread_gate: Any | None) -> dict[str, Any]:
    if spread_gate is None:
        return {}
    return _clean_dict(
        {
            "passed": getattr(spread_gate, "passed", None),
            "spread_points": _optional_float(getattr(spread_gate, "spread_points", None)),
            "spread_price": _optional_float(getattr(spread_gate, "spread_price", None)),
            "risk_price": _optional_float(getattr(spread_gate, "risk_price", None)),
            "spread_risk_fraction": _optional_float(getattr(spread_gate, "spread_risk_fraction", None)),
            "max_spread_risk_fraction": _optional_float(getattr(spread_gate, "max_spread_risk_fraction", None)),
        }
    )


def _risk_distance(setup: TradeSetup) -> float | None:
    entry = _optional_float(getattr(setup, "entry_price", None))
    stop = _optional_float(getattr(setup, "stop_price", None))
    if entry is None or stop is None:
        return None
    return abs(entry - stop)


def _target_distance(setup: TradeSetup) -> float | None:
    entry = _optional_float(getattr(setup, "entry_price", None))
    target = _optional_float(getattr(setup, "target_price", None))
    if entry is None or target is None:
        return None
    return abs(target - entry)


def _join_key(
    symbol: str,
    timeframe: str,
    side: str,
    signal_index: Any,
    candidate_id: str | None,
    signal_time: str | None,
) -> str:
    parts = [symbol, timeframe, str(side).lower(), "" if signal_index is None else str(signal_index), candidate_id or "", signal_time or ""]
    return "|".join(parts)


def _deep_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _deep_value(item) for key, item in value.items()}
    return {}


def _deep_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_value(item) for item in value]
    if isinstance(value, tuple):
        return [_deep_value(item) for item in value]
    if is_dataclass(value):
        return _deep_value(asdict(value))
    return value


def _clean_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or value == "":
            continue
        if isinstance(value, Mapping):
            nested = _clean_dict(value)
            if nested:
                cleaned[str(key)] = nested
            continue
        cleaned[str(key)] = value
    return cleaned


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _optional_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _flatten(prefix: str, payload: Mapping[str, Any], flat: dict[str, Any]) -> None:
    for key, value in payload.items():
        column = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            _flatten(column, value, flat)
        else:
            flat[f"diagnostic_{column}"] = value
