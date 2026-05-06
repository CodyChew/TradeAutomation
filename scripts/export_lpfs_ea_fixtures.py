from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
LPFS_ROOT = REPO_ROOT / "strategies" / "lp_force_strike_strategy_lab"
SRC_ROOTS = [
    LPFS_ROOT / "src",
    REPO_ROOT / "concepts" / "lp_levels_lab" / "src",
    REPO_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    REPO_ROOT / "shared" / "backtest_engine_lab" / "src",
]
DEFAULT_OUTPUT = REPO_ROOT / "mql5" / "lpfs_ea" / "fixtures" / "canonical_lpfs_ea_fixture.json"

for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    ExistingStrategyExposure,
    ExecutionSafetyLimits,
    MT5AccountSnapshot,
    MT5MarketSnapshot,
    MT5SymbolExecutionSpec,
    TradeModelCandidate,
    build_mt5_order_intent,
    build_trade_setup,
    detect_lp_force_strike_signals,
    signal_key_for_setup,
)


BASE_RISK_PROFILES: dict[str, dict[str, Any]] = {
    "Conservative": {
        "risk_buckets_pct": {"H4": 0.10, "H8": 0.10, "H12": 0.15, "D1": 0.15, "W1": 0.30},
        "max_open_risk_pct": 3.0,
        "max_concurrent_trades": 8,
        "max_same_symbol_trades": 2,
    },
    "Standard": {
        "risk_buckets_pct": {"H4": 0.20, "H8": 0.20, "H12": 0.30, "D1": 0.30, "W1": 0.75},
        "max_open_risk_pct": 6.0,
        "max_concurrent_trades": 17,
        "max_same_symbol_trades": 4,
    },
    "Growth": {
        "risk_buckets_pct": {"H4": 0.25, "H8": 0.25, "H12": 0.30, "D1": 0.30, "W1": 0.75},
        "max_open_risk_pct": 9.0,
        "max_concurrent_trades": 17,
        "max_same_symbol_trades": 4,
    },
}

APPROVED_SYMBOLS = [
    "AUDCAD",
    "AUDCHF",
    "AUDJPY",
    "AUDNZD",
    "AUDUSD",
    "CADCHF",
    "CADJPY",
    "CHFJPY",
    "EURAUD",
    "EURCAD",
    "EURCHF",
    "EURGBP",
    "EURJPY",
    "EURNZD",
    "EURUSD",
    "GBPAUD",
    "GBPCAD",
    "GBPCHF",
    "GBPJPY",
    "GBPNZD",
    "GBPUSD",
    "NZDCAD",
    "NZDCHF",
    "NZDJPY",
    "NZDUSD",
    "USDCAD",
    "USDCHF",
    "USDJPY",
]
APPROVED_TIMEFRAMES = ["H4", "H8", "H12", "D1", "W1"]


def _frame(rows: list[dict[str, float]]) -> pd.DataFrame:
    times = pd.date_range("2026-01-01 00:00:00+00:00", periods=len(rows), freq="4h", tz="UTC")
    return pd.DataFrame(
        [
            {
                "time_utc": times[index],
                "open": row.get("open", (row["high"] + row["low"]) / 2.0),
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for index, row in enumerate(rows)
        ]
    )


def _long_rows() -> list[dict[str, float]]:
    return [
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 8.0, "low": 5.0, "close": 6.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 8.0, "low": 4.0, "close": 5.0},
        {"high": 9.0, "low": 7.0, "close": 8.0},
        {"high": 10.0, "low": 8.0, "close": 9.0},
        {"high": 9.0, "low": 3.8, "close": 7.0},
        {"high": 8.5, "low": 4.5, "close": 7.0},
        {"high": 8.8, "low": 3.5, "close": 8.0},
        {"high": 9.0, "low": 6.0, "close": 8.2},
    ]


