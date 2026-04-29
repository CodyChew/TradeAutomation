from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import get_timeframe_spec, load_dataset_config, load_rates_parquet  # noqa: E402


DEFAULT_BASELINE = REPO_ROOT / "configs" / "datasets" / "fingerprints" / "ftmo_forex_major_crosses_10y.json"
DEFAULT_CONFIGS = [
    REPO_ROOT / "configs" / "datasets" / "forex_major_crosses_10y.json",
    REPO_ROOT / "configs" / "datasets" / "forex_major_crosses_10y_h8.json",
    REPO_ROOT / "configs" / "datasets" / "forex_major_crosses_10y_h12.json",
]
HASH_COLUMNS = ["time_utc", "open", "high", "low", "close", "tick_volume", "spread_points", "real_volume"]


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _large_gap_tolerance(timeframe: str) -> pd.Timedelta:
    if timeframe == "W1":
        return pd.Timedelta(days=14)
    return pd.Timedelta(days=5)


def _load_frame(data_root: str | Path, symbol: str, timeframe: str) -> pd.DataFrame:
    frame = load_rates_parquet(data_root, symbol=symbol, timeframe=timeframe)
    frame = frame.sort_values("time_utc").reset_index(drop=True)
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True)
    return frame


def _stable_hash(frame: pd.DataFrame) -> str:
    data = frame.loc[:, HASH_COLUMNS].copy()
    data["time_utc"] = pd.to_datetime(data["time_utc"], utc=True).astype("int64")
    hashed = pd.util.hash_pandas_object(data, index=False).to_numpy(dtype="uint64")
    return hashlib.sha256(hashed.tobytes()).hexdigest()


def _fingerprint_frame(frame: pd.DataFrame, *, symbol: str, timeframe: str) -> dict[str, Any]:
    deltas = frame["time_utc"].diff()
    large_gaps = deltas > _large_gap_tolerance(timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(frame)),
        "first_time_utc": frame["time_utc"].iloc[0].isoformat(),
        "last_time_utc": frame["time_utc"].iloc[-1].isoformat(),
        "min_low": float(frame["low"].min()),
        "max_high": float(frame["high"].max()),
        "duplicate_timestamps": int(frame["time_utc"].duplicated().sum()),
        "max_gap_hours": float(deltas.max() / pd.Timedelta(hours=1)) if len(deltas.dropna()) else 0.0,
        "large_gap_count": int(large_gaps.sum()),
        "data_hash_sha256": _stable_hash(frame),
    }


def _dataset_keys(config_paths: list[Path]) -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in config_paths:
        config = load_dataset_config(path)
        for symbol in config.symbols:
            for timeframe in config.timeframes:
                key = (str(config.data_root), str(symbol).upper(), str(timeframe).upper())
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
    return keys


def build_fingerprint(config_paths: list[Path]) -> dict[str, Any]:
    datasets = []
    for data_root, symbol, timeframe in _dataset_keys(config_paths):
        frame = _load_frame(data_root, symbol, timeframe)
        datasets.append(_fingerprint_frame(frame, symbol=symbol, timeframe=timeframe))
    datasets = sorted(datasets, key=lambda row: (row["symbol"], row["timeframe"]))
    config_labels = []
    for path in config_paths:
        try:
            config_labels.append(str(path.relative_to(REPO_ROOT)) if path.is_absolute() else str(path))
        except ValueError:
            config_labels.append(str(path))
    return {
        "schema_version": 1,
        "description": "FTMO FOREX major/cross 10-year local candle fingerprint.",
        "configs": config_labels,
        "dataset_count": len(datasets),
        "datasets": datasets,
    }


def _dataset_id(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["symbol"]), str(row["timeframe"])


