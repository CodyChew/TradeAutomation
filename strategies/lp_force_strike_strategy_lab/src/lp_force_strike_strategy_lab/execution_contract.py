"""Pure MT5 execution contract for the LP + Force Strike baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Literal

import pandas as pd

from backtest_engine_lab import TradeSetup


OrderType = Literal["BUY_LIMIT", "SELL_LIMIT", "BUY", "SELL"]
ExecutionDecisionStatus = Literal["ready", "rejected"]

V15_EFFICIENT_RISK_BUCKET_PCT: dict[str, float] = {
    "H4": 0.20,
    "H8": 0.20,
    "H12": 0.30,
    "D1": 0.30,
    "W1": 0.75,
}

TIMEFRAME_DELTAS: dict[str, pd.Timedelta] = {
    "H4": pd.Timedelta(hours=4),
    "H8": pd.Timedelta(hours=8),
    "H12": pd.Timedelta(hours=12),
    "D1": pd.Timedelta(days=1),
    "W1": pd.Timedelta(days=7),
}

BROKER_BACKSTOP_PADDING: dict[str, pd.Timedelta] = {
    "H4": pd.Timedelta(days=10),
    "H8": pd.Timedelta(days=10),
    "H12": pd.Timedelta(days=10),
    "D1": pd.Timedelta(days=14),
    "W1": pd.Timedelta(days=21),
}


@dataclass(frozen=True)
class MT5SymbolExecutionSpec:
    """Broker metadata needed before an order can be considered sendable."""

    symbol: str
    digits: int
    point: float
    trade_tick_value: float
    trade_tick_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_stops_level_points: int = 0
    trade_freeze_level_points: int = 0
    visible: bool = True
    trade_allowed: bool = True


@dataclass(frozen=True)
class MT5AccountSnapshot:
    """Non-sensitive account state used for risk sizing."""

    equity: float
    currency: str = ""


@dataclass(frozen=True)
class MT5MarketSnapshot:
    """Current market quote used to decide pending order validity."""

    bid: float
    ask: float
    time_utc: pd.Timestamp | str | None = None
    spread_points: float | None = None


@dataclass(frozen=True)
class ExecutionSafetyLimits:
    """Executor guardrails that must pass before live order sending is allowed."""

    max_risk_pct_per_trade: float = 0.75
    max_open_risk_pct: float = 6.0
    max_lots_per_order: float | None = None
    max_same_symbol_stack: int = 4
    max_concurrent_strategy_trades: int = 17
    max_spread_points: float | None = None
    strategy_magic: int = 131500


@dataclass(frozen=True)
class ExistingStrategyExposure:
    """Existing strategy exposure from MT5 reconciliation and the local journal."""

    open_risk_pct: float = 0.0
    same_symbol_positions: int = 0
    total_strategy_positions: int = 0
    existing_signal_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class MT5OrderIntent:
    """Validated order intent ready for a later MT5 adapter to translate."""

    signal_key: str
    symbol: str
    timeframe: str
    side: str
    order_type: OrderType
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    target_risk_pct: float
    actual_risk_pct: float
    expiration_time_utc: pd.Timestamp
    magic: int
    comment: str
    setup_id: str
    signal_time_utc: pd.Timestamp | None = None
    max_entry_wait_bars: int = 6
    strategy_expiry_mode: str = "bar_count"
    broker_backstop_expiration_time_utc: pd.Timestamp | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expiration_time_utc"] = self.expiration_time_utc.isoformat()
        if self.signal_time_utc is not None:
            payload["signal_time_utc"] = self.signal_time_utc.isoformat()
        else:
            payload.pop("signal_time_utc", None)
        if self.broker_backstop_expiration_time_utc is not None:
            payload["broker_backstop_expiration_time_utc"] = self.broker_backstop_expiration_time_utc.isoformat()
        else:
            payload.pop("broker_backstop_expiration_time_utc", None)
        return payload


@dataclass(frozen=True)
class MT5ExecutionDecision:
    """Order contract result: either sendable intent or precise rejection."""

    status: ExecutionDecisionStatus
    intent: MT5OrderIntent | None = None
    rejection_reason: str | None = None
    detail: str = ""
    checks: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.intent is not None:
            payload["intent"] = self.intent.to_dict()
        return payload


@dataclass(frozen=True)
class _SizedVolume:
    volume: float
    actual_risk_pct: float


def risk_pct_for_timeframe(timeframe: str, risk_buckets: dict[str, float] | None = None) -> float:
    """Return the V15 account-risk percentage for one baseline timeframe."""

    buckets = risk_buckets or V15_EFFICIENT_RISK_BUCKET_PCT
    key = str(timeframe).upper()
    if key not in buckets:
        raise ValueError(f"No execution risk bucket for timeframe {timeframe!r}.")
    return float(buckets[key])


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    """Return the candle duration for an executable baseline timeframe."""

    key = str(timeframe).upper()
    if key not in TIMEFRAME_DELTAS:
        raise ValueError(f"Unsupported execution timeframe {timeframe!r}.")
    return TIMEFRAME_DELTAS[key]


def setup_signal_time_utc(setup: TradeSetup) -> pd.Timestamp:
    """Return the setup signal candle open time as a UTC timestamp."""

    signal_time = setup.metadata.get("fs_signal_time_utc")
    if signal_time is None:
        raise ValueError("TradeSetup metadata missing fs_signal_time_utc.")
    timestamp = pd.Timestamp(signal_time)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def pending_expiration_time_utc(setup: TradeSetup, *, max_entry_wait_bars: int = 6) -> pd.Timestamp:
    """Return the theoretical fixed-bar boundary for the pullback wait.

    Candle timestamps are bar opens. The signal candle is known after it closes,
    then the pullback can fill during the next ``max_entry_wait_bars`` candles.
    This timestamp is only exact when bars are continuous. Live execution uses
    actual MT5 bar counting for strategy expiry and a separate broker backstop.
    """

    if max_entry_wait_bars < 1:
        raise ValueError("max_entry_wait_bars must be >= 1.")
    return setup_signal_time_utc(setup) + timeframe_delta(setup.timeframe) * (max_entry_wait_bars + 1)


def broker_backstop_expiration_time_utc(setup: TradeSetup, *, max_entry_wait_bars: int = 6) -> pd.Timestamp:
    """Return the conservative broker-side emergency expiration timestamp."""

    key = str(setup.timeframe).upper()
    if key not in BROKER_BACKSTOP_PADDING:
        raise ValueError(f"Unsupported execution timeframe {setup.timeframe!r}.")
    return pending_expiration_time_utc(setup, max_entry_wait_bars=max_entry_wait_bars) + BROKER_BACKSTOP_PADDING[key]


def signal_key_for_setup(setup: TradeSetup) -> str:
    """Build the idempotency key used to prevent duplicate live orders."""

    candidate = setup.metadata.get("candidate_id", "unknown_candidate")
    signal_time = setup.metadata.get("fs_signal_time_utc", "unknown_time")
    return (
        f"lpfs:{str(setup.symbol).upper()}:{str(setup.timeframe).upper()}:"
        f"{setup.signal_index}:{setup.side}:{candidate}:{signal_time}"
    )


def money_risk_per_lot(setup: TradeSetup, spec: MT5SymbolExecutionSpec) -> float:
    """Return account-currency risk for one lot between entry and stop."""

    if spec.trade_tick_value <= 0 or spec.trade_tick_size <= 0:
        raise ValueError("Symbol tick value and tick size must be positive.")
    distance = abs(float(setup.entry_price) - float(setup.stop_price))
    return distance / float(spec.trade_tick_size) * float(spec.trade_tick_value)


def build_mt5_order_intent(
    setup: TradeSetup,
    *,
    account: MT5AccountSnapshot,
    symbol_spec: MT5SymbolExecutionSpec,
    market: MT5MarketSnapshot,
    safety: ExecutionSafetyLimits | None = None,
    exposure: ExistingStrategyExposure | None = None,
    risk_buckets: dict[str, float] | None = None,
    max_entry_wait_bars: int = 6,
    money_risk_per_lot_override: float | None = None,
) -> MT5ExecutionDecision:
    """Convert a tested setup into a guarded MT5 pending-order intent."""

    limits = safety or ExecutionSafetyLimits()
    current_exposure = exposure or ExistingStrategyExposure()
    signal_key = signal_key_for_setup(setup)
    checks: list[str] = []

    basic_rejection = _basic_rejection(setup, account, symbol_spec, market, limits, current_exposure, signal_key)
    if basic_rejection is not None:
        reason, detail = basic_rejection
        return _reject(reason, detail, checks)
    checks.append("basic_contract")

    order_type = _order_type(setup, market)
    if order_type is None:
        return _reject("entry_not_pending_pullback", "Entry is already marketable or on the wrong side of current quote.", checks)
    checks.append("pending_direction")

    distance_rejection = _distance_rejection(setup, symbol_spec, market, order_type)
    if distance_rejection is not None:
        reason, detail = distance_rejection
        return _reject(reason, detail, checks)
    checks.append("broker_distances")

    try:
        target_risk_pct = risk_pct_for_timeframe(setup.timeframe, risk_buckets)
    except ValueError as exc:
        return _reject("missing_risk_bucket", str(exc), checks)
    if target_risk_pct <= 0 or target_risk_pct > limits.max_risk_pct_per_trade:
        return _reject("risk_pct_limit", f"target_risk_pct={target_risk_pct:g}", checks)
    checks.append("risk_bucket")

    volume_decision = _sized_volume(
        setup,
        account,
        symbol_spec,
        limits,
        target_risk_pct,
        money_risk_per_lot_override=money_risk_per_lot_override,
    )
    if not isinstance(volume_decision, _SizedVolume):
        reason, detail = volume_decision
        return _reject(reason, detail, checks)
    volume = volume_decision.volume
    actual_risk_pct = volume_decision.actual_risk_pct
    checks.append("volume_sizing")

    if current_exposure.open_risk_pct + actual_risk_pct > limits.max_open_risk_pct + 1e-12:
        return _reject(
            "max_open_risk",
            f"open={current_exposure.open_risk_pct:g} new={actual_risk_pct:g} max={limits.max_open_risk_pct:g}",
            checks,
        )
    checks.append("exposure_limits")

    signal_time = setup_signal_time_utc(setup)
    broker_backstop = broker_backstop_expiration_time_utc(setup, max_entry_wait_bars=max_entry_wait_bars)
    market_time = _market_time_utc(market)
    if market_time is not None and broker_backstop <= market_time:
        return _reject(
            "pending_expired",
            f"broker_backstop_expiration_time_utc={broker_backstop.isoformat()} market_time_utc={market_time.isoformat()}",
            checks + ["expiration"],
        )
    checks.append("expiration")
    intent = MT5OrderIntent(
        signal_key=signal_key,
        symbol=str(setup.symbol).upper(),
        timeframe=str(setup.timeframe).upper(),
        side=setup.side,
        order_type=order_type,
        volume=volume,
        entry_price=_round_price(setup.entry_price, symbol_spec.digits),
        stop_loss=_round_price(setup.stop_price, symbol_spec.digits),
        take_profit=_round_price(setup.target_price, symbol_spec.digits),
        target_risk_pct=target_risk_pct,
        actual_risk_pct=actual_risk_pct,
        expiration_time_utc=broker_backstop,
        magic=limits.strategy_magic,
        comment=_order_comment(setup),
        setup_id=setup.setup_id,
        signal_time_utc=signal_time,
        max_entry_wait_bars=max_entry_wait_bars,
        strategy_expiry_mode="bar_count",
        broker_backstop_expiration_time_utc=broker_backstop,
    )
    return MT5ExecutionDecision(status="ready", intent=intent, checks=tuple(checks))


def _basic_rejection(
    setup: TradeSetup,
    account: MT5AccountSnapshot,
    spec: MT5SymbolExecutionSpec,
    market: MT5MarketSnapshot,
    limits: ExecutionSafetyLimits,
    exposure: ExistingStrategyExposure,
    signal_key: str,
) -> tuple[str, str] | None:
    if str(setup.symbol).upper() != str(spec.symbol).upper():
        return "symbol_mismatch", f"setup={setup.symbol} spec={spec.symbol}"
    if setup.side not in {"long", "short"}:
        return "unsupported_side", f"side={setup.side}"
    if not spec.visible or not spec.trade_allowed:
        return "symbol_not_tradeable", f"visible={spec.visible} trade_allowed={spec.trade_allowed}"
    if account.equity <= 0:
        return "invalid_account_equity", f"equity={account.equity:g}"
    if not _prices_are_finite(setup.entry_price, setup.stop_price, setup.target_price, market.bid, market.ask):
        return "non_finite_price", "Entry, stop, target, bid, and ask must be finite."
    if market.bid >= market.ask:
        return "invalid_market", f"bid={market.bid:g} ask={market.ask:g}"
    spread = _spread_points(market, spec)
    if limits.max_spread_points is not None and spread > limits.max_spread_points:
        return "spread_too_wide", f"spread_points={spread:g} max={limits.max_spread_points:g}"
    if setup.side == "long" and not (setup.stop_price < setup.entry_price < setup.target_price):
        return "invalid_trade_geometry", "Long requires stop < entry < target."
    if setup.side == "short" and not (setup.target_price < setup.entry_price < setup.stop_price):
        return "invalid_trade_geometry", "Short requires target < entry < stop."
    if signal_key in set(exposure.existing_signal_keys):
        return "duplicate_signal", signal_key
    if exposure.same_symbol_positions >= limits.max_same_symbol_stack:
        return "same_symbol_stack_limit", f"same_symbol_positions={exposure.same_symbol_positions}"
    if exposure.total_strategy_positions >= limits.max_concurrent_strategy_trades:
        return "concurrent_trade_limit", f"total_strategy_positions={exposure.total_strategy_positions}"
    return None


def _order_type(setup: TradeSetup, market: MT5MarketSnapshot) -> OrderType | None:
    if setup.side == "long" and setup.entry_price < market.ask:
        return "BUY_LIMIT"
    if setup.side == "short" and setup.entry_price > market.bid:
        return "SELL_LIMIT"
    return None


def _distance_rejection(
    setup: TradeSetup,
    spec: MT5SymbolExecutionSpec,
    market: MT5MarketSnapshot,
    order_type: OrderType,
) -> tuple[str, str] | None:
    min_distance = max(spec.trade_stops_level_points, spec.trade_freeze_level_points, 0) * spec.point
    if min_distance <= 0:
        return None
    market_distance = market.ask - setup.entry_price if order_type == "BUY_LIMIT" else setup.entry_price - market.bid
    if market_distance < min_distance:
        return "pending_too_close", f"distance={market_distance:g} min={min_distance:g}"
    stop_distance = abs(setup.entry_price - setup.stop_price)
    target_distance = abs(setup.target_price - setup.entry_price)
    if stop_distance < min_distance or target_distance < min_distance:
        return "sl_tp_too_close", f"stop_distance={stop_distance:g} target_distance={target_distance:g} min={min_distance:g}"
    return None


def _sized_volume(
    setup: TradeSetup,
    account: MT5AccountSnapshot,
    spec: MT5SymbolExecutionSpec,
    limits: ExecutionSafetyLimits,
    target_risk_pct: float,
    *,
    money_risk_per_lot_override: float | None = None,
) -> _SizedVolume | tuple[str, str]:
    if spec.volume_step <= 0 or spec.volume_min <= 0 or spec.volume_max <= 0:
        return "invalid_volume_spec", "volume_min, volume_max, and volume_step must be positive."
    if money_risk_per_lot_override is None:
        try:
            risk_per_lot = money_risk_per_lot(setup, spec)
        except ValueError as exc:
            return "invalid_symbol_value", str(exc)
    else:
        risk_per_lot = float(money_risk_per_lot_override)
        if risk_per_lot <= 0 or not math.isfinite(risk_per_lot):
            return "invalid_symbol_value", f"money_risk_per_lot_override={risk_per_lot:g}"

    risk_money = account.equity * target_risk_pct / 100.0
    raw_volume = risk_money / risk_per_lot
    cap = spec.volume_max
    if limits.max_lots_per_order is not None:
        cap = min(cap, limits.max_lots_per_order)
    bounded = min(raw_volume, cap)
    volume = _round_volume_down(bounded, spec.volume_step)
    if volume < spec.volume_min:
        return "volume_below_min", f"raw_volume={raw_volume:g} rounded_volume={volume:g} min={spec.volume_min:g}"
    actual_risk_pct = volume * risk_per_lot / account.equity * 100.0
    return _SizedVolume(volume=volume, actual_risk_pct=actual_risk_pct)


def _spread_points(market: MT5MarketSnapshot, spec: MT5SymbolExecutionSpec) -> float:
    if market.spread_points is not None:
        return float(market.spread_points)
    return (float(market.ask) - float(market.bid)) / float(spec.point)


def _market_time_utc(market: MT5MarketSnapshot) -> pd.Timestamp | None:
    if market.time_utc is None:
        return None
    timestamp = pd.Timestamp(market.time_utc)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _prices_are_finite(*prices: float) -> bool:
    return all(math.isfinite(float(price)) for price in prices)


def _round_price(price: float, digits: int) -> float:
    return round(float(price), int(digits))


def _round_volume_down(volume: float, step: float) -> float:
    units = math.floor(float(volume) / float(step) + 1e-12)
    return units * float(step)


def _order_comment(setup: TradeSetup) -> str:
    signal_index = "na" if setup.signal_index is None else str(setup.signal_index)
    return f"LPFS {str(setup.timeframe).upper()} {setup.side[0].upper()} {signal_index}"[:31]


def _reject(reason: str, detail: str, checks: list[str]) -> MT5ExecutionDecision:
    return MT5ExecutionDecision(
        status="rejected",
        rejection_reason=reason,
        detail=detail,
        checks=tuple(checks),
    )