def _short_rows() -> list[dict[str, float]]:
    return [
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 15.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 16.0, "low": 10.0, "close": 12.0},
        {"high": 13.0, "low": 9.0, "close": 11.0},
        {"high": 12.0, "low": 8.0, "close": 10.0},
        {"high": 17.0, "low": 10.0, "close": 12.0},
        {"high": 16.5, "low": 10.5, "close": 12.0},
        {"high": 17.2, "low": 10.5, "close": 11.0},
        {"high": 14.1, "low": 9.8, "close": 11.0},
    ]


def _overlap_rows() -> list[dict[str, float]]:
    return [
        {"high": 8.0, "low": 5.0, "close": 6.0},
        {"high": 8.5, "low": 5.5, "close": 6.5},
        {"high": 9.2, "low": 6.0, "close": 7.0},
        {"high": 9.4, "low": 6.5, "close": 7.5},
        {"high": 10.0, "low": 8.0, "close": 9.8},
        {"high": 9.8, "low": 8.4, "close": 9.0},
        {"high": 9.7, "low": 8.5, "close": 9.2},
        {"high": 9.8, "low": 8.6, "close": 9.4},
        {"high": 10.2, "low": 8.5, "close": 8.9},
        {"high": 9.5, "low": 8.4, "close": 9.0},
    ]


def _candidate() -> TradeModelCandidate:
    return TradeModelCandidate(
        candidate_id="lp_pivot_3__signal_zone_0p5_pullback__fs_structure__1r",
        entry_model="signal_zone_pullback",
        entry_zone=0.5,
        stop_model="fs_structure",
        target_r=1.0,
    )


def _symbol_spec(**overrides: Any) -> MT5SymbolExecutionSpec:
    values = {
        "symbol": "EURUSD",
        "digits": 5,
        "point": 0.0001,
        "trade_tick_value": 10.0,
        "trade_tick_size": 0.0001,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "trade_stops_level_points": 5,
        "trade_freeze_level_points": 0,
        "visible": True,
        "trade_allowed": True,
    }
    values.update(overrides)
    return MT5SymbolExecutionSpec(**values)


def _account(equity: float = 100_000.0) -> MT5AccountSnapshot:
    return MT5AccountSnapshot(equity=equity, currency="USD")


def _market(**overrides: Any) -> MT5MarketSnapshot:
    values = {"bid": 8.60, "ask": 8.62, "time_utc": pd.Timestamp("2026-01-03T00:00:00Z")}
    values.update(overrides)
    return MT5MarketSnapshot(**values)


def _setup_from_frame(frame: pd.DataFrame, *, symbol: str = "EURUSD", timeframe: str = "H4") -> tuple[Any, TradeSetup]:
    signals = detect_lp_force_strike_signals(frame, timeframe, pivot_strength=2)
    if len(signals) != 1:
        raise RuntimeError(f"Expected one fixture signal, got {len(signals)}")
    setup = build_trade_setup(
        frame,
        signals[0],
        _candidate(),
        symbol=symbol,
        timeframe=timeframe,
        max_entry_wait_bars=6,
        entry_wait_mode="fixed_bars",
        entry_wait_same_bar_priority="entry",
    )
    if not isinstance(setup, TradeSetup):
        raise RuntimeError(f"Expected fixture trade setup, got {setup}")
    return signals[0], setup