def _compare_fingerprints(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected_rows = {_dataset_id(row): row for row in expected.get("datasets", [])}
    actual_rows = {_dataset_id(row): row for row in actual.get("datasets", [])}

    missing = sorted(set(expected_rows).difference(actual_rows))
    extra = sorted(set(actual_rows).difference(expected_rows))
    for symbol, timeframe in missing:
        failures.append(f"missing dataset {symbol} {timeframe}")
    for symbol, timeframe in extra:
        failures.append(f"unexpected dataset {symbol} {timeframe}")

    compared_fields = [
        "rows",
        "first_time_utc",
        "last_time_utc",
        "min_low",
        "max_high",
        "duplicate_timestamps",
        "max_gap_hours",
        "large_gap_count",
        "data_hash_sha256",
    ]
    for key in sorted(set(expected_rows).intersection(actual_rows)):
        expected_row = expected_rows[key]
        actual_row = actual_rows[key]
        symbol, timeframe = key
        for field in compared_fields:
            if actual_row.get(field) != expected_row.get(field):
                failures.append(
                    f"{symbol} {timeframe} {field} changed: "
                    f"expected={expected_row.get(field)!r} actual={actual_row.get(field)!r}"
                )
    return failures


def _aggregation_rows(
    config_paths: list[Path],
    *,
    tolerance: float,
    settlement_days: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    keys = _dataset_keys(config_paths)
    by_symbol: dict[str, set[str]] = {}
    roots: dict[str, str] = {}
    for data_root, symbol, timeframe in keys:
        by_symbol.setdefault(symbol, set()).add(timeframe)
        roots[symbol] = data_root

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for symbol, timeframes in sorted(by_symbol.items()):
        if "M30" not in timeframes:
            continue
        m30 = _load_frame(roots[symbol], symbol, "M30")
        settled_until = m30["time_utc"].iloc[-1] - pd.Timedelta(days=settlement_days)
        for timeframe in sorted(timeframes - {"M30"}, key=lambda tf: get_timeframe_spec(tf).expected_delta):
            target = _load_frame(roots[symbol], symbol, timeframe)
            target = target.copy()
            target["target_idx"] = range(len(target))
            target["target_end"] = target["time_utc"].shift(-1)
            target.loc[target.index[-1], "target_end"] = target.loc[target.index[-1], "time_utc"] + get_timeframe_spec(timeframe).expected_delta
            target = target[target["target_end"] <= settled_until].reset_index(drop=True)
            if target.empty:
                compared = 0
                mismatches = 0
                max_open_diff = max_high_diff = max_low_diff = max_close_diff = 0.0
            else:
                assigned = pd.merge_asof(
                    m30.sort_values("time_utc"),
                    target[["time_utc", "target_idx", "target_end"]].sort_values("time_utc"),
                    on="time_utc",
                    direction="backward",
                )
                assigned = assigned[
                    assigned["target_idx"].notna()
                    & (assigned["time_utc"] < assigned["target_end"])
                ].copy()
                assigned["target_idx"] = assigned["target_idx"].astype(int)
                aggregated = (
                    assigned.groupby("target_idx", sort=True)
                    .agg(
                        open=("open", "first"),
                        high=("high", "max"),
                        low=("low", "min"),
                        close=("close", "last"),
                    )
                    .reset_index()
                )
                compared_frame = target.merge(aggregated, on="target_idx", how="inner", suffixes=("_target", "_m30"))
                compared = int(len(compared_frame))
                open_diff_series = (compared_frame["open_m30"] - compared_frame["open_target"]).abs()
                high_diff_series = (compared_frame["high_m30"] - compared_frame["high_target"]).abs()
                low_diff_series = (compared_frame["low_m30"] - compared_frame["low_target"]).abs()
                close_diff_series = (compared_frame["close_m30"] - compared_frame["close_target"]).abs()
                max_diff_series = pd.concat(
                    [open_diff_series, high_diff_series, low_diff_series, close_diff_series],
                    axis=1,
                ).max(axis=1)
                mismatches = int((max_diff_series > tolerance).sum())
                max_open_diff = float(open_diff_series.max()) if compared else 0.0
                max_high_diff = float(high_diff_series.max()) if compared else 0.0
                max_low_diff = float(low_diff_series.max()) if compared else 0.0
                max_close_diff = float(close_diff_series.max()) if compared else 0.0
            row = {
                "symbol": symbol,
                "timeframe": timeframe,
                "settlement_days": float(settlement_days),
                "compared_candles": compared,
                "mismatch_count": mismatches,
                "max_open_diff": max_open_diff,
                "max_high_diff": max_high_diff,
                "max_low_diff": max_low_diff,
                "max_close_diff": max_close_diff,
            }
            rows.append(row)
            if mismatches:
                failures.append(f"{symbol} {timeframe} has {mismatches} M30 aggregation mismatches")
    return rows, failures


def verify(
    config_paths: list[Path],
    baseline_path: Path,
    *,
    aggregation_tolerance: float,
    aggregation_settlement_days: float,
) -> dict[str, Any]:
    actual = build_fingerprint(config_paths)
    expected = _read_json(baseline_path)
    fingerprint_failures = _compare_fingerprints(actual, expected)
    aggregation_rows, aggregation_failures = _aggregation_rows(
        config_paths,
        tolerance=aggregation_tolerance,
        settlement_days=aggregation_settlement_days,
    )
    failures = fingerprint_failures + aggregation_failures
    return {
        "status": "FAIL" if failures else "OK",
        "failures": failures,
        "fingerprint_dataset_count": actual["dataset_count"],
        "aggregation_settlement_days": float(aggregation_settlement_days),
        "aggregation_checks": aggregation_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify canonical local dataset fingerprints.")
    parser.add_argument(
        "--config",
        action="append",
        dest="configs",
        help="Dataset config JSON. Can be passed multiple times. Defaults to the FOREX M30/H4/D1/W1, H8, and H12 configs.",
    )
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="Fingerprint baseline JSON path.")
    parser.add_argument("--write-baseline", action="store_true", help="Write/update the baseline instead of verifying it.")
    parser.add_argument("--aggregation-tolerance", type=float, default=1e-9, help="Maximum allowed M30 aggregation OHLC diff.")
    parser.add_argument(
        "--aggregation-settlement-days",
        type=float,
        default=1.0,
        help="Skip the newest N days when checking higher timeframes against M30, avoiding MT5 live-edge cache drift.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    args = parser.parse_args()

    config_paths = [Path(path) for path in args.configs] if args.configs else DEFAULT_CONFIGS
    baseline_path = Path(args.baseline)
    if args.write_baseline:
        payload = build_fingerprint(config_paths)
        _write_json(baseline_path, payload)
        print(f"wrote={baseline_path}")
        print(f"datasets={payload['dataset_count']}")
        return 0

    result = verify(
        config_paths,
        baseline_path,
        aggregation_tolerance=float(args.aggregation_tolerance),
        aggregation_settlement_days=float(args.aggregation_settlement_days),
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"status={result['status']}")
        print(f"fingerprint_datasets={result['fingerprint_dataset_count']}")
        print(f"aggregation_checks={len(result['aggregation_checks'])}")
        for failure in result["failures"]:
            print(f"failure: {failure}")
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
