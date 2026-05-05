"""Live MT5 pending-order lifecycle executor for LP + Force Strike."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Iterable, Sequence

import pandas as pd

from backtest_engine_lab import TradeSetup

from .dry_run_executor import (
    DryRunLocalConfig,
    DryRunSettings,
    LocalConfigError,
    OrderCheckOutcome,
    SetupProvider,
    account_snapshot_from_mt5,
    append_audit_event,
    append_market_snapshot,
    broker_time_epoch_to_utc,
    build_order_check_request,
    default_setup_provider,
    deliver_notification_best_effort,
    fetch_closed_candles,
    load_dry_run_settings,
    market_snapshot_from_mt5,
    mt5_timeframe_constant,
    require_mt5_credentials,
    run_order_check,
    symbol_spec_from_mt5,
)
from .execution_contract import (
    ExistingStrategyExposure,
    ExecutionSafetyLimits,
    MT5MarketSnapshot,
    MT5OrderIntent,
    MT5SymbolExecutionSpec,
    broker_backstop_expiration_time_utc,
    build_mt5_order_intent,
    signal_key_for_setup,
    setup_signal_time_utc,
    timeframe_delta,
)
from .experiment import SkippedTrade
from .notifications import (
    NotificationEvent,
    TelegramNotifier,
    format_notification_message,
    notification_from_execution_decision,
)


LIVE_SEND_ACK = "I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"
LIVE_SEND_MODE = "LIVE_SEND"
TRADE_RETCODE_CLIENT_DISABLES_AT = 10027


@dataclass(frozen=True)
class LiveSendExecutorConfig:
    """Non-secret settings for real MT5 pending-order execution."""

    execution_mode: str = "DRY_RUN"
    live_send_enabled: bool = False
    real_money_ack: str = ""
    symbols: tuple[str, ...] = ("EURUSD",)
    timeframes: tuple[str, ...] = ("H4", "H8", "H12", "D1", "W1")
    broker_timezone: str = "UTC"
    history_bars: int = 300
    journal_path: str = "data/live/lpfs_live_journal.jsonl"
    state_path: str = "data/live/lpfs_live_state.json"
    max_lots_per_order: float | None = None
    risk_bucket_scale: float = 0.05
    max_open_risk_pct: float = 0.65
    max_same_symbol_stack: int = 4
    max_concurrent_strategy_trades: int = 17
    strategy_magic: int = 131500
    pivot_strength: int = 3
    max_bars_from_lp_break: int = 6
    require_lp_pivot_before_fs_mother: bool = True
    max_entry_wait_bars: int = 6
    max_spread_risk_fraction: float = 0.10
    market_recovery_mode: str = "better_than_entry_only"
    market_recovery_deviation_points: int = 0
    history_lookback_days: int = 30

    def safe_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveSendSettings:
    """Resolved local MT5/Telegram config plus live-send settings."""

    local: DryRunLocalConfig
    executor: LiveSendExecutorConfig

    def safe_dict(self) -> dict[str, Any]:
        return {"local": self.local.safe_dict(), "executor": self.executor.safe_dict()}


@dataclass(frozen=True)
class LiveTrackedOrder:
    """Pending order tracked locally for restart-safe reconciliation."""

    signal_key: str
    order_ticket: int
    symbol: str
    timeframe: str
    side: str
    order_type: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    target_risk_pct: float
    actual_risk_pct: float
    expiration_time_utc: str
    magic: int
    comment: str
    setup_id: str
    placed_time_utc: str
    price_digits: int | None = None
    signal_time_utc: str | None = None
    max_entry_wait_bars: int = 6
    strategy_expiry_mode: str = "bar_count"
    broker_backstop_expiration_time_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LiveTrackedOrder":
        values = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        values.setdefault("price_digits", None)
        values.setdefault("signal_time_utc", _signal_time_from_signal_key(str(payload.get("signal_key", ""))))
        values.setdefault("max_entry_wait_bars", 6)
        values.setdefault("strategy_expiry_mode", "bar_count")
        values.setdefault("broker_backstop_expiration_time_utc", None)
        return cls(**values)


@dataclass(frozen=True)
class LiveTrackedPosition:
    """Open position tracked locally after MT5 fills a pending order."""

    signal_key: str
    position_id: int
    order_ticket: int
    symbol: str
    timeframe: str
    side: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    target_risk_pct: float
    actual_risk_pct: float
    opened_time_utc: str
    magic: int
    comment: str
    setup_id: str
    price_digits: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LiveTrackedPosition":
        values = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        values.setdefault("price_digits", None)
        return cls(**values)


@dataclass(frozen=True)
class LiveExecutorState:
    """Restart-safe live state for idempotency and lifecycle alerts."""

    processed_signal_keys: tuple[str, ...] = ()
    order_checked_signal_keys: tuple[str, ...] = ()
    pending_orders: tuple[LiveTrackedOrder, ...] = ()
    active_positions: tuple[LiveTrackedPosition, ...] = ()
    notified_event_keys: tuple[str, ...] = ()
    last_seen_close_ticket: int | None = None
    last_seen_close_time_utc: str | None = None
    telegram_message_ids: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed_signal_keys": list(self.processed_signal_keys),
            "order_checked_signal_keys": list(self.order_checked_signal_keys),
            "pending_orders": [order.to_dict() for order in self.pending_orders],
            "active_positions": [position.to_dict() for position in self.active_positions],
            "notified_event_keys": list(self.notified_event_keys),
            "last_seen_close_ticket": self.last_seen_close_ticket,
            "last_seen_close_time_utc": self.last_seen_close_time_utc,
            "telegram_message_ids": dict(self.telegram_message_ids),
        }


@dataclass(frozen=True)
class DynamicSpreadGate:
    """Result of comparing current spread with setup risk distance."""

    passed: bool
    spread_points: float | None
    spread_price: float
    risk_price: float
    spread_risk_fraction: float
    max_spread_risk_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissedEntryCheck:
    """Whether the pullback entry was already touched before live placement."""

    checked: bool
    missed: bool
    bars_checked: int = 0
    first_touch_time_utc: str | None = None
    first_touch_high: float | None = None
    first_touch_low: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketRecoveryCheck:
    """Whether a missed pending entry can be recovered with a live market order."""

    checked: bool
    recoverable: bool
    status: str
    original_entry: float
    fill_price: float | None = None
    stop_loss: float | None = None
    original_take_profit: float | None = None
    recalculated_take_profit: float | None = None
    spread_risk_fraction: float | None = None
    max_spread_risk_fraction: float | None = None
    first_touch_time_utc: str | None = None
    first_touch_high: float | None = None
    first_touch_low: float | None = None
    stop_touched_time_utc: str | None = None
    stop_touched_high: float | None = None
    stop_touched_low: float | None = None
    target_touched_time_utc: str | None = None
    target_touched_high: float | None = None
    target_touched_low: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PendingBarExpiryCheck:
    """Actual-bar expiry state for a live pending order."""

    checked: bool
    expired: bool
    bars_after_signal: int = 0
    max_entry_wait_bars: int = 6
    signal_time_utc: str | None = None
    first_expired_bar_time_utc: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveOrderSendOutcome:
    """Result of calling MT5 order_send for a pending order."""

    sent: bool
    request: dict[str, Any]
    retcode: int | None
    comment: str
    order_ticket: int | None = None
    deal_ticket: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveCloseEvent:
    """Broker close deal normalized for TP/SL Telegram reporting."""

    ticket: int
    position_id: int
    close_reason: str
    close_time_utc: str
    close_price: float
    close_profit: float
    close_comment: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveSetupResult:
    """Result of processing one setup through the live-send path."""

    state: LiveExecutorState
    signal_key: str
    status: str
    order_check: OrderCheckOutcome | None = None
    order_send: LiveOrderSendOutcome | None = None


@dataclass(frozen=True)
class LiveCycleResult:
    """Summary of one finite live-send polling cycle."""

    state: LiveExecutorState
    frames_processed: int
    orders_sent: int
    setups_rejected: int
    setups_blocked: int = 0


def load_live_send_settings(path: str | Path = "config.local.json", *, env: dict[str, str] | None = None) -> LiveSendSettings:
    """Load live-send settings from ignored local config."""

    dry_settings = load_dry_run_settings(path, env=env)
    config_path = Path(path)
    payload: dict[str, Any] = {}
    if config_path.exists():
        payload = dict(json.loads(config_path.read_text(encoding="utf-8-sig")))
    base_dir = config_path.parent if config_path.parent != Path("") else Path(".")
    live_payload = dict(payload.get("live_send", {}) or {})
    dry_executor = dry_settings.executor

    executor = LiveSendExecutorConfig(
        execution_mode=str(live_payload.get("execution_mode", "DRY_RUN")),
        live_send_enabled=bool(live_payload.get("live_send_enabled", False)),
        real_money_ack=str(live_payload.get("real_money_ack", "")),
        symbols=_tuple_of_strings(live_payload.get("symbols"), dry_executor.symbols),
        timeframes=_tuple_of_strings(live_payload.get("timeframes"), dry_executor.timeframes),
        broker_timezone=str(live_payload.get("broker_timezone", dry_executor.broker_timezone)),
        history_bars=int(live_payload.get("history_bars", dry_executor.history_bars)),
        journal_path=str(_resolve_local_path(base_dir, live_payload.get("journal_path", "data/live/lpfs_live_journal.jsonl"))),
        state_path=str(_resolve_local_path(base_dir, live_payload.get("state_path", "data/live/lpfs_live_state.json"))),
        max_lots_per_order=_optional_float(live_payload.get("max_lots_per_order", dry_executor.max_lots_per_order)),
        risk_bucket_scale=float(live_payload.get("risk_bucket_scale", 0.05)),
        max_open_risk_pct=float(live_payload.get("max_open_risk_pct", 0.65)),
        max_same_symbol_stack=int(live_payload.get("max_same_symbol_stack", dry_executor.max_same_symbol_stack)),
        max_concurrent_strategy_trades=int(
            live_payload.get("max_concurrent_strategy_trades", dry_executor.max_concurrent_strategy_trades)
        ),
        strategy_magic=int(live_payload.get("strategy_magic", dry_executor.strategy_magic)),
        pivot_strength=int(live_payload.get("pivot_strength", dry_executor.pivot_strength)),
        max_bars_from_lp_break=int(live_payload.get("max_bars_from_lp_break", dry_executor.max_bars_from_lp_break)),
        require_lp_pivot_before_fs_mother=_optional_bool(
            live_payload.get(
                "require_lp_pivot_before_fs_mother",
                dry_executor.require_lp_pivot_before_fs_mother,
            ),
            default=True,
        ),
        max_entry_wait_bars=int(live_payload.get("max_entry_wait_bars", dry_executor.max_entry_wait_bars)),
        max_spread_risk_fraction=float(live_payload.get("max_spread_risk_fraction", 0.10)),
        market_recovery_mode=str(live_payload.get("market_recovery_mode", "better_than_entry_only")),
        market_recovery_deviation_points=int(live_payload.get("market_recovery_deviation_points", 0)),
        history_lookback_days=int(live_payload.get("history_lookback_days", 30)),
    )
    return LiveSendSettings(local=dry_settings.local, executor=executor)


def validate_live_send_settings(settings: LiveSendSettings) -> None:
    """Fail closed unless real-order mode is explicitly acknowledged."""

    require_mt5_credentials(settings.local)
    config = settings.executor
    if config.execution_mode != LIVE_SEND_MODE:
        raise LocalConfigError("Live order sending requires live_send.execution_mode='LIVE_SEND'.")
    if not config.live_send_enabled:
        raise LocalConfigError("Live order sending requires live_send.live_send_enabled=true.")
    if config.real_money_ack != LIVE_SEND_ACK:
        raise LocalConfigError(f"Live order sending requires live_send.real_money_ack='{LIVE_SEND_ACK}'.")
    if config.risk_bucket_scale <= 0:
        raise LocalConfigError("live_send.risk_bucket_scale must be positive.")
    if config.max_open_risk_pct <= 0:
        raise LocalConfigError("live_send.max_open_risk_pct must be positive.")
    if not (0 < config.max_spread_risk_fraction <= 1):
        raise LocalConfigError("live_send.max_spread_risk_fraction must be between 0 and 1.")
    if config.market_recovery_mode not in {"better_than_entry_only", "disabled"}:
        raise LocalConfigError("live_send.market_recovery_mode must be 'better_than_entry_only' or 'disabled'.")
    if config.market_recovery_deviation_points < 0:
        raise LocalConfigError("live_send.market_recovery_deviation_points must be zero or positive.")


def load_live_state(path: str | Path) -> LiveExecutorState:
    state_path = Path(path)
    if not state_path.exists():
        return LiveExecutorState()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    state = LiveExecutorState(
        processed_signal_keys=tuple(payload.get("processed_signal_keys", ())),
        order_checked_signal_keys=tuple(payload.get("order_checked_signal_keys", ())),
        pending_orders=tuple(LiveTrackedOrder.from_dict(item) for item in payload.get("pending_orders", ())),
        active_positions=tuple(LiveTrackedPosition.from_dict(item) for item in payload.get("active_positions", ())),
        notified_event_keys=tuple(payload.get("notified_event_keys", ())),
        last_seen_close_ticket=payload.get("last_seen_close_ticket"),
        last_seen_close_time_utc=payload.get("last_seen_close_time_utc"),
        telegram_message_ids={
            str(key): int(value)
            for key, value in dict(payload.get("telegram_message_ids", {}) or {}).items()
            if value not in (None, "")
        },
    )
    return state


def save_live_state(path: str | Path, state: LiveExecutorState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2)
    temp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(payload, encoding="utf-8")

    for attempt in range(3):
        try:
            os.replace(temp_path, state_path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))

    # OneDrive can expose synced files as Windows reparse points and reject
    # replacing them even when writing their contents is allowed.
    state_path.write_text(payload, encoding="utf-8")
    try:
        temp_path.unlink()
    except OSError:
        pass


def live_execution_safety_from_config(config: LiveSendExecutorConfig) -> ExecutionSafetyLimits:
    """Return live-send guardrails."""

    return ExecutionSafetyLimits(
        max_open_risk_pct=config.max_open_risk_pct,
        max_lots_per_order=config.max_lots_per_order,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        max_spread_points=None,
        strategy_magic=config.strategy_magic,
    )


def live_risk_buckets_from_config(config: LiveSendExecutorConfig) -> dict[str, float]:
    from .execution_contract import V15_EFFICIENT_RISK_BUCKET_PCT

    if config.risk_bucket_scale <= 0:
        raise ValueError("risk_bucket_scale must be positive.")
    return {timeframe: risk_pct * config.risk_bucket_scale for timeframe, risk_pct in V15_EFFICIENT_RISK_BUCKET_PCT.items()}


def dynamic_spread_gate(
    setup: TradeSetup,
    spec: MT5SymbolExecutionSpec,
    market: MT5MarketSnapshot,
    *,
    max_spread_risk_fraction: float,
) -> DynamicSpreadGate:
    """Require spread to be a small fraction of entry-to-stop distance."""

    spread_price = float(market.ask) - float(market.bid)
    risk_price = abs(float(setup.entry_price) - float(setup.stop_price))
    fraction = float("inf") if risk_price <= 0 else spread_price / risk_price
    spread_points = None if spec.point <= 0 else spread_price / spec.point
    return DynamicSpreadGate(
        passed=spread_price >= 0 and risk_price > 0 and fraction <= max_spread_risk_fraction,
        spread_points=spread_points,
        spread_price=spread_price,
        risk_price=risk_price,
        spread_risk_fraction=fraction,
        max_spread_risk_fraction=max_spread_risk_fraction,
    )


def market_recovery_check(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    market: MT5MarketSnapshot,
    missed_entry: MissedEntryCheck,
    symbol_spec: MT5SymbolExecutionSpec,
) -> MarketRecoveryCheck:
    """Return whether a missed pending entry is recoverable at the current quote."""

    signal_key = signal_key_for_setup(setup)
    original_entry = float(setup.entry_price)
    stop = float(setup.stop_price)
    original_target = float(setup.target_price)
    fill = float(market.ask) if setup.side == "long" else float(market.bid)
    base_fields = {
        "original_entry": original_entry,
        "fill_price": fill,
        "stop_loss": stop,
        "original_take_profit": original_target,
        "first_touch_time_utc": missed_entry.first_touch_time_utc,
        "first_touch_high": missed_entry.first_touch_high,
        "first_touch_low": missed_entry.first_touch_low,
    }
    if not all(math.isfinite(value) for value in (original_entry, fill, stop, original_target)):
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_invalid_price",
            detail=f"non-finite recovery price for {signal_key}",
            **base_fields,
        )

    tolerance = max(abs(float(symbol_spec.point)) / 2.0, 1e-12)
    if setup.side == "long":
        better_or_equal = fill <= original_entry + tolerance
        stop_valid = fill > stop + tolerance
    else:
        better_or_equal = fill >= original_entry - tolerance
        stop_valid = fill < stop - tolerance
    if not better_or_equal:
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_not_better",
            detail="current executable price is worse than the original pending entry",
            **base_fields,
        )
    if not stop_valid:
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_invalid_stop_distance",
            detail="current executable price is not on the valid side of the structural stop",
            **base_fields,
        )

    path_block = _market_recovery_path_block(
        mt5_module,
        setup,
        config=config,
        until_time_utc=market.time_utc,
        from_time_utc=missed_entry.first_touch_time_utc,
    )
    if path_block["status"] == "path_unavailable":
        return MarketRecoveryCheck(
            checked=False,
            recoverable=False,
            status="market_recovery_path_unavailable",
            detail=str(path_block.get("detail", "")),
            **base_fields,
        )
    if path_block["status"] == "stop_touched":
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_stop_touched",
            stop_touched_time_utc=path_block.get("time_utc"),
            stop_touched_high=path_block.get("high"),
            stop_touched_low=path_block.get("low"),
            detail="structural stop traded before market recovery",
            **base_fields,
        )
    if path_block["status"] == "target_touched":
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_target_touched",
            target_touched_time_utc=path_block.get("time_utc"),
            target_touched_high=path_block.get("high"),
            target_touched_low=path_block.get("low"),
            detail="original 1R target traded before market recovery",
            **base_fields,
        )

    recalculated_take_profit = _market_recovery_take_profit(setup.side, fill_price=fill, stop_loss=stop)
    recovery_setup = replace(setup, entry_price=fill, target_price=recalculated_take_profit)
    spread_gate = dynamic_spread_gate(
        recovery_setup,
        symbol_spec,
        market,
        max_spread_risk_fraction=config.max_spread_risk_fraction,
    )
    if not spread_gate.passed:
        return MarketRecoveryCheck(
            checked=True,
            recoverable=False,
            status="market_recovery_spread_too_wide",
            recalculated_take_profit=recalculated_take_profit,
            spread_risk_fraction=spread_gate.spread_risk_fraction,
            max_spread_risk_fraction=spread_gate.max_spread_risk_fraction,
            detail="spread is too large versus actual market fill-to-stop risk",
            **base_fields,
        )
    return MarketRecoveryCheck(
        checked=True,
        recoverable=True,
        status="market_recovery_ready",
        recalculated_take_profit=recalculated_take_profit,
        spread_risk_fraction=spread_gate.spread_risk_fraction,
        max_spread_risk_fraction=spread_gate.max_spread_risk_fraction,
        **base_fields,
    )


def broker_money_risk_per_lot(mt5_module: Any, setup: TradeSetup) -> float:
    """Use MT5 order_calc_profit to get account-currency loss for one lot."""

    order_type = mt5_module.ORDER_TYPE_BUY if setup.side == "long" else mt5_module.ORDER_TYPE_SELL
    result = mt5_module.order_calc_profit(
        order_type,
        str(setup.symbol).upper(),
        1.0,
        float(setup.entry_price),
        float(setup.stop_price),
    )
    if result is None:
        raise RuntimeError(f"order_calc_profit failed for {setup.symbol}.")
    risk = abs(float(result))
    if risk <= 0:
        raise RuntimeError(f"order_calc_profit returned non-positive risk for {setup.symbol}.")
    return risk


def missed_entry_before_placement(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    placed_time_utc: pd.Timestamp | str | None = None,
) -> MissedEntryCheck:
    """Reject late starts when the pending entry already traded before send."""

    raw_signal_time = setup.metadata.get("fs_signal_time_utc")
    if raw_signal_time is None:
        return MissedEntryCheck(checked=False, missed=False, detail="missing fs_signal_time_utc")
    signal_time = _as_utc_timestamp(raw_signal_time)
    placed_time = pd.Timestamp.now(tz="UTC") if placed_time_utc is None else _as_utc_timestamp(placed_time_utc)
    timeframe_constant = mt5_timeframe_constant(mt5_module, setup.timeframe)
    raw_rates = mt5_module.copy_rates_from_pos(setup.symbol, timeframe_constant, 0, int(config.history_bars) + 1)
    if raw_rates is None:
        return MissedEntryCheck(checked=False, missed=False, detail="copy_rates_from_pos returned None")
    frame = pd.DataFrame(raw_rates)
    if frame.empty:
        return MissedEntryCheck(checked=False, missed=False, detail="copy_rates_from_pos returned no rows")
    data = frame.copy()
    data["time_utc"] = [broker_time_epoch_to_utc(raw_time, config.broker_timezone) for raw_time in data["time"].tolist()]
    data = data.sort_values("time_utc")
    after_signal = data[
        (pd.to_datetime(data["time_utc"], utc=True) > signal_time)
        & (pd.to_datetime(data["time_utc"], utc=True) <= placed_time)
    ]
    entry = float(setup.entry_price)
    if setup.side == "short":
        touched = after_signal[after_signal["high"].astype(float) >= entry]
    else:
        touched = after_signal[after_signal["low"].astype(float) <= entry]
    if touched.empty:
        return MissedEntryCheck(checked=True, missed=False, bars_checked=int(len(after_signal)))
    first = touched.iloc[0]
    return MissedEntryCheck(
        checked=True,
        missed=True,
        bars_checked=int(len(after_signal)),
        first_touch_time_utc=pd.Timestamp(first["time_utc"]).isoformat(),
        first_touch_high=float(first["high"]),
        first_touch_low=float(first["low"]),
    )


def setup_bar_expiry_check(mt5_module: Any, setup: TradeSetup, config: LiveSendExecutorConfig) -> PendingBarExpiryCheck:
    """Return whether a setup is already outside its actual MT5-bar entry window."""

    try:
        signal_time = setup_signal_time_utc(setup)
    except ValueError as exc:
        return PendingBarExpiryCheck(checked=False, expired=False, detail=str(exc))
    return _bar_expiry_check(
        mt5_module,
        symbol=str(setup.symbol).upper(),
        timeframe=str(setup.timeframe).upper(),
        signal_time=signal_time,
        max_entry_wait_bars=config.max_entry_wait_bars,
        config=config,
    )


def pending_order_bar_expiry_check(
    mt5_module: Any,
    pending: LiveTrackedOrder,
    config: LiveSendExecutorConfig,
) -> PendingBarExpiryCheck:
    """Return whether a tracked pending order reached the first bar after its wait window."""

    signal_time = _pending_signal_time_utc(pending)
    if signal_time is None:
        return PendingBarExpiryCheck(checked=False, expired=False, detail="missing signal_time_utc")
    return _bar_expiry_check(
        mt5_module,
        symbol=pending.symbol,
        timeframe=pending.timeframe,
        signal_time=signal_time,
        max_entry_wait_bars=int(pending.max_entry_wait_bars or config.max_entry_wait_bars),
        config=config,
    )


def _bar_expiry_check(
    mt5_module: Any,
    *,
    symbol: str,
    timeframe: str,
    signal_time: pd.Timestamp,
    max_entry_wait_bars: int,
    config: LiveSendExecutorConfig,
) -> PendingBarExpiryCheck:
    if max_entry_wait_bars < 1:
        return PendingBarExpiryCheck(checked=False, expired=False, detail="max_entry_wait_bars must be >= 1")
    try:
        data = _fetch_candles_including_current(
            mt5_module,
            symbol=symbol,
            timeframe=timeframe,
            bars=config.history_bars,
            broker_timezone=config.broker_timezone,
        )
    except Exception as exc:
        return PendingBarExpiryCheck(checked=False, expired=False, detail=str(exc))
    if data.empty:
        return PendingBarExpiryCheck(checked=False, expired=False, detail="copy_rates_from_pos returned no rows")

    signal_time = _as_utc_timestamp(signal_time)
    times = pd.to_datetime(data["time_utc"], utc=True)
    after_signal = data.loc[times > signal_time].copy()
    bars_after_signal = int(len(after_signal))
    expired = bars_after_signal > int(max_entry_wait_bars)
    first_expired_bar_time = None
    if expired:
        first_expired_bar_time = pd.Timestamp(after_signal.iloc[int(max_entry_wait_bars)]["time_utc"]).isoformat()
    return PendingBarExpiryCheck(
        checked=True,
        expired=expired,
        bars_after_signal=bars_after_signal,
        max_entry_wait_bars=int(max_entry_wait_bars),
        signal_time_utc=signal_time.isoformat(),
        first_expired_bar_time_utc=first_expired_bar_time,
    )


def _fetch_candles_including_current(
    mt5_module: Any,
    *,
    symbol: str,
    timeframe: str,
    bars: int,
    broker_timezone: str,
) -> pd.DataFrame:
    timeframe_constant = mt5_timeframe_constant(mt5_module, timeframe)
    raw_rates = mt5_module.copy_rates_from_pos(symbol, timeframe_constant, 0, int(bars) + 1)
    if raw_rates is None:
        raise RuntimeError(f"copy_rates_from_pos failed for {symbol} {timeframe}.")
    frame = pd.DataFrame(raw_rates)
    if frame.empty:
        return pd.DataFrame(columns=("time_utc",))
    data = frame.copy()
    data["time_utc"] = [broker_time_epoch_to_utc(raw_time, broker_timezone) for raw_time in data["time"].tolist()]
    data = data.dropna(subset=["time_utc"]).sort_values("time_utc").reset_index(drop=True)
    return data


def _market_recovery_path_block(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    until_time_utc: pd.Timestamp | str | None,
    from_time_utc: pd.Timestamp | str | None = None,
) -> dict[str, Any]:
    try:
        signal_time = setup_signal_time_utc(setup)
        data = _fetch_candles_including_current(
            mt5_module,
            symbol=str(setup.symbol).upper(),
            timeframe=str(setup.timeframe).upper(),
            bars=config.history_bars,
            broker_timezone=config.broker_timezone,
        )
    except Exception as exc:
        return {"status": "path_unavailable", "detail": str(exc)}
    if data.empty:
        return {"status": "path_unavailable", "detail": "copy_rates_from_pos returned no rows"}

    until_time = pd.Timestamp.now(tz="UTC") if until_time_utc is None else _as_utc_timestamp(until_time_utc)
    times = pd.to_datetime(data["time_utc"], utc=True)
    if from_time_utc is None:
        after_signal = data.loc[(times > signal_time) & (times <= until_time)].copy()
    else:
        from_time = _as_utc_timestamp(from_time_utc)
        after_signal = data.loc[(times >= from_time) & (times <= until_time)].copy()
    if after_signal.empty:
        return {"status": "clear"}

    high = after_signal["high"].astype(float)
    low = after_signal["low"].astype(float)
    stop = float(setup.stop_price)
    target = float(setup.target_price)
    if setup.side == "long":
        stop_hits = after_signal.loc[low <= stop]
        target_hits = after_signal.loc[high >= target]
    else:
        stop_hits = after_signal.loc[high >= stop]
        target_hits = after_signal.loc[low <= target]
    first_stop = _first_touch_row(stop_hits)
    first_target = _first_touch_row(target_hits)
    if first_stop is not None and (first_target is None or pd.Timestamp(first_stop["time_utc"]) <= pd.Timestamp(first_target["time_utc"])):
        return {"status": "stop_touched", **first_stop}
    if first_target is not None:
        return {"status": "target_touched", **first_target}
    return {"status": "clear"}


def _first_touch_row(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    first = frame.iloc[0]
    return {
        "time_utc": pd.Timestamp(first["time_utc"]).isoformat(),
        "high": float(first["high"]),
        "low": float(first["low"]),
    }


def _market_recovery_take_profit(side: str, *, fill_price: float, stop_loss: float) -> float:
    risk = abs(float(fill_price) - float(stop_loss))
    if side == "short":
        return float(fill_price) - risk
    return float(fill_price) + risk


def _pending_signal_time_utc(pending: LiveTrackedOrder) -> pd.Timestamp | None:
    if pending.signal_time_utc:
        return _as_utc_timestamp(pending.signal_time_utc)
    parsed = _signal_time_from_signal_key(pending.signal_key)
    if parsed:
        return _as_utc_timestamp(parsed)
    try:
        return _as_utc_timestamp(pending.expiration_time_utc) - timeframe_delta(pending.timeframe) * (
            int(pending.max_entry_wait_bars or 6) + 1
        )
    except Exception:
        return None


def _signal_time_from_signal_key(signal_key: str) -> str | None:
    parts = str(signal_key).split(":", 6)
    if len(parts) == 7 and parts[0] == "lpfs":
        return parts[6]
    return None


def _broker_backstop_elapsed(pending: LiveTrackedOrder) -> bool:
    if not pending.broker_backstop_expiration_time_utc:
        return False
    return _as_utc_timestamp(pending.broker_backstop_expiration_time_utc) <= pd.Timestamp.now(tz="UTC")


def send_pending_order(mt5_module: Any, intent: MT5OrderIntent) -> LiveOrderSendOutcome:
    """Send a validated MT5 pending order request."""

    request = build_order_check_request(mt5_module, intent)
    result = mt5_module.order_send(request)
    retcode = None if result is None else getattr(result, "retcode", None)
    comment = "order_send returned None" if result is None else str(getattr(result, "comment", "") or "")
    order_ticket = None if result is None else _optional_int(getattr(result, "order", None))
    deal_ticket = None if result is None else _optional_int(getattr(result, "deal", None))
    accepted_retcodes = _accepted_send_retcodes(mt5_module)
    sent = result is not None and retcode is not None and int(retcode) in accepted_retcodes and order_ticket is not None
    return LiveOrderSendOutcome(
        sent=sent,
        request=request,
        retcode=retcode,
        comment=comment,
        order_ticket=order_ticket,
        deal_ticket=deal_ticket,
    )


def _dedupe_filling_modes(values: list[Any]) -> list[Any]:
    seen: set[int] = set()
    deduped: list[Any] = []
    for value in values:
        if value is None:
            continue
        try:
            key = int(value)
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _market_order_filling_candidates(mt5_module: Any, symbol: str) -> list[Any]:
    """Return fill modes to try for market-recovery DEAL requests."""

    symbol_info = getattr(mt5_module, "symbol_info", lambda _symbol: None)(symbol)
    filling_mode = getattr(symbol_info, "filling_mode", None)
    candidates: list[Any] = []

    def add_order_filling(name: str) -> None:
        if hasattr(mt5_module, name):
            candidates.append(getattr(mt5_module, name))

    if filling_mode is not None:
        try:
            mode_flags = int(filling_mode)
        except (TypeError, ValueError):
            mode_flags = 0
        ioc_flag = int(getattr(mt5_module, "SYMBOL_FILLING_IOC", 2))
        fok_flag = int(getattr(mt5_module, "SYMBOL_FILLING_FOK", 1))
        if mode_flags & ioc_flag:
            add_order_filling("ORDER_FILLING_IOC")
        if mode_flags & fok_flag:
            add_order_filling("ORDER_FILLING_FOK")

    add_order_filling("ORDER_FILLING_IOC")
    add_order_filling("ORDER_FILLING_FOK")
    add_order_filling("ORDER_FILLING_RETURN")
    return _dedupe_filling_modes(candidates)


def build_market_order_request(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    deviation_points: int = 0,
    filling_mode: Any | None = None,
) -> dict[str, Any]:
    """Translate a market-recovery intent to an MT5 TRADE_ACTION_DEAL request."""

    order_type = getattr(mt5_module, "ORDER_TYPE_BUY") if intent.side == "long" else getattr(mt5_module, "ORDER_TYPE_SELL")
    request = {
        "action": mt5_module.TRADE_ACTION_DEAL,
        "symbol": intent.symbol,
        "volume": intent.volume,
        "type": order_type,
        "price": intent.entry_price,
        "sl": intent.stop_loss,
        "tp": intent.take_profit,
        "deviation": int(deviation_points),
        "magic": intent.magic,
        "comment": intent.comment,
    }
    if filling_mode is None:
        candidates = _market_order_filling_candidates(mt5_module, intent.symbol)
        filling_mode = candidates[0] if candidates else None
    if filling_mode is not None:
        request["type_filling"] = filling_mode
    return request


def _unsupported_filling_mode(mt5_module: Any, outcome: OrderCheckOutcome) -> bool:
    invalid_fill_retcode = getattr(mt5_module, "TRADE_RETCODE_INVALID_FILL", 10030)
    try:
        retcode_matches = outcome.retcode is not None and int(outcome.retcode) == int(invalid_fill_retcode)
    except (TypeError, ValueError):
        retcode_matches = False
    comment = str(outcome.comment or "").lower()
    return retcode_matches or "unsupported filling mode" in comment or "invalid fill" in comment


def run_market_order_check(mt5_module: Any, intent: MT5OrderIntent, *, deviation_points: int = 0) -> OrderCheckOutcome:
    """Run MT5 order_check for a market-recovery DEAL request."""

    filling_modes = _market_order_filling_candidates(mt5_module, intent.symbol)
    attempts = filling_modes or [None]
    last_outcome: OrderCheckOutcome | None = None
    for filling_mode in attempts:
        request = build_market_order_request(mt5_module, intent, deviation_points=deviation_points, filling_mode=filling_mode)
        result = mt5_module.order_check(request)
        retcode = None if result is None else getattr(result, "retcode", None)
        comment = "order_check returned None" if result is None else str(getattr(result, "comment", "") or "")
        passed = result is not None and retcode is not None and int(retcode) in _accepted_done_retcodes(mt5_module)
        outcome = OrderCheckOutcome(passed=passed, request=request, retcode=retcode, comment=comment)
        if passed:
            return outcome
        last_outcome = outcome
        if not _unsupported_filling_mode(mt5_module, outcome):
            return outcome
    return last_outcome


def _market_send_request(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    deviation_points: int,
    checked_request: dict[str, Any] | None,
) -> dict[str, Any]:
    if checked_request is not None:
        return dict(checked_request)
    return build_market_order_request(mt5_module, intent, deviation_points=deviation_points)


def send_market_recovery_order(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    deviation_points: int = 0,
    checked_request: dict[str, Any] | None = None,
) -> LiveOrderSendOutcome:
    """Send a validated MT5 market-recovery order request."""

    request = _market_send_request(mt5_module, intent, deviation_points=deviation_points, checked_request=checked_request)
    result = mt5_module.order_send(request)
    retcode = None if result is None else getattr(result, "retcode", None)
    comment = "order_send returned None" if result is None else str(getattr(result, "comment", "") or "")
    order_ticket = None if result is None else _optional_int(getattr(result, "order", None))
    deal_ticket = None if result is None else _optional_int(getattr(result, "deal", None))
    sent = result is not None and retcode is not None and int(retcode) in _accepted_done_retcodes(mt5_module) and (
        order_ticket is not None or deal_ticket is not None
    )
    return LiveOrderSendOutcome(
        sent=sent,
        request=request,
        retcode=retcode,
        comment=comment,
        order_ticket=order_ticket,
        deal_ticket=deal_ticket,
    )


def cancel_pending_order(mt5_module: Any, order: LiveTrackedOrder) -> LiveOrderSendOutcome:
    """Remove one stale pending order from MT5."""

    request = {
        "action": mt5_module.TRADE_ACTION_REMOVE,
        "order": order.order_ticket,
        "symbol": order.symbol,
        "magic": order.magic,
        "comment": order.comment,
    }
    result = mt5_module.order_send(request)
    retcode = None if result is None else getattr(result, "retcode", None)
    comment = "order_send returned None" if result is None else str(getattr(result, "comment", "") or "")
    sent = result is not None and retcode is not None and int(retcode) in _accepted_done_retcodes(mt5_module)
    return LiveOrderSendOutcome(sent=sent, request=request, retcode=retcode, comment=comment)


def _process_market_recovery_live_send(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    account: Any,
    symbol_spec: MT5SymbolExecutionSpec,
    missed_entry: MissedEntryCheck,
    bar_expiry: PendingBarExpiryCheck,
    notifier: TelegramNotifier | None,
) -> LiveSetupResult:
    signal_key = signal_key_for_setup(setup)
    base_fields = {
        **missed_entry.to_dict(),
        "original_entry": float(setup.entry_price),
        "stop_loss": float(setup.stop_price),
        "original_take_profit": float(setup.target_price),
        "market_recovery_mode": config.market_recovery_mode,
    }
    if config.market_recovery_mode == "disabled":
        event = _rejection_event(
            "entry_already_touched_before_placement",
            "The pullback entry traded before the live pending order could be placed.",
            signal_key,
            base_fields,
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:missed_entry", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    if bar_expiry.expired:
        event = _rejection_event(
            "pending_expired",
            "The pullback window expired by actual MT5 bar count before market recovery.",
            signal_key,
            {**base_fields, **bar_expiry.to_dict()},
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:bar_expired", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    recovery_market = market_snapshot_from_mt5(mt5_module, setup.symbol, broker_timezone=config.broker_timezone)
    recovery_check = market_recovery_check(
        mt5_module,
        setup,
        config=config,
        market=recovery_market,
        missed_entry=missed_entry,
        symbol_spec=symbol_spec,
    )
    if not recovery_check.checked:
        event = _rejection_event(
            recovery_check.status,
            recovery_check.detail or "Could not verify market recovery path.",
            signal_key,
            recovery_check.to_dict(),
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:market_recovery_unavailable", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")
    if not recovery_check.recoverable:
        event = _rejection_event(
            recovery_check.status,
            recovery_check.detail or "Missed pending entry is not eligible for market recovery.",
            signal_key,
            recovery_check.to_dict(),
        )
        retryable_statuses = {
            "market_recovery_not_better",
            "market_recovery_spread_too_wide",
        }
        if recovery_check.status in retryable_statuses:
            retry_reason = (
                "market_recovery_price"
                if recovery_check.status == "market_recovery_not_better"
                else "market_recovery_spread"
            )
            next_state = _record_event_once(config, state, notifier, f"setup_blocked:{signal_key}:{retry_reason}", event)
            return LiveSetupResult(state=next_state, signal_key=signal_key, status="blocked")
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:{recovery_check.status}", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    intent, risk_per_lot, rejection = _build_market_recovery_intent(
        mt5_module,
        setup,
        config=config,
        state=state,
        account=account,
        symbol_spec=symbol_spec,
        recovery_check=recovery_check,
    )
    if rejection is not None or intent is None:
        event = rejection or _rejection_event(
            "market_recovery_intent_failed",
            "Market recovery intent could not be built.",
            signal_key,
            recovery_check.to_dict(),
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:market_recovery_intent", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    append_audit_event(
        config.journal_path,
        "market_recovery_intent_created",
        signal_key=signal_key,
        recovery_check=recovery_check.to_dict(),
        intent=intent.to_dict(),
        broker_money_risk_per_lot=risk_per_lot,
    )
    processed_state = _with_processed_key(state, signal_key)
    order_check = run_market_order_check(
        mt5_module,
        intent,
        deviation_points=config.market_recovery_deviation_points,
    )
    checked_state = _with_checked_key(processed_state, signal_key)
    if not order_check.passed:
        event = NotificationEvent(
            kind="order_check_failed",
            mode="LIVE",
            title="MT5 rejected live market recovery check",
            severity="warning",
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            side=intent.side,
            status="failed",
            signal_key=signal_key,
            fields={
                "retcode": order_check.retcode,
                "comment": order_check.comment,
                "execution_type": "market_recovery",
                **recovery_check.to_dict(),
            },
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"market_recovery_check_failed:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_check_failed", order_check=order_check)

    outcome = send_market_recovery_order(
        mt5_module,
        intent,
        deviation_points=config.market_recovery_deviation_points,
        checked_request=order_check.request,
    )
    if not outcome.sent:
        if _is_retryable_order_send_block(outcome):
            event = _rejection_event(
                "autotrading_disabled",
                "MT5 AutoTrading is disabled by the client terminal.",
                signal_key,
                {
                    "retcode": outcome.retcode,
                    "comment": outcome.comment,
                    "execution_type": "market_recovery",
                    **recovery_check.to_dict(),
                },
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:autotrading_disabled", event)
            return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check, order_send=outcome)
        event = NotificationEvent(
            kind="order_rejected",
            mode="LIVE",
            title="Live market recovery order rejected",
            severity="warning",
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            side=intent.side,
            status="rejected",
            signal_key=signal_key,
            fields={
                "retcode": outcome.retcode,
                "comment": outcome.comment,
                "execution_type": "market_recovery",
                **recovery_check.to_dict(),
            },
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"market_recovery_rejected:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_rejected", order_check=order_check, order_send=outcome)

    position = _matching_broker_position_for_intent(mt5_module, intent, config, symbol_spec)
    if position is None:
        position = _fallback_market_recovery_position(mt5_module, intent, outcome, config)
    tracked_position = _tracked_position_from_intent(intent, position, config, price_digits=symbol_spec.digits)
    next_state = replace(checked_state, active_positions=(*checked_state.active_positions, tracked_position))
    save_live_state(config.state_path, next_state)
    event = _market_recovery_sent_event(tracked_position, outcome, recovery_check)
    thread_key = f"order:{tracked_position.order_ticket}"
    next_state = _record_event_once(
        config,
        next_state,
        notifier,
        f"market_recovery_sent:{tracked_position.position_id}:{outcome.deal_ticket or outcome.order_ticket or 0}",
        event,
        store_thread_key=thread_key,
    )
    return LiveSetupResult(state=next_state, signal_key=signal_key, status="market_recovery_sent", order_check=order_check, order_send=outcome)


def process_trade_setup_live_send(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    market: MT5MarketSnapshot | None = None,
    notifier: TelegramNotifier | None = None,
) -> LiveSetupResult:
    """Validate, broker-check, and send one real live setup order."""

    signal_key = signal_key_for_setup(setup)
    if signal_key in state.processed_signal_keys:
        append_audit_event(config.journal_path, "signal_already_processed", signal_key=signal_key)
        return LiveSetupResult(state=state, signal_key=signal_key, status="already_processed")

    account = account_snapshot_from_mt5(mt5_module)
    symbol_spec = symbol_spec_from_mt5(mt5_module, setup.symbol)
    first_market = market or market_snapshot_from_mt5(mt5_module, setup.symbol, broker_timezone=config.broker_timezone)
    missed_entry = missed_entry_before_placement(mt5_module, setup, config=config)
    if not missed_entry.checked:
        event = _rejection_event(
            "missed_entry_check_unavailable",
            "Could not confirm whether the pullback entry was already touched before live placement.",
            signal_key,
            missed_entry.to_dict(),
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:missed_entry_unavailable", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    bar_expiry = setup_bar_expiry_check(mt5_module, setup, config)
    if not bar_expiry.checked:
        event = _rejection_event(
            "bar_expiry_check_unavailable",
            "Could not confirm the live pending order is still inside the actual-bar pullback window.",
            signal_key,
            bar_expiry.to_dict(),
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:bar_expiry_unavailable", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")
    if missed_entry.missed:
        return _process_market_recovery_live_send(
            mt5_module,
            setup,
            config=config,
            state=state,
            account=account,
            symbol_spec=symbol_spec,
            missed_entry=missed_entry,
            bar_expiry=bar_expiry,
            notifier=notifier,
        )

    if bar_expiry.expired:
        event = _rejection_event(
            "pending_expired",
            "The pullback window expired by actual MT5 bar count before live placement.",
            signal_key,
            bar_expiry.to_dict(),
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:bar_expired", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    pre_spread = dynamic_spread_gate(
        setup,
        symbol_spec,
        first_market,
        max_spread_risk_fraction=config.max_spread_risk_fraction,
    )
    if not pre_spread.passed:
        event = _rejection_event("spread_too_wide", "Spread is too large versus setup risk.", signal_key, pre_spread.to_dict())
        next_state = _record_event_once(config, state, notifier, f"setup_blocked:{signal_key}:spread", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="blocked")

    risk_per_lot = broker_money_risk_per_lot(mt5_module, setup)
    decision = build_mt5_order_intent(
        setup,
        account=account,
        symbol_spec=symbol_spec,
        market=first_market,
        safety=live_execution_safety_from_config(config),
        exposure=_exposure_from_state(state, setup.symbol),
        risk_buckets=live_risk_buckets_from_config(config),
        max_entry_wait_bars=config.max_entry_wait_bars,
        money_risk_per_lot_override=risk_per_lot,
    )
    decision_event = notification_from_execution_decision(decision, mode="LIVE")
    append_audit_event(
        config.journal_path,
        decision_event.kind,
        signal_key=signal_key,
        notification=format_notification_message(decision_event),
        decision=decision.to_dict(),
        broker_money_risk_per_lot=risk_per_lot,
    )
    processed_state = _with_processed_key(state, signal_key)
    if not decision.ready or decision.intent is None:
        processed_state = _record_event_once(config, processed_state, notifier, f"setup_rejected:{signal_key}", decision_event)
        return LiveSetupResult(state=processed_state, signal_key=signal_key, status="rejected")

    order_check = run_order_check(mt5_module, decision.intent)
    checked_state = _with_checked_key(processed_state, signal_key)
    if not order_check.passed:
        event = NotificationEvent(
            kind="order_check_failed",
            mode="LIVE",
            title="MT5 rejected live pending order check",
            severity="warning",
            symbol=decision.intent.symbol,
            timeframe=decision.intent.timeframe,
            side=decision.intent.side,
            status="failed",
            signal_key=signal_key,
            fields={"retcode": order_check.retcode, "comment": order_check.comment},
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"order_check_failed:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_check_failed", order_check=order_check)

    final_market = market_snapshot_from_mt5(mt5_module, setup.symbol, broker_timezone=config.broker_timezone)
    final_spread = dynamic_spread_gate(
        setup,
        symbol_spec,
        final_market,
        max_spread_risk_fraction=config.max_spread_risk_fraction,
    )
    if not final_spread.passed:
        event = _rejection_event("spread_too_wide_before_send", "Spread widened before order_send.", signal_key, final_spread.to_dict())
        retry_state = _without_processed_key(checked_state, signal_key)
        retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:final_spread", event)
        return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check)

    adopted = _adopt_existing_broker_item(mt5_module, decision.intent, config=config, state=checked_state, symbol_spec=symbol_spec, notifier=notifier)
    if adopted is not None:
        return adopted

    outcome = send_pending_order(mt5_module, decision.intent)
    if not outcome.sent or outcome.order_ticket is None:
        if _is_retryable_order_send_block(outcome):
            event = _rejection_event(
                "autotrading_disabled",
                "MT5 AutoTrading is disabled by the client terminal.",
                signal_key,
                {"retcode": outcome.retcode, "comment": outcome.comment},
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:autotrading_disabled", event)
            return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check, order_send=outcome)
        event = NotificationEvent(
            kind="order_rejected",
            mode="LIVE",
            title="Live pending order rejected",
            severity="warning",
            symbol=decision.intent.symbol,
            timeframe=decision.intent.timeframe,
            side=decision.intent.side,
            status="rejected",
            signal_key=signal_key,
            fields={"retcode": outcome.retcode, "comment": outcome.comment},
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"order_rejected:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_rejected", order_check=order_check, order_send=outcome)

    placed = _tracked_order_from_intent(decision.intent, outcome.order_ticket, price_digits=symbol_spec.digits)
    next_state = replace(checked_state, pending_orders=(*checked_state.pending_orders, placed))
    save_live_state(config.state_path, next_state)
    event = _order_sent_event(placed, outcome, final_spread)
    next_state = _record_event_once(
        config,
        next_state,
        notifier,
        f"order_sent:{outcome.order_ticket}",
        event,
        store_thread_key=f"order:{outcome.order_ticket}",
    )
    return LiveSetupResult(state=next_state, signal_key=signal_key, status="order_sent", order_check=order_check, order_send=outcome)


def reconcile_live_state(
    mt5_module: Any,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    notifier: TelegramNotifier | None = None,
) -> LiveExecutorState:
    """Reconcile local lifecycle state with MT5 orders, positions, and deals."""

    orders = {int(getattr(order, "ticket")): order for order in current_strategy_orders(mt5_module, config)}
    positions = current_strategy_positions(mt5_module, config)
    next_state = state
    kept_pending: list[LiveTrackedOrder] = []
    new_active: list[LiveTrackedPosition] = list(state.active_positions)

    for pending in state.pending_orders:
        order = orders.get(pending.order_ticket)
        if order is not None:
            expiry_check = pending_order_bar_expiry_check(mt5_module, pending, config)
            if expiry_check.expired or _broker_backstop_elapsed(pending):
                cancel = cancel_pending_order(mt5_module, pending)
                event = _pending_cancelled_event(pending, cancel, expired=True, expiry_check=expiry_check)
                event_key_suffix = "cancelled" if cancel.sent else "cancel_failed"
                next_state = _record_event_once(
                    config,
                    next_state,
                    notifier,
                    f"pending_expired:{pending.order_ticket}:{event_key_suffix}",
                    event,
                    reply_thread_key=f"order:{pending.order_ticket}",
                )
                if not cancel.sent:
                    kept_pending.append(pending)
            else:
                kept_pending.append(pending)
            continue

        position = _matching_position_for_order(mt5_module, pending, positions, config)
        if position is not None:
            tracked_position = _tracked_position_from_pending(pending, position, config)
            new_active.append(tracked_position)
            event = _position_opened_event(tracked_position, position)
            next_state = _record_event_once(
                config,
                next_state,
                notifier,
                f"position_opened:{tracked_position.position_id}",
                event,
                reply_thread_key=f"order:{pending.order_ticket}",
            )
            continue

        history_order = _history_order_for_ticket(mt5_module, pending, config)
        event = _pending_missing_event(pending, history_order=history_order)
        next_state = _record_event_once(
            config,
            next_state,
            notifier,
            f"pending_cancelled:{pending.order_ticket}",
            event,
            reply_thread_key=f"order:{pending.order_ticket}",
        )

    next_state = replace(next_state, pending_orders=tuple(kept_pending), active_positions=tuple(new_active))
    positions_by_id = {_position_id(position): position for position in positions}
    kept_active: list[LiveTrackedPosition] = []
    for active in next_state.active_positions:
        if active.position_id in positions_by_id:
            kept_active.append(active)
            continue
        close = latest_close_for_position(mt5_module, active, config)
        if close is None:
            kept_active.append(active)
            append_audit_event(config.journal_path, "active_position_missing_close", position=active.to_dict())
            continue
        event = _close_event(active, close)
        next_state = _record_event_once(
            config,
            next_state,
            None if _close_is_old(next_state, close) else notifier,
            f"close:{close.ticket}",
            event,
            reply_thread_key=f"order:{active.order_ticket}",
        )
        next_state = replace(
            next_state,
            last_seen_close_ticket=close.ticket,
            last_seen_close_time_utc=close.close_time_utc,
        )

    next_state = replace(next_state, active_positions=tuple(kept_active))
    save_live_state(config.state_path, next_state)
    return next_state


def run_live_send_cycle(
    mt5_module: Any,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    notifier: TelegramNotifier | None = None,
    setup_provider: SetupProvider = default_setup_provider,
) -> LiveCycleResult:
    """Run one finite live-send polling cycle."""

    current_state = reconcile_live_state(mt5_module, config=config, state=state, notifier=notifier)
    save_live_state(config.state_path, current_state)
    frames_processed = 0
    orders_sent = 0
    setups_rejected = 0
    setups_blocked = 0
    for symbol in config.symbols:
        for timeframe in config.timeframes:
            frame = fetch_closed_candles(mt5_module, symbol=symbol, timeframe=timeframe, bars=config.history_bars, broker_timezone=config.broker_timezone)
            market = market_snapshot_from_mt5(mt5_module, symbol, broker_timezone=config.broker_timezone)
            append_market_snapshot(config.journal_path, symbol, timeframe, market)
            frames_processed += 1
            for item in setup_provider(frame, symbol, timeframe, _dry_compatible_config(config)):
                if isinstance(item, SkippedTrade):
                    setups_rejected += 1
                    append_audit_event(config.journal_path, "setup_skipped", skipped=item.to_dict())
                    continue
                result = process_trade_setup_live_send(
                    mt5_module,
                    item,
                    config=config,
                    state=current_state,
                    market=market,
                    notifier=notifier,
                )
                current_state = result.state
                save_live_state(config.state_path, current_state)
                orders_sent += 1 if result.status in {"order_sent", "market_recovery_sent"} else 0
                setups_rejected += 1 if result.status == "rejected" else 0
                setups_blocked += 1 if result.status == "blocked" else 0
    save_live_state(config.state_path, current_state)
    return LiveCycleResult(
        state=current_state,
        frames_processed=frames_processed,
        orders_sent=orders_sent,
        setups_rejected=setups_rejected,
        setups_blocked=setups_blocked,
    )


def current_strategy_orders(mt5_module: Any, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    orders: list[Any] = []
    for symbol in config.symbols:
        result = mt5_module.orders_get(symbol=symbol)
        orders.extend([] if result is None else list(result))
    return tuple(order for order in orders if int(getattr(order, "magic", 0) or 0) == config.strategy_magic)


def current_strategy_positions(mt5_module: Any, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    positions: list[Any] = []
    for symbol in config.symbols:
        result = mt5_module.positions_get(symbol=symbol)
        positions.extend([] if result is None else list(result))
    return tuple(position for position in positions if int(getattr(position, "magic", 0) or 0) == config.strategy_magic)


def latest_close_for_position(mt5_module: Any, active: LiveTrackedPosition, config: LiveSendExecutorConfig) -> LiveCloseEvent | None:
    deals = _history_deals_for_position(mt5_module, active.position_id, config)
    close_deals = [
        deal
        for deal in deals
        if _deal_is_exit(mt5_module, deal)
        and int(getattr(deal, "position_id", active.position_id) or active.position_id) == active.position_id
    ]
    if not close_deals:
        return None
    deal = sorted(close_deals, key=lambda item: (int(getattr(item, "time_msc", 0) or 0), int(getattr(item, "ticket", 0) or 0)))[-1]
    return LiveCloseEvent(
        ticket=int(getattr(deal, "ticket", 0) or 0),
        position_id=active.position_id,
        close_reason=_close_reason(mt5_module, deal),
        close_time_utc=_deal_time_utc(deal, config),
        close_price=float(getattr(deal, "price", 0.0) or 0.0),
        close_profit=float(getattr(deal, "profit", 0.0) or 0.0),
        close_comment=str(getattr(deal, "comment", "") or ""),
    )


def _record_event_once(
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    notifier: TelegramNotifier | None,
    event_key: str,
    event: NotificationEvent,
    *,
    reply_thread_key: str | None = None,
    store_thread_key: str | None = None,
) -> LiveExecutorState:
    if event_key in state.notified_event_keys:
        return state
    reply_to_message_id = None if reply_thread_key is None else state.telegram_message_ids.get(reply_thread_key)
    delivery = deliver_notification_best_effort(notifier, event, reply_to_message_id=reply_to_message_id)
    append_audit_event(
        config.journal_path,
        event.kind,
        signal_key=event.signal_key,
        notification=format_notification_message(event),
        notification_event=event.to_dict(),
        delivery=None if delivery is None else delivery.to_dict(),
        event_key=event_key,
        reply_thread_key=reply_thread_key,
        store_thread_key=store_thread_key,
        telegram_message_id=None if delivery is None else delivery.message_id,
        reply_to_message_id=reply_to_message_id,
    )
    telegram_message_ids = dict(state.telegram_message_ids)
    if store_thread_key and delivery is not None and delivery.sent and delivery.message_id is not None:
        telegram_message_ids[store_thread_key] = int(delivery.message_id)
    next_state = replace(
        state,
        notified_event_keys=_append_unique(state.notified_event_keys, event_key),
        telegram_message_ids=telegram_message_ids,
    )
    save_live_state(config.state_path, next_state)
    return next_state


def _tracked_order_from_intent(intent: MT5OrderIntent, order_ticket: int, *, price_digits: int | None = None) -> LiveTrackedOrder:
    broker_backstop = intent.broker_backstop_expiration_time_utc or intent.expiration_time_utc
    signal_time = intent.signal_time_utc
    return LiveTrackedOrder(
        signal_key=intent.signal_key,
        order_ticket=order_ticket,
        symbol=intent.symbol,
        timeframe=intent.timeframe,
        side=intent.side,
        order_type=intent.order_type,
        volume=intent.volume,
        entry_price=intent.entry_price,
        stop_loss=intent.stop_loss,
        take_profit=intent.take_profit,
        target_risk_pct=intent.target_risk_pct,
        actual_risk_pct=intent.actual_risk_pct,
        expiration_time_utc=intent.expiration_time_utc.isoformat(),
        magic=intent.magic,
        comment=intent.comment,
        setup_id=intent.setup_id,
        placed_time_utc=pd.Timestamp.now(tz="UTC").isoformat(),
        price_digits=price_digits,
        signal_time_utc=None if signal_time is None else signal_time.isoformat(),
        max_entry_wait_bars=intent.max_entry_wait_bars,
        strategy_expiry_mode=intent.strategy_expiry_mode,
        broker_backstop_expiration_time_utc=broker_backstop.isoformat(),
    )


def _tracked_position_from_pending(pending: LiveTrackedOrder, position: Any, config: LiveSendExecutorConfig) -> LiveTrackedPosition:
    return LiveTrackedPosition(
        signal_key=pending.signal_key,
        position_id=_position_id(position),
        order_ticket=pending.order_ticket,
        symbol=pending.symbol,
        timeframe=pending.timeframe,
        side=pending.side,
        volume=float(getattr(position, "volume", pending.volume) or pending.volume),
        entry_price=float(getattr(position, "price_open", pending.entry_price) or pending.entry_price),
        stop_loss=float(getattr(position, "sl", pending.stop_loss) or pending.stop_loss),
        take_profit=float(getattr(position, "tp", pending.take_profit) or pending.take_profit),
        target_risk_pct=pending.target_risk_pct,
        actual_risk_pct=pending.actual_risk_pct,
        opened_time_utc=_position_time_utc(position, config),
        magic=pending.magic,
        comment=pending.comment,
        setup_id=pending.setup_id,
        price_digits=pending.price_digits,
    )


def _tracked_position_from_intent(
    intent: MT5OrderIntent,
    position: Any,
    config: LiveSendExecutorConfig,
    *,
    price_digits: int | None,
) -> LiveTrackedPosition:
    position_id = _position_id(position)
    return LiveTrackedPosition(
        signal_key=intent.signal_key,
        position_id=position_id,
        order_ticket=int(getattr(position, "ticket", 0) or position_id),
        symbol=intent.symbol,
        timeframe=intent.timeframe,
        side=intent.side,
        volume=float(getattr(position, "volume", intent.volume) or intent.volume),
        entry_price=float(getattr(position, "price_open", intent.entry_price) or intent.entry_price),
        stop_loss=float(getattr(position, "sl", intent.stop_loss) or intent.stop_loss),
        take_profit=float(getattr(position, "tp", intent.take_profit) or intent.take_profit),
        target_risk_pct=intent.target_risk_pct,
        actual_risk_pct=intent.actual_risk_pct,
        opened_time_utc=_position_time_utc(position, config),
        magic=intent.magic,
        comment=intent.comment,
        setup_id=intent.setup_id,
        price_digits=price_digits,
    )


def _build_market_recovery_intent(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    account: Any,
    symbol_spec: MT5SymbolExecutionSpec,
    recovery_check: MarketRecoveryCheck,
) -> tuple[MT5OrderIntent | None, float | None, NotificationEvent | None]:
    signal_key = signal_key_for_setup(setup)
    fill = recovery_check.fill_price
    take_profit = recovery_check.recalculated_take_profit
    if fill is None or take_profit is None:
        return (
            None,
            None,
            _rejection_event(
                "market_recovery_missing_price",
                "Market recovery fill or recalculated target is missing.",
                signal_key,
                recovery_check.to_dict(),
            ),
        )

    stop = float(setup.stop_price)
    rounded_fill = _round_price_for_spec(fill, symbol_spec)
    rounded_stop = _round_price_for_spec(stop, symbol_spec)
    rounded_take_profit = _round_price_for_spec(take_profit, symbol_spec)
    recovery_setup = replace(setup, entry_price=rounded_fill, stop_price=rounded_stop, target_price=rounded_take_profit)
    try:
        risk_per_lot = broker_money_risk_per_lot(mt5_module, recovery_setup)
    except RuntimeError as exc:
        return (
            None,
            None,
            _rejection_event(
                "market_recovery_invalid_symbol_value",
                str(exc),
                signal_key,
                recovery_check.to_dict(),
            ),
        )
    try:
        target_risk_pct = live_risk_buckets_from_config(config)[str(setup.timeframe).upper()]
    except KeyError:
        return (
            None,
            risk_per_lot,
            _rejection_event(
                "missing_risk_bucket",
                f"No execution risk bucket for timeframe {setup.timeframe!r}.",
                signal_key,
                recovery_check.to_dict(),
            ),
        )
    limits = live_execution_safety_from_config(config)
    if target_risk_pct <= 0 or target_risk_pct > limits.max_risk_pct_per_trade:
        return (
            None,
            risk_per_lot,
            _rejection_event(
                "market_recovery_risk_pct_limit",
                f"target_risk_pct={target_risk_pct:g}",
                signal_key,
                {**recovery_check.to_dict(), "target_risk_pct": target_risk_pct},
            ),
        )
    volume_decision = _market_recovery_sized_volume(
        account=account,
        symbol_spec=symbol_spec,
        limits=limits,
        target_risk_pct=target_risk_pct,
        risk_per_lot=risk_per_lot,
    )
    if "error" in volume_decision:
        return (
            None,
            risk_per_lot,
            _rejection_event(
                str(volume_decision["error"]),
                str(volume_decision["detail"]),
                signal_key,
                {**recovery_check.to_dict(), **volume_decision},
            ),
        )
    exposure = _exposure_from_state(state, setup.symbol)
    actual_risk_pct = float(volume_decision["actual_risk_pct"])
    if exposure.open_risk_pct + actual_risk_pct > limits.max_open_risk_pct + 1e-12:
        return (
            None,
            risk_per_lot,
            _rejection_event(
                "market_recovery_max_open_risk",
                f"open={exposure.open_risk_pct:g} new={actual_risk_pct:g} max={limits.max_open_risk_pct:g}",
                signal_key,
                {**recovery_check.to_dict(), **volume_decision},
            ),
        )
    try:
        signal_time = setup_signal_time_utc(setup)
        broker_backstop = broker_backstop_expiration_time_utc(setup, max_entry_wait_bars=config.max_entry_wait_bars)
    except Exception as exc:
        return (
            None,
            risk_per_lot,
            _rejection_event(
                "market_recovery_expiration_failed",
                str(exc),
                signal_key,
                recovery_check.to_dict(),
            ),
        )
    intent = MT5OrderIntent(
        signal_key=signal_key,
        symbol=str(setup.symbol).upper(),
        timeframe=str(setup.timeframe).upper(),
        side=setup.side,
        order_type="BUY" if setup.side == "long" else "SELL",  # type: ignore[arg-type]
        volume=float(volume_decision["volume"]),
        entry_price=rounded_fill,
        stop_loss=rounded_stop,
        take_profit=rounded_take_profit,
        target_risk_pct=target_risk_pct,
        actual_risk_pct=actual_risk_pct,
        expiration_time_utc=broker_backstop,
        magic=limits.strategy_magic,
        comment=_live_order_comment(setup),
        setup_id=setup.setup_id,
        signal_time_utc=signal_time,
        max_entry_wait_bars=config.max_entry_wait_bars,
        strategy_expiry_mode="bar_count",
        broker_backstop_expiration_time_utc=broker_backstop,
    )
    return intent, risk_per_lot, None


def _market_recovery_sized_volume(
    *,
    account: Any,
    symbol_spec: MT5SymbolExecutionSpec,
    limits: ExecutionSafetyLimits,
    target_risk_pct: float,
    risk_per_lot: float,
) -> dict[str, Any]:
    if symbol_spec.volume_step <= 0 or symbol_spec.volume_min <= 0 or symbol_spec.volume_max <= 0:
        return {"error": "market_recovery_invalid_volume_spec", "detail": "volume_min, volume_max, and volume_step must be positive"}
    if risk_per_lot <= 0 or not math.isfinite(float(risk_per_lot)):
        return {"error": "market_recovery_invalid_symbol_value", "detail": f"risk_per_lot={risk_per_lot:g}"}
    equity = float(getattr(account, "equity", 0.0) if not isinstance(account, dict) else account.get("equity", 0.0))
    if equity <= 0:
        return {"error": "market_recovery_invalid_account_equity", "detail": f"equity={equity:g}"}
    raw_volume = equity * float(target_risk_pct) / 100.0 / float(risk_per_lot)
    cap = float(symbol_spec.volume_max)
    if limits.max_lots_per_order is not None:
        cap = min(cap, float(limits.max_lots_per_order))
    rounded_volume = _round_volume_down(raw_volume if raw_volume < cap else cap, symbol_spec.volume_step)
    if rounded_volume < float(symbol_spec.volume_min):
        return {
            "error": "market_recovery_volume_below_min",
            "detail": f"raw_volume={raw_volume:g} rounded_volume={rounded_volume:g} min={symbol_spec.volume_min:g}",
            "raw_volume": raw_volume,
            "rounded_volume": rounded_volume,
            "target_risk_pct": target_risk_pct,
        }
    actual_risk_pct = rounded_volume * float(risk_per_lot) / equity * 100.0
    return {
        "volume": rounded_volume,
        "actual_risk_pct": actual_risk_pct,
        "target_risk_pct": target_risk_pct,
        "raw_volume": raw_volume,
        "risk_per_lot": risk_per_lot,
    }


def _fallback_market_recovery_position(
    mt5_module: Any,
    intent: MT5OrderIntent,
    outcome: LiveOrderSendOutcome,
    config: LiveSendExecutorConfig,
) -> Any:
    ticket = outcome.order_ticket or outcome.deal_ticket or int(pd.Timestamp.now(tz="UTC").timestamp())
    position_type = getattr(mt5_module, "ORDER_TYPE_BUY", 0) if intent.side == "long" else getattr(mt5_module, "ORDER_TYPE_SELL", 1)
    now_msc = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    return SimpleNamespace(
        identifier=ticket,
        ticket=ticket,
        symbol=intent.symbol,
        magic=intent.magic,
        type=position_type,
        comment=intent.comment,
        volume=intent.volume,
        price_open=intent.entry_price,
        sl=intent.stop_loss,
        tp=intent.take_profit,
        time_msc=now_msc,
        time=0,
    )


def _round_price_for_spec(value: float, spec: MT5SymbolExecutionSpec) -> float:
    return round(float(value), int(spec.digits))


def _round_volume_down(volume: float, step: float) -> float:
    units = math.floor(float(volume) / float(step) + 1e-12)
    return units * float(step)


def _live_order_comment(setup: TradeSetup) -> str:
    signal_index = "na" if setup.signal_index is None else str(setup.signal_index)
    return f"LPFS {str(setup.timeframe).upper()} {str(setup.side)[0].upper()} {signal_index}"[:31]


def _adopt_existing_broker_item(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    symbol_spec: MT5SymbolExecutionSpec,
    notifier: TelegramNotifier | None = None,
) -> LiveSetupResult | None:
    order = _matching_broker_order_for_intent(mt5_module, intent, config, symbol_spec)
    if order is not None:
        ticket = int(getattr(order, "ticket", 0) or 0)
        if ticket <= 0:
            return None
        tracked = _tracked_order_from_intent(intent, ticket, price_digits=symbol_spec.digits)
        next_state = replace(state, pending_orders=(*state.pending_orders, tracked))
        save_live_state(config.state_path, next_state)
        event = _order_adopted_event(tracked, source="pending order", broker_item=order)
        next_state = _record_event_once(
            config,
            next_state,
            notifier,
            f"order_adopted:{ticket}",
            event,
            store_thread_key=f"order:{ticket}",
        )
        return LiveSetupResult(
            state=next_state,
            signal_key=intent.signal_key,
            status="order_adopted",
            order_send=_adopted_outcome(mt5_module, intent, ticket, "existing pending order"),
        )

    position = _matching_broker_position_for_intent(mt5_module, intent, config, symbol_spec)
    if position is None:
        return None
    tracked_position = _tracked_position_from_intent(intent, position, config, price_digits=symbol_spec.digits)
    next_state = replace(state, active_positions=(*state.active_positions, tracked_position))
    save_live_state(config.state_path, next_state)
    event = _order_adopted_event(tracked_position, source="open position", broker_item=position)
    next_state = _record_event_once(
        config,
        next_state,
        notifier,
        f"position_adopted:{tracked_position.position_id}",
        event,
        store_thread_key=f"order:{tracked_position.order_ticket}",
    )
    return LiveSetupResult(
        state=next_state,
        signal_key=intent.signal_key,
        status="order_adopted",
        order_send=_adopted_outcome(mt5_module, intent, tracked_position.order_ticket, "existing open position"),
    )


def _adopted_outcome(mt5_module: Any, intent: MT5OrderIntent, ticket: int, source: str) -> LiveOrderSendOutcome:
    return LiveOrderSendOutcome(
        sent=True,
        request=build_order_check_request(mt5_module, intent),
        retcode=None,
        comment=f"adopted {source}; no order_send call",
        order_ticket=ticket,
    )


def _order_sent_event(order: LiveTrackedOrder, outcome: LiveOrderSendOutcome, spread: DynamicSpreadGate) -> NotificationEvent:
    return NotificationEvent(
        kind="order_sent",
        mode="LIVE",
        title="Live limit order placed",
        severity="info",
        symbol=order.symbol,
        timeframe=order.timeframe,
        side=order.side,
        status="pending",
        signal_key=order.signal_key,
        fields={
            "order_ticket": order.order_ticket,
            "order_type": order.order_type,
            "entry": order.entry_price,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "volume": order.volume,
            "actual_risk_pct": order.actual_risk_pct,
            "target_risk_pct": order.target_risk_pct,
            "expiration_utc": order.expiration_time_utc,
            "signal_time_utc": order.signal_time_utc,
            "max_entry_wait_bars": order.max_entry_wait_bars,
            "strategy_expiry_mode": order.strategy_expiry_mode,
            "broker_backstop_expiration_utc": order.broker_backstop_expiration_time_utc,
            "spread_risk_pct": spread.spread_risk_fraction * 100,
            "price_digits": order.price_digits,
            "retcode": outcome.retcode,
            "comment": outcome.comment,
        },
        message="closed-candle LP + Force Strike setup, 50% pullback entry, FS structure stop, 1R target.",
    )


def _market_recovery_sent_event(
    active: LiveTrackedPosition,
    outcome: LiveOrderSendOutcome,
    recovery_check: MarketRecoveryCheck,
) -> NotificationEvent:
    return NotificationEvent(
        kind="market_recovery_sent",
        mode="LIVE",
        title="Live market recovery order placed",
        severity="info",
        symbol=active.symbol,
        timeframe=active.timeframe,
        side=active.side,
        status="open",
        signal_key=active.signal_key,
        fields={
            "position_id": active.position_id,
            "order_ticket": active.order_ticket,
            "deal_ticket": outcome.deal_ticket,
            "order_type": "BUY" if active.side == "long" else "SELL",
            "original_entry": recovery_check.original_entry,
            "fill_price": active.entry_price,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "original_take_profit": recovery_check.original_take_profit,
            "volume": active.volume,
            "actual_risk_pct": active.actual_risk_pct,
            "target_risk_pct": active.target_risk_pct,
            "spread_risk_pct": None
            if recovery_check.spread_risk_fraction is None
            else recovery_check.spread_risk_fraction * 100.0,
            "max_spread_risk_fraction": recovery_check.max_spread_risk_fraction,
            "first_touch_time_utc": recovery_check.first_touch_time_utc,
            "first_touch_high": recovery_check.first_touch_high,
            "first_touch_low": recovery_check.first_touch_low,
            "opened_utc": active.opened_time_utc,
            "price_digits": active.price_digits,
            "retcode": outcome.retcode,
            "comment": outcome.comment,
        },
        message="Missed pending touch recovered with better-than-entry executable price, original structure stop, and recalculated 1R target.",
    )


def _order_adopted_event(item: LiveTrackedOrder | LiveTrackedPosition, *, source: str, broker_item: Any) -> NotificationEvent:
    return NotificationEvent(
        kind="order_adopted",
        mode="LIVE",
        title="Existing live order adopted",
        severity="warning",
        symbol=item.symbol,
        timeframe=item.timeframe,
        side=item.side,
        status="adopted",
        signal_key=item.signal_key,
        fields={
            "adoption_source": source,
            "order_ticket": item.order_ticket,
            "position_id": getattr(item, "position_id", None),
            "order_type": "BUY_LIMIT" if item.side == "long" else "SELL_LIMIT",
            "entry": item.entry_price,
            "stop_loss": item.stop_loss,
            "take_profit": item.take_profit,
            "volume": item.volume,
            "actual_risk_pct": item.actual_risk_pct,
            "target_risk_pct": item.target_risk_pct,
            "price_digits": item.price_digits,
            "broker_comment": str(getattr(broker_item, "comment", "") or ""),
        },
        message=f"Existing MT5 {source} matched this LPFS setup; no new order sent.",
    )


def _position_opened_event(active: LiveTrackedPosition, position: Any) -> NotificationEvent:
    return NotificationEvent(
        kind="position_opened",
        mode="LIVE",
        title="Live limit order filled",
        severity="info",
        symbol=active.symbol,
        timeframe=active.timeframe,
        side=active.side,
        status="open",
        signal_key=active.signal_key,
        fields={
            "position_id": active.position_id,
            "order_ticket": active.order_ticket,
            "fill_price": active.entry_price,
            "volume": active.volume,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "actual_risk_pct": active.actual_risk_pct,
            "target_risk_pct": active.target_risk_pct,
            "opened_utc": active.opened_time_utc,
            "price_digits": active.price_digits,
            "broker_comment": str(getattr(position, "comment", "") or ""),
        },
    )


def _close_event(active: LiveTrackedPosition, close: LiveCloseEvent) -> NotificationEvent:
    risk_price = abs(active.entry_price - active.stop_loss)
    r_result = 0.0 if risk_price <= 0 else (close.close_price - active.entry_price) / risk_price
    if active.side == "short":
        r_result *= -1
    if close.close_reason == "tp":
        kind = "take_profit_hit"
    elif close.close_reason == "sl":
        kind = "stop_loss_hit"
    else:
        kind = "position_closed"
    return NotificationEvent(
        kind=kind,
        mode="LIVE",
        title={
            "take_profit_hit": "Take profit hit",
            "stop_loss_hit": "Stop loss hit",
            "position_closed": "Position closed",
        }[kind],
        severity="warning" if kind == "stop_loss_hit" else "info",
        symbol=active.symbol,
        timeframe=active.timeframe,
        side=active.side,
        status=close.close_reason,
        signal_key=active.signal_key,
        fields={
            "position_id": active.position_id,
            "deal_ticket": close.ticket,
            "entry": active.entry_price,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "volume": active.volume,
            "close_price": close.close_price,
            "close_profit": close.close_profit,
            "r_result": r_result,
            "opened_utc": active.opened_time_utc,
            "closed_utc": close.close_time_utc,
            "price_digits": active.price_digits,
            "broker_comment": close.close_comment,
            "close_reason": close.close_reason,
        },
    )


def _pending_cancelled_event(
    order: LiveTrackedOrder,
    outcome: LiveOrderSendOutcome,
    *,
    expired: bool,
    expiry_check: PendingBarExpiryCheck | None = None,
) -> NotificationEvent:
    fields: dict[str, Any] = {
        "order_ticket": order.order_ticket,
        "price_digits": order.price_digits,
        "retcode": outcome.retcode,
        "comment": outcome.comment,
    }
    if expiry_check is not None:
        fields.update(expiry_check.to_dict())
    return NotificationEvent(
        kind="pending_expired" if expired else "pending_cancelled",
        mode="LIVE",
        title="Pending order expired" if expired else "Pending order cancelled",
        severity="warning",
        symbol=order.symbol,
        timeframe=order.timeframe,
        side=order.side,
        status="cancelled" if outcome.sent else "cancel_failed",
        signal_key=order.signal_key,
        fields=fields,
    )


def _pending_missing_event(order: LiveTrackedOrder, *, history_order: Any | None = None) -> NotificationEvent:
    status = "missing" if history_order is None else "history"
    return NotificationEvent(
        kind="pending_cancelled",
        mode="LIVE",
        title="Pending order no longer open",
        severity="warning",
        symbol=order.symbol,
        timeframe=order.timeframe,
        side=order.side,
        status=status,
        signal_key=order.signal_key,
        fields={
            "order_ticket": order.order_ticket,
            "price_digits": order.price_digits,
            "broker_comment": "" if history_order is None else str(getattr(history_order, "comment", "") or ""),
        },
    )


def _rejection_event(status: str, message: str, signal_key: str, fields: dict[str, Any]) -> NotificationEvent:
    return NotificationEvent(
        kind="setup_rejected",
        mode="LIVE",
        title="Live setup rejected before send",
        severity="warning",
        status=status,
        signal_key=signal_key,
        message=message,
        fields=fields,
    )


def _matching_broker_order_for_intent(
    mt5_module: Any,
    intent: MT5OrderIntent,
    config: LiveSendExecutorConfig,
    spec: MT5SymbolExecutionSpec,
) -> Any | None:
    for order in current_strategy_orders(mt5_module, config):
        if str(getattr(order, "symbol", "") or "").upper() != intent.symbol:
            continue
        if int(getattr(order, "type", -1) or -1) != _mt5_pending_order_type(mt5_module, intent):
            continue
        if str(getattr(order, "comment", "") or "") != intent.comment:
            continue
        if not _any_volume_matches(order, intent.volume, spec):
            continue
        if not _price_attr_matches(order, ("price_open", "price"), intent.entry_price, spec):
            continue
        if not _price_attr_matches(order, ("sl",), intent.stop_loss, spec):
            continue
        if not _price_attr_matches(order, ("tp",), intent.take_profit, spec):
            continue
        return order
    return None


def _matching_broker_position_for_intent(
    mt5_module: Any,
    intent: MT5OrderIntent,
    config: LiveSendExecutorConfig,
    spec: MT5SymbolExecutionSpec,
) -> Any | None:
    expected_type = getattr(mt5_module, "ORDER_TYPE_BUY", 0) if intent.side == "long" else getattr(mt5_module, "ORDER_TYPE_SELL", 1)
    for position in current_strategy_positions(mt5_module, config):
        if str(getattr(position, "symbol", "") or "").upper() != intent.symbol:
            continue
        if int(getattr(position, "type", expected_type) or expected_type) != expected_type:
            continue
        if str(getattr(position, "comment", "") or "") != intent.comment:
            continue
        if not _any_volume_matches(position, intent.volume, spec):
            continue
        if not _price_attr_matches(position, ("sl",), intent.stop_loss, spec):
            continue
        if not _price_attr_matches(position, ("tp",), intent.take_profit, spec):
            continue
        return position
    return None


def _matching_position_for_order(
    mt5_module: Any,
    order: LiveTrackedOrder,
    positions: Sequence[Any],
    config: LiveSendExecutorConfig,
) -> Any | None:
    candidates = [
        position
        for position in positions
        if str(getattr(position, "symbol", "") or "").upper() == order.symbol
        and int(getattr(position, "magic", 0) or 0) == order.magic
    ]
    for position in candidates:
        comment = str(getattr(position, "comment", "") or "")
        if order.comment and order.comment in comment:
            return position
    linked_position_id = _position_id_from_order_history(mt5_module, order, config)
    if linked_position_id is None:
        return None
    for position in candidates:
        if _position_id(position) == linked_position_id:
            return position
    return None


def _position_id_from_order_history(mt5_module: Any, order: LiveTrackedOrder, config: LiveSendExecutorConfig) -> int | None:
    history_order = _history_order_for_ticket(mt5_module, order, config)
    if history_order is not None:
        for attr in ("position_id", "position_by_id"):
            value = _optional_int(getattr(history_order, attr, None))
            if value is not None:
                return value
    for deal in _history_deals_for_order_ticket(mt5_module, order.order_ticket, config):
        value = _optional_int(getattr(deal, "position_id", None))
        if value is not None:
            return value
    return None


def _history_deals_for_order_ticket(mt5_module: Any, order_ticket: int, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    result = mt5_module.history_deals_get(start.to_pydatetime(), end.to_pydatetime())
    deals = [] if result is None else list(result)
    return tuple(deal for deal in deals if int(getattr(deal, "order", 0) or 0) == int(order_ticket))


def _history_deals_for_position(mt5_module: Any, position_id: int, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    try:
        direct = mt5_module.history_deals_get(position=position_id)
    except TypeError:
        direct = None
    if direct:
        return tuple(direct)
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    fallback = mt5_module.history_deals_get(start.to_pydatetime(), end.to_pydatetime())
    return tuple() if fallback is None else tuple(fallback)


def _history_order_for_ticket(mt5_module: Any, order: LiveTrackedOrder, config: LiveSendExecutorConfig) -> Any | None:
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    result = mt5_module.history_orders_get(start.to_pydatetime(), end.to_pydatetime())
    for item in [] if result is None else list(result):
        if int(getattr(item, "ticket", 0) or 0) != order.order_ticket:
            continue
        if int(getattr(item, "magic", 0) or 0) != order.magic:
            continue
        if str(getattr(item, "symbol", "") or "").upper() != order.symbol:
            continue
        return item
    return None


def _deal_is_exit(mt5_module: Any, deal: Any) -> bool:
    entry = int(getattr(deal, "entry", -1) or -1)
    return entry in {int(getattr(mt5_module, "DEAL_ENTRY_OUT", 1)), int(getattr(mt5_module, "DEAL_ENTRY_INOUT", 2))}


def _close_reason(mt5_module: Any, deal: Any) -> str:
    reason = getattr(deal, "reason", None)
    comment = str(getattr(deal, "comment", "") or "").lower()
    if reason == getattr(mt5_module, "DEAL_REASON_TP", object()) or "[tp" in comment or "tp" in comment:
        return "tp"
    if reason == getattr(mt5_module, "DEAL_REASON_SL", object()) or "[sl" in comment or "sl" in comment:
        return "sl"
    return "manual"


def _deal_time_utc(deal: Any, config: LiveSendExecutorConfig) -> str:
    raw_msc = getattr(deal, "time_msc", None)
    timestamp = broker_time_epoch_to_utc(raw_msc, config.broker_timezone, unit="ms") if raw_msc else None
    if timestamp is None:
        timestamp = broker_time_epoch_to_utc(getattr(deal, "time", None), config.broker_timezone, unit="s")
    return (timestamp or pd.Timestamp.now(tz="UTC")).isoformat()


def _position_id(position: Any) -> int:
    return int(getattr(position, "identifier", None) or getattr(position, "ticket", 0) or 0)


def _position_time_utc(position: Any, config: LiveSendExecutorConfig) -> str:
    raw_msc = getattr(position, "time_msc", None)
    timestamp = broker_time_epoch_to_utc(raw_msc, config.broker_timezone, unit="ms") if raw_msc else None
    if timestamp is None:
        timestamp = broker_time_epoch_to_utc(getattr(position, "time", None), config.broker_timezone, unit="s")
    return (timestamp or pd.Timestamp.now(tz="UTC")).isoformat()


def _as_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _close_is_old(state: LiveExecutorState, close: LiveCloseEvent) -> bool:
    if state.last_seen_close_time_utc is None:
        return False
    close_time = pd.Timestamp(close.close_time_utc)
    last_time = pd.Timestamp(state.last_seen_close_time_utc)
    if close_time > last_time:
        return False
    if close_time == last_time and state.last_seen_close_ticket is not None:
        return close.ticket <= state.last_seen_close_ticket
    return True


def _exposure_from_state(state: LiveExecutorState, symbol: str) -> ExistingStrategyExposure:
    open_items = (*state.pending_orders, *state.active_positions)
    return ExistingStrategyExposure(
        open_risk_pct=sum(float(item.actual_risk_pct) for item in open_items),
        same_symbol_positions=sum(1 for item in open_items if item.symbol == str(symbol).upper()),
        total_strategy_positions=len(open_items),
        existing_signal_keys=tuple(
            set(state.processed_signal_keys)
            | {item.signal_key for item in state.pending_orders}
            | {item.signal_key for item in state.active_positions}
        ),
    )


def _accepted_done_retcodes(mt5_module: Any) -> set[int]:
    accepted = {0}
    retcode_done = getattr(mt5_module, "TRADE_RETCODE_DONE", None)
    if retcode_done is not None:
        accepted.add(int(retcode_done))
    return accepted


def _accepted_send_retcodes(mt5_module: Any) -> set[int]:
    accepted = _accepted_done_retcodes(mt5_module)
    retcode_placed = getattr(mt5_module, "TRADE_RETCODE_PLACED", None)
    if retcode_placed is not None:
        accepted.add(int(retcode_placed))
    return accepted


def _is_retryable_order_send_block(outcome: LiveOrderSendOutcome) -> bool:
    """Return true for operator/environment send blocks that can clear later."""

    return outcome.retcode == TRADE_RETCODE_CLIENT_DISABLES_AT


def _mt5_pending_order_type(mt5_module: Any, intent: MT5OrderIntent) -> int:
    if intent.order_type not in {"BUY_LIMIT", "SELL_LIMIT"}:
        raise ValueError("Pending order type expected for broker pending-order matching.")
    return int(
        getattr(mt5_module, "ORDER_TYPE_BUY_LIMIT")
        if intent.order_type == "BUY_LIMIT"
        else getattr(mt5_module, "ORDER_TYPE_SELL_LIMIT")
    )


def _any_volume_matches(item: Any, expected: float, spec: MT5SymbolExecutionSpec) -> bool:
    tolerance = max(float(spec.volume_step) * 1e-6, 1e-9)
    for attr in ("volume_initial", "volume_current", "volume"):
        raw_value = getattr(item, attr, None)
        if raw_value in (None, ""):
            continue
        if abs(float(raw_value) - float(expected)) <= tolerance:
            return True
    return False


def _price_attr_matches(item: Any, attrs: Sequence[str], expected: float, spec: MT5SymbolExecutionSpec) -> bool:
    tolerance = max(abs(float(spec.point)) / 2.0, 1e-9)
    for attr in attrs:
        raw_value = getattr(item, attr, None)
        if raw_value in (None, ""):
            continue
        if abs(float(raw_value) - float(expected)) <= tolerance:
            return True
    return False


def _optional_int(value: Any) -> int | None:
    integer = int(value or 0)
    return None if integer == 0 else integer


def _append_unique(values: Iterable[str], value: str) -> tuple[str, ...]:
    items = tuple(values)
    return items if value in items else (*items, value)


def _with_processed_key(state: LiveExecutorState, signal_key: str) -> LiveExecutorState:
    return replace(state, processed_signal_keys=_append_unique(state.processed_signal_keys, signal_key))


def _without_processed_key(state: LiveExecutorState, signal_key: str) -> LiveExecutorState:
    return replace(state, processed_signal_keys=tuple(key for key in state.processed_signal_keys if key != signal_key))


def _with_checked_key(state: LiveExecutorState, signal_key: str) -> LiveExecutorState:
    return replace(state, order_checked_signal_keys=_append_unique(state.order_checked_signal_keys, signal_key))


def _tuple_of_strings(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_local_path(base_dir: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _dry_compatible_config(config: LiveSendExecutorConfig) -> Any:
    from .dry_run_executor import DryRunExecutorConfig

    return DryRunExecutorConfig(
        symbols=config.symbols,
        timeframes=config.timeframes,
        broker_timezone=config.broker_timezone,
        history_bars=config.history_bars,
        journal_path=config.journal_path,
        state_path=config.state_path,
        max_lots_per_order=config.max_lots_per_order,
        risk_bucket_scale=config.risk_bucket_scale,
        max_open_risk_pct=config.max_open_risk_pct,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        strategy_magic=config.strategy_magic,
        pivot_strength=config.pivot_strength,
        max_bars_from_lp_break=config.max_bars_from_lp_break,
        require_lp_pivot_before_fs_mother=config.require_lp_pivot_before_fs_mother,
        max_entry_wait_bars=config.max_entry_wait_bars,
    )
