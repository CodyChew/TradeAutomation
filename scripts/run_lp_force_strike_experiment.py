from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = [
    REPO_ROOT / "shared" / "market_data_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
]
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import CostConfig, drop_incomplete_last_bar  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    LPForceStrikeSignal,
    SkippedTrade,
    make_trade_model_candidates,
    run_lp_force_strike_experiment_on_frame,
    trade_report_row,
)
from market_data_lab import (  # noqa: E402
    load_dataset_config,
    load_rates_parquet,
    manifest_path,
    normalize_timeframe,
    read_json,
)


def _read_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: str | Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=columns) if columns is not None else pd.DataFrame(rows)
    frame.to_csv(target, index=False)


def _parse_csv_arg(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _selected_symbols(dataset_symbols: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    if override is not None:
        symbols = override
    elif config.get("symbols") is None:
        symbols = list(dataset_symbols)
    else:
        symbols = [str(symbol).upper() for symbol in config.get("symbols", [])]

    excluded = {str(symbol).upper() for symbol in config.get("excluded_symbols", [])}
    return [symbol for symbol in symbols if symbol not in excluded]


def _selected_timeframes(dataset_timeframes: tuple[str, ...], config: dict[str, Any], override: list[str] | None) -> list[str]:
    raw = override if override is not None else config.get("timeframes", dataset_timeframes)
    return [normalize_timeframe(timeframe) for timeframe in raw]


def _cost_config(payload: dict[str, Any]) -> CostConfig:
    costs = payload.get("costs", {})
    return CostConfig(
        use_candle_spread=bool(costs.get("use_candle_spread", True)),
        fallback_spread_points=float(costs.get("fallback_spread_points", 0.0)),
        entry_slippage_points=float(costs.get("entry_slippage_points", 0.0)),
        exit_slippage_points=float(costs.get("exit_slippage_points", 0.0)),
        round_turn_commission_points=float(costs.get("round_turn_commission_points", 0.0)),
    )


def _selected_pivot_strengths(config: dict[str, Any]) -> list[int]:
    raw_values = config.get("pivot_strengths")
    if raw_values is None:
        raw_values = [config.get("pivot_strength", 3)]

    strengths = [int(value) for value in raw_values]
    if not strengths:
        raise ValueError("At least one pivot strength is required.")
    if any(value < 1 for value in strengths):
        raise ValueError("Pivot strengths must be positive integers.")
    return strengths


def _manifest(root: str | Path, symbol: str, timeframe: str) -> dict[str, Any]:
    return read_json(manifest_path(root, symbol, timeframe))


def _load_backtest_frame(data_root: str | Path, symbol: str, timeframe: str, *, drop_latest: bool) -> pd.DataFrame:
    frame = load_rates_parquet(data_root, symbol=symbol, timeframe=timeframe)
    manifest = _manifest(data_root, symbol, timeframe)
    point = manifest.get("symbol_metadata", {}).get("point")
    if point is not None:
        frame["point"] = float(point)

    if drop_latest:
        requested_end = manifest.get("requested_end_utc")
        if requested_end:
            frame = drop_incomplete_last_bar(frame, timeframe, as_of_time_utc=requested_end)
    return frame


def _report_candidate_id(candidate_id: str, pivot_strength: int, *, include_pivot: bool) -> str:
    if not include_pivot:
        return candidate_id
    return f"lp_pivot_{pivot_strength}__{candidate_id}"


def _signal_row(symbol: str, timeframe: str, pivot_strength: int, signal: LPForceStrikeSignal) -> dict[str, Any]:
    row = asdict(signal)
    row["symbol"] = symbol
    row["timeframe"] = timeframe
    row["pivot_strength"] = pivot_strength
    return row


def _skipped_row(
    skipped: SkippedTrade,
    candidate_lookup: dict[str, dict[str, Any]],
    *,
    pivot_strength: int,
    include_pivot_in_candidate_id: bool,
) -> dict[str, Any]:
    row = skipped.to_dict()
    row["base_candidate_id"] = skipped.candidate_id
    row["pivot_strength"] = pivot_strength
    row["candidate_id"] = _report_candidate_id(
        skipped.candidate_id,
        pivot_strength,
        include_pivot=include_pivot_in_candidate_id,
    )
    row.update({f"candidate_{key}": value for key, value in candidate_lookup.get(skipped.candidate_id, {}).items()})
    return row


def _trade_row(trade, *, pivot_strength: int, include_pivot_in_candidate_id: bool) -> dict[str, Any]:
    row = trade_report_row(trade)
    base_candidate_id = str(row.get("candidate_id", ""))
    row["base_candidate_id"] = base_candidate_id
    row["pivot_strength"] = pivot_strength
    row["candidate_id"] = _report_candidate_id(
        base_candidate_id,
        pivot_strength,
        include_pivot=include_pivot_in_candidate_id,
    )
    return row


def _candidate_rows(candidates, pivot_strengths: list[int], *, include_pivot_in_candidate_id: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        base = asdict(candidate)
        for pivot_strength in pivot_strengths:
            row = dict(base)
            row["base_candidate_id"] = candidate.candidate_id
            row["pivot_strength"] = pivot_strength
            row["candidate_id"] = _report_candidate_id(
                candidate.candidate_id,
                pivot_strength,
                include_pivot=include_pivot_in_candidate_id,
            )
            rows.append(row)
    return rows


def _summary_rows_from_report_rows(rows: list[dict[str, Any]], *, group_fields: list[str]) -> list[dict[str, Any]]:
    if not rows:
        return []

    frame = pd.DataFrame(rows)
    required = set(group_fields + ["net_r", "bars_held", "exit_reason"])
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Trade report rows are missing required summary fields: {missing}")

    frame["net_r"] = pd.to_numeric(frame["net_r"], errors="coerce").fillna(0.0)
    frame["bars_held"] = pd.to_numeric(frame["bars_held"], errors="coerce").fillna(0.0)

    summary: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_fields, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        net_r = group["net_r"]
        gross_win = float(net_r[net_r > 0].sum())
        gross_loss = float(net_r[net_r < 0].sum())
        trade_count = int(len(group))
        row = {field: value for field, value in zip(group_fields, keys)}
        row.update(
            {
                "trades": trade_count,
                "wins": int((net_r > 0).sum()),
                "losses": int((net_r < 0).sum()),
                "win_rate": float((net_r > 0).sum()) / trade_count if trade_count else 0.0,
                "total_net_r": float(net_r.sum()),
                "avg_net_r": float(net_r.mean()) if trade_count else 0.0,
                "profit_factor": None if gross_loss == 0 else gross_win / abs(gross_loss),
                "avg_bars_held": float(group["bars_held"].mean()) if trade_count else 0.0,
                "target_exits": int((group["exit_reason"] == "target").sum()),
                "stop_exits": int((group["exit_reason"] == "stop").sum()),
                "same_bar_stop_exits": int((group["exit_reason"] == "same_bar_stop_priority").sum()),
                "end_of_data_exits": int((group["exit_reason"] == "end_of_data").sum()),
            }
        )
        summary.append(row)

    return summary


def _run(config_path: Path, *, symbol_override: list[str] | None, timeframe_override: list[str] | None, output_dir: Path | None) -> int:
    config = _read_config(config_path)
    dataset_config = load_dataset_config(REPO_ROOT / str(config["dataset_config"]))
    symbols = _selected_symbols(dataset_config.symbols, config, symbol_override)
    timeframes = _selected_timeframes(dataset_config.timeframes, config, timeframe_override)
    candidates = make_trade_model_candidates(
        entry_models=[str(value) for value in config["entry_models"]],
        stop_models=[str(value) for value in config["stop_models"]],
        target_rs=[float(value) for value in config["target_rs"]],
        max_risk_atrs=[float(value) for value in config.get("max_risk_atrs", [])],
        entry_zones=[float(value) for value in config.get("entry_zones", [])] or None,
        exit_models=[str(value) for value in config.get("exit_models", ["single_target"])],
        partial_target_r=float(config.get("partial_target_r", 1.0)),
        partial_fraction=float(config.get("partial_fraction", 0.5)),
    )
    candidate_lookup = {candidate.candidate_id: asdict(candidate) for candidate in candidates}
    pivot_strengths = _selected_pivot_strengths(config)
    include_pivot_in_candidate_id = len(pivot_strengths) > 1
    costs = _cost_config(config)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir or (REPO_ROOT / str(config["report_root"]) / timestamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    all_signal_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    all_skipped_rows: list[dict[str, Any]] = []
    dataset_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                frame = _load_backtest_frame(
                    dataset_config.data_root,
                    symbol,
                    timeframe,
                    drop_latest=bool(config.get("drop_incomplete_latest_bar", True)),
                )
                for pivot_strength in pivot_strengths:
                    result = run_lp_force_strike_experiment_on_frame(
                        frame,
                        symbol=symbol,
                        timeframe=timeframe,
                        candidates=candidates,
                        pivot_strength=pivot_strength,
                        max_bars_from_lp_break=int(config.get("max_bars_from_lp_break", 6)),
                        atr_period=int(config.get("atr_period", 14)),
                        max_entry_wait_bars=int(config.get("max_entry_wait_bars", 6)),
                        entry_wait_mode=str(config.get("entry_wait_mode", "fixed_bars")),
                        entry_wait_same_bar_priority=str(config.get("entry_wait_same_bar_priority", "entry")),
                        costs=costs,
                    )
                    all_signal_rows.extend(_signal_row(symbol, timeframe, pivot_strength, signal) for signal in result.signals)
                    all_trade_rows.extend(
                        _trade_row(
                            trade,
                            pivot_strength=pivot_strength,
                            include_pivot_in_candidate_id=include_pivot_in_candidate_id,
                        )
                        for trade in result.trades
                    )
                    all_skipped_rows.extend(
                        _skipped_row(
                            skipped,
                            candidate_lookup,
                            pivot_strength=pivot_strength,
                            include_pivot_in_candidate_id=include_pivot_in_candidate_id,
                        )
                        for skipped in result.skipped
                    )
                    dataset_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "pivot_strength": pivot_strength,
                            "status": "ok",
                            "rows": int(len(frame)),
                            "signals": int(len(result.signals)),
                            "trades": int(len(result.trades)),
                            "skipped": int(len(result.skipped)),
                        }
                    )
                    print(
                        f"{symbol} {timeframe} LP{pivot_strength}: rows={len(frame)} signals={len(result.signals)} "
                        f"trades={len(result.trades)} skipped={len(result.skipped)}"
                    )
            except Exception as exc:
                dataset_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                print(f"{symbol} {timeframe}: failed={exc}")

    _write_json(
        run_dir / "run_config.json",
        {
            "config_path": str(config_path),
            "config": config,
            "symbols": symbols,
            "timeframes": timeframes,
            "pivot_strengths": pivot_strengths,
            "candidates": _candidate_rows(
                candidates,
                pivot_strengths,
                include_pivot_in_candidate_id=include_pivot_in_candidate_id,
            ),
        },
    )
    _write_csv(run_dir / "datasets.csv", dataset_rows)
    _write_csv(run_dir / "signals.csv", all_signal_rows)
    _write_csv(run_dir / "trades.csv", all_trade_rows)
    _write_csv(run_dir / "skipped.csv", all_skipped_rows)
    _write_csv(
        run_dir / "candidates.csv",
        _candidate_rows(
            candidates,
            pivot_strengths,
            include_pivot_in_candidate_id=include_pivot_in_candidate_id,
        ),
    )
    _write_csv(run_dir / "summary_by_candidate.csv", _summary_rows_from_report_rows(all_trade_rows, group_fields=["candidate_id"]))
    _write_csv(
        run_dir / "summary_by_candidate_timeframe.csv",
        _summary_rows_from_report_rows(all_trade_rows, group_fields=["candidate_id", "timeframe"]),
    )
    _write_csv(
        run_dir / "summary_by_candidate_symbol.csv",
        _summary_rows_from_report_rows(all_trade_rows, group_fields=["candidate_id", "symbol"]),
    )
    _write_csv(
        run_dir / "summary_by_pivot_strength.csv",
        _summary_rows_from_report_rows(all_trade_rows, group_fields=["pivot_strength"]),
    )
    _write_csv(
        run_dir / "summary_by_pivot_strength_timeframe.csv",
        _summary_rows_from_report_rows(all_trade_rows, group_fields=["pivot_strength", "timeframe"]),
    )

    failed = [row for row in dataset_rows if row.get("status") != "ok"]
    summary = {
        "run_dir": str(run_dir),
        "datasets": len(dataset_rows),
        "failed_datasets": len(failed),
        "signals": len(all_signal_rows),
        "trades": len(all_trade_rows),
        "skipped": len(all_skipped_rows),
    }
    _write_json(run_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LP + Force Strike trade-model experiment.")
    parser.add_argument("--config", required=True, help="Path to experiment config JSON.")
    parser.add_argument("--symbols", help="Optional comma-separated symbol override, e.g. AUDCAD,EURUSD.")
    parser.add_argument("--timeframes", help="Optional comma-separated timeframe override, e.g. M30,H4.")
    parser.add_argument("--output-dir", help="Optional explicit output directory.")
    args = parser.parse_args()

    symbol_override = _parse_csv_arg(args.symbols)
    timeframe_override = _parse_csv_arg(args.timeframes)
    output_dir = None if args.output_dir is None else Path(args.output_dir)
    return _run(Path(args.config), symbol_override=symbol_override, timeframe_override=timeframe_override, output_dir=output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
