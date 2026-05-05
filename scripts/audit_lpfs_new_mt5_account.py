from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import FOREX_MAJOR_CROSS_PAIRS, normalize_timeframe  # noqa: E402
from market_data_lab.mt5 import account_metadata, symbol_metadata, terminal_metadata  # noqa: E402
from market_data_lab.timeframes import mt5_timeframe_value  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports" / "mt5_account_validation" / "lpfs_new_account"
DEFAULT_TIMEFRAMES = ("H4", "H8", "H12", "D1", "W1")


def _parse_csv_arg(value: str | None, *, default: tuple[str, ...]) -> list[str]:
    if value is None or not value.strip():
        return list(default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _object_fields(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if obj is None:
        return {}
    return {field: _safe_value(getattr(obj, field, None)) for field in fields}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _utc_from_epoch_seconds(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _tick_snapshot(mt5_module: Any, symbol: str) -> dict[str, Any]:
    tick = mt5_module.symbol_info_tick(symbol)
    if tick is None:
        return {"tick_available": False, "tick_error": str(mt5_module.last_error())}
    return {
        "tick_available": True,
        **_object_fields(
            tick,
            (
                "time",
                "bid",
                "ask",
                "last",
                "volume",
                "time_msc",
                "flags",
                "volume_real",
            ),
        ),
    }


def _timeframe_probe(mt5_module: Any, symbol: str, timeframe: str, history_bars: int) -> dict[str, Any]:
    label = normalize_timeframe(timeframe)
    try:
        mt5_value = mt5_timeframe_value(mt5_module, label)
        raw = mt5_module.copy_rates_from_pos(symbol, mt5_value, 0, int(history_bars))
    except Exception as exc:
        return {
            "symbol": symbol,
            "timeframe": label,
            "status": "failed",
            "rows": 0,
            "error": str(exc),
        }

    if raw is None:
        return {
            "symbol": symbol,
            "timeframe": label,
            "status": "failed",
            "rows": 0,
            "error": str(mt5_module.last_error()),
        }
    rows = len(raw)
    if rows <= 0:
        return {
            "symbol": symbol,
            "timeframe": label,
            "status": "no_data",
            "rows": 0,
            "error": None,
        }
    first_time = raw[0]["time"] if "time" in raw.dtype.names else None
    last_time = raw[-1]["time"] if "time" in raw.dtype.names else None
    return {
        "symbol": symbol,
        "timeframe": label,
        "status": "ok",
        "rows": rows,
        "first_bar_time_utc": _utc_from_epoch_seconds(first_time),
        "last_bar_time_utc": _utc_from_epoch_seconds(last_time),
        "error": None,
    }


def _audit_symbol(
    mt5_module: Any,
    *,
    symbol: str,
    timeframes: list[str],
    history_bars: int,
    select_symbols: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = symbol.upper()
    info = mt5_module.symbol_info(normalized)
    if info is None:
        symbol_row = {
            "symbol": normalized,
            "available": False,
            "visible": False,
            "selected_for_audit": False,
            "error": str(mt5_module.last_error()),
        }
        coverage_rows = [
            {
                "symbol": normalized,
                "timeframe": normalize_timeframe(timeframe),
                "status": "symbol_unavailable",
                "rows": 0,
                "error": symbol_row["error"],
            }
            for timeframe in timeframes
        ]
        return symbol_row, coverage_rows

    visible_before = bool(getattr(info, "visible", False))
    selected = visible_before
    if select_symbols and not visible_before:
        selected = bool(mt5_module.symbol_select(normalized, True))
        info = mt5_module.symbol_info(normalized) or info

    symbol_row = {
        "symbol": normalized,
        "available": True,
        "visible": bool(getattr(info, "visible", visible_before)),
        "visible_before_audit": visible_before,
        "selected_for_audit": selected,
        "selection_attempted": bool(select_symbols and not visible_before),
        **symbol_metadata(info, normalized),
        **_object_fields(
            info,
            (
                "currency_base",
                "currency_profit",
                "currency_margin",
                "filling_mode",
                "order_mode",
                "expiration_mode",
                "trade_calc_mode",
            ),
        ),
        **_tick_snapshot(mt5_module, normalized),
    }
    coverage_rows = [
        _timeframe_probe(mt5_module, normalized, timeframe, history_bars)
        for timeframe in timeframes
    ]
    return symbol_row, coverage_rows


def build_readme(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return f"""# LPFS New MT5 Account Audit

Generated at: `{payload["generated_at_utc"]}`

This is a read-only local MT5 account audit for LP + Force Strike validation.
It does not call `order_check`, `order_send`, or touch the VPS runner.

## Summary

- Account login: `{payload["account"].get("login")}`
- Account server: `{payload["account"].get("server")}`
- Account currency: `{payload["account"].get("currency")}`
- Symbols requested: `{summary["symbols_requested"]}`
- Symbols available: `{summary["symbols_available"]}`
- Symbols not visible: `{summary["symbols_not_visible"]}`
- Timeframe probes: `{summary["timeframe_probes"]}`
- Timeframe probes OK: `{summary["timeframe_probes_ok"]}`
- Account expectation matched: `{not summary["account_mismatch"]}`

## Next

1. If the account is correct and all symbols/timeframes are available, pull the
   broker-specific dataset with `scripts/pull_mt5_dataset.py`.
2. Rerun the V22-separated LPFS baseline with the new-account strategy config.
3. Compare the new run against the existing V22 baseline before any dry-run or
   live-send work.
"""


def run_audit(
    *,
    output_dir: Path,
    symbols: list[str],
    timeframes: list[str],
    history_bars: int,
    expected_login: str | None,
    expected_server: str | None,
    mt5_path: str | None,
    select_symbols: bool,
) -> int:
    import MetaTrader5 as mt5  # type: ignore

    initialized = mt5.initialize(path=mt5_path) if mt5_path else mt5.initialize()
    if not initialized:
        raise RuntimeError(f"MetaTrader5 initialize failed: {mt5.last_error()}")

    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        account = account_metadata(mt5.account_info())
        terminal = terminal_metadata(mt5.terminal_info())
        if not account:
            raise RuntimeError("MT5 account_info unavailable. Log into the target account locally first.")

        symbol_rows: list[dict[str, Any]] = []
        coverage_rows: list[dict[str, Any]] = []
        for symbol in symbols:
            symbol_row, rows = _audit_symbol(
                mt5,
                symbol=symbol,
                timeframes=timeframes,
                history_bars=history_bars,
                select_symbols=select_symbols,
            )
            symbol_rows.append(symbol_row)
            coverage_rows.extend(rows)
    finally:
        mt5.shutdown()

    account_mismatch = False
    expected = {}
    if expected_login:
        expected["login"] = expected_login
        account_mismatch = account_mismatch or str(account.get("login")) != str(expected_login)
    if expected_server:
        expected["server"] = expected_server
        account_mismatch = account_mismatch or str(account.get("server")) != str(expected_server)

    available = [row for row in symbol_rows if row.get("available")]
    not_visible = [row for row in symbol_rows if row.get("available") and not row.get("visible")]
    ok_probes = [row for row in coverage_rows if row.get("status") == "ok"]
    failed_probes = [row for row in coverage_rows if row.get("status") != "ok"]
    summary = {
        "account_mismatch": account_mismatch,
        "symbols_requested": len(symbols),
        "symbols_available": len(available),
        "symbols_missing": len(symbols) - len(available),
        "symbols_not_visible": len(not_visible),
        "timeframes": timeframes,
        "history_bars": history_bars,
        "timeframe_probes": len(coverage_rows),
        "timeframe_probes_ok": len(ok_probes),
        "timeframe_probes_failed": len(failed_probes),
        "select_symbols": select_symbols,
    }
    payload = {
        "generated_at_utc": generated_at,
        "account": account,
        "expected_account": expected,
        "terminal": terminal,
        "summary": summary,
        "symbol_specs": symbol_rows,
        "timeframe_coverage": coverage_rows,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "account_audit.json", payload)
    _write_csv(output_dir / "symbol_specs.csv", symbol_rows)
    _write_csv(output_dir / "timeframe_coverage.csv", coverage_rows)
    (output_dir / "README.md").write_text(build_readme(payload), encoding="utf-8")

    print(json.dumps({"output_dir": str(output_dir), **summary}, indent=2, sort_keys=True))
    return 1 if account_mismatch or summary["symbols_missing"] or summary["timeframe_probes_failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a locally logged-in MT5 account for LPFS validation.")
    parser.add_argument("--output-dir", help="Output report directory. Defaults to reports/mt5_account_validation/lpfs_new_account/<timestamp>.")
    parser.add_argument("--symbols", help="Comma-separated symbols. Defaults to the 28 major/cross FX pairs.")
    parser.add_argument("--timeframes", help="Comma-separated timeframes. Defaults to H4,H8,H12,D1,W1.")
    parser.add_argument("--history-bars", type=int, default=300, help="Bars to probe per symbol/timeframe.")
    parser.add_argument("--expected-login", help="Expected MT5 login. If provided, mismatch returns non-zero.")
    parser.add_argument("--expected-server", help="Expected MT5 server. If provided, mismatch returns non-zero.")
    parser.add_argument("--mt5-path", help="Optional terminal64.exe path for a specific local MT5 terminal.")
    parser.add_argument("--select-symbols", action="store_true", help="Select hidden symbols in Market Watch before probing candles.")
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else DEFAULT_OUTPUT_ROOT / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )
    symbols = _parse_csv_arg(args.symbols, default=FOREX_MAJOR_CROSS_PAIRS)
    timeframes = _parse_csv_arg(args.timeframes, default=DEFAULT_TIMEFRAMES)
    return run_audit(
        output_dir=output_dir,
        symbols=symbols,
        timeframes=timeframes,
        history_bars=args.history_bars,
        expected_login=args.expected_login,
        expected_server=args.expected_server,
        mt5_path=args.mt5_path,
        select_symbols=args.select_symbols,
    )


if __name__ == "__main__":
    raise SystemExit(main())