def _bar_payload(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples():
        rows.append(
            {
                "time_utc": row.time_utc.isoformat(),
                "open": round(float(row.open), 8),
                "high": round(float(row.high), 8),
                "low": round(float(row.low), 8),
                "close": round(float(row.close), 8),
            }
        )
    return rows


def _signal_payload(signal: Any) -> dict[str, Any]:
    return {
        "side": signal.side,
        "scenario": signal.scenario,
        "lp_price": float(signal.lp_price),
        "lp_break_index": int(signal.lp_break_index),
        "lp_pivot_index": int(signal.lp_pivot_index),
        "fs_mother_index": int(signal.fs_mother_index),
        "fs_signal_index": int(signal.fs_signal_index),
        "bars_from_lp_break": int(signal.bars_from_lp_break),
        "fs_total_bars": int(signal.fs_total_bars),
        "fs_signal_time_utc": signal.fs_signal_time_utc.isoformat(),
    }


def _setup_payload(setup: TradeSetup) -> dict[str, Any]:
    return {
        "setup_id": setup.setup_id,
        "symbol": setup.symbol,
        "timeframe": setup.timeframe,
        "side": setup.side,
        "signal_index": setup.signal_index,
        "entry_index": setup.entry_index,
        "entry_price": round(float(setup.entry_price), 8),
        "stop_price": round(float(setup.stop_price), 8),
        "target_price": round(float(setup.target_price), 8),
        "signal_key": signal_key_for_setup(setup),
    }


def _decision_payload(decision: Any) -> dict[str, Any]:
    payload = {
        "ready": bool(decision.ready),
        "status": decision.status,
        "rejection_reason": decision.rejection_reason,
        "detail": decision.detail,
        "checks": list(decision.checks),
    }
    if decision.intent is not None:
        intent = decision.intent.to_dict()
        payload["intent"] = {
            key: intent[key]
            for key in [
                "order_type",
                "volume",
                "entry_price",
                "stop_loss",
                "take_profit",
                "target_risk_pct",
                "actual_risk_pct",
                "magic",
                "comment",
                "signal_key",
                "max_entry_wait_bars",
                "strategy_expiry_mode",
            ]
            if key in intent
        }
    return payload


def _trade_setup(
    *,
    side: str = "long",
    entry: float = 1.1000,
    stop: float = 1.0950,
    target: float = 1.1050,
    timeframe: str = "H4",
    symbol: str = "EURUSD",
) -> TradeSetup:
    return TradeSetup(
        setup_id=f"{symbol}_{timeframe}_{side}",
        side=side,  # type: ignore[arg-type]
        entry_index=11,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        symbol=symbol,
        timeframe=timeframe,
        signal_index=10,
        metadata={
            "candidate_id": "lp_pivot_3__signal_zone_0p5_pullback__fs_structure__1r",
            "fs_signal_time_utc": pd.Timestamp("2026-01-01T00:00:00Z"),
        },
    )


def _dynamic_spread_gate(setup: TradeSetup, *, bid: float, ask: float, max_fraction: float = 0.10) -> dict[str, Any]:
    spread_price = ask - bid
    risk_price = abs(float(setup.entry_price) - float(setup.stop_price))
    fraction = spread_price / risk_price if risk_price > 0 else float("inf")
    return {
        "spread_price": round(spread_price, 8),
        "risk_price": round(risk_price, 8),
        "spread_risk_fraction": round(fraction, 8),
        "max_spread_risk_fraction": max_fraction,
        "passed": bool(spread_price >= 0 and risk_price > 0 and fraction <= max_fraction),
    }


def build_fixture_payload() -> dict[str, Any]:
    long_frame = _frame(_long_rows())
    long_signal, long_setup = _setup_from_frame(long_frame)
    long_decision = build_mt5_order_intent(
        long_setup,
        account=_account(),
        symbol_spec=_symbol_spec(point=0.01, trade_tick_size=0.01, trade_tick_value=10.0),
        market=_market(bid=8.60, ask=8.62),
        safety=ExecutionSafetyLimits(strategy_magic=331500, order_comment_prefix="LPFSEA"),
    )

    short_frame = _frame(_short_rows())
    short_signal, short_setup = _setup_from_frame(short_frame, timeframe="W1")
    short_decision = build_mt5_order_intent(
        short_setup,
        account=_account(),
        symbol_spec=_symbol_spec(point=0.01, trade_tick_size=0.01, trade_tick_value=10.0),
        market=MT5MarketSnapshot(bid=11.00, ask=11.02, time_utc=pd.Timestamp("2026-01-03T00:00:00Z")),
        safety=ExecutionSafetyLimits(strategy_magic=331500, order_comment_prefix="LPFSEA"),
    )

    no_signal_frame = _frame([{"high": 1.0, "low": 0.8, "close": 0.9} for _ in range(12)])
    overlap_frame = _frame(_overlap_rows())
    overlap_default = detect_lp_force_strike_signals(overlap_frame, "H4", pivot_strength=2)
    overlap_legacy = detect_lp_force_strike_signals(
        overlap_frame,
        "H4",
        pivot_strength=2,
        require_lp_pivot_before_fs_mother=False,
    )

    base_setup = _trade_setup()
    rejection_cases = {
        "spread_too_wide_dynamic": _dynamic_spread_gate(base_setup, bid=1.1000, ask=1.1008),
        "volume_below_min": _decision_payload(
            build_mt5_order_intent(
                base_setup,
                account=_account(100.0),
                symbol_spec=_symbol_spec(volume_min=0.10),
                market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            )
        ),
        "sl_tp_too_close": _decision_payload(
            build_mt5_order_intent(
                _trade_setup(entry=1.1000, stop=1.0998, target=1.1002),
                account=_account(),
                symbol_spec=_symbol_spec(trade_stops_level_points=5),
                market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
            )
        ),
        "pending_expired": _decision_payload(
            build_mt5_order_intent(
                base_setup,
                account=_account(),
                symbol_spec=_symbol_spec(),
                market=MT5MarketSnapshot(bid=1.1018, ask=1.1020, time_utc=pd.Timestamp("2026-01-12T04:00:00Z")),
            )
        ),
        "duplicate_signal": _decision_payload(
            build_mt5_order_intent(
                base_setup,
                account=_account(),
                symbol_spec=_symbol_spec(),
                market=MT5MarketSnapshot(bid=1.1018, ask=1.1020),
                exposure=ExistingStrategyExposure(existing_signal_keys=(signal_key_for_setup(base_setup),)),
            )
        ),
        "max_open_risk": _decision_payload(
            build_mt5_order_intent(
                _trade_setup(side="short", entry=1.2000, stop=1.2100, target=1.1900, timeframe="W1"),
                account=_account(),
                symbol_spec=_symbol_spec(),
                market=MT5MarketSnapshot(bid=1.1980, ask=1.1982),
                safety=ExecutionSafetyLimits(max_lots_per_order=0.10),
                exposure=ExistingStrategyExposure(open_risk_pct=5.91),
            )
        ),
    }

    return {
        "fixture_version": 1,
        "strategy_contract": "V13 mechanics + V15 risk buckets + V22 LP/FS separation",
        "ea_mode": "native_mql5_tester_only",
        "approved_symbols": APPROVED_SYMBOLS,
        "approved_timeframes": APPROVED_TIMEFRAMES,
        "risk_profiles": BASE_RISK_PROFILES,
        "cases": {
            "valid_long_signal": {
                "symbol": "EURUSD",
                "timeframe": "H4",
                "bars": _bar_payload(long_frame),
                "signal": _signal_payload(long_signal),
                "setup": _setup_payload(long_setup),
                "order_decision": _decision_payload(long_decision),
            },
            "valid_short_signal": {
                "symbol": "EURUSD",
                "timeframe": "W1",
                "bars": _bar_payload(short_frame),
                "signal": _signal_payload(short_signal),
                "setup": _setup_payload(short_setup),
                "order_decision": _decision_payload(short_decision),
            },
            "no_signal": {
                "symbol": "EURUSD",
                "timeframe": "H4",
                "bars": _bar_payload(no_signal_frame),
                "signals": [],
            },
            "invalid_lp_fs_separation": {
                "symbol": "EURUSD",
                "timeframe": "H4",
                "bars": _bar_payload(overlap_frame),
                "default_signal_count": len(overlap_default),
                "legacy_signal_count": len(overlap_legacy),
            },
            "rejections": rejection_cases,
        },
    }


def write_fixture(path: Path = DEFAULT_OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_fixture_payload()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export canonical Python parity fixtures for the LPFS MQL5 EA port.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = write_fixture(args.output)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
