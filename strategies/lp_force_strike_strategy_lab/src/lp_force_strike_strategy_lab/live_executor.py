"""Live MT5 pending-order lifecycle executor for LP + Force Strike."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
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
from .diagnostic_logging import (
    DIAGNOSTIC_SCHEMA_VERSION,
    build_setup_diagnostics,
    enrich_diagnostics,
    fields_with_diagnostics,
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
from .timestamp_semantics import (
    DEFAULT_LEGACY_BROKER_TIMEZONE,
    LEGACY_HELSINKI_RELOCALIZED_V1,
    MT5_EPOCH_UTC_V2,
    TimestampSemanticsError,
    canonical_and_legacy_signal_keys,
    canonical_signal_key,
    normalize_recorded_timestamp,
    parse_signal_key,
    signal_key_matches_canonical,
)


LIVE_SEND_ACK = "I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"
LIVE_SEND_MODE = "LIVE_SEND"
TRADE_RETCODE_CLIENT_DISABLES_AT = 10027
TRADE_RETCODE_MARKET_CLOSED = 10018
LIVE_STATE_SCHEMA_VERSION = 2
MINIMUM_LIVE_STATE_READER_SCHEMA_VERSION = 2
DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES = 512 * 1024 * 1024
MARKET_SNAPSHOT_RETENTION_TRIM_TARGET_FRACTION = 0.90
CLOSE_VOLUME_TOLERANCE = 1e-9


class BrokerSnapshotUnavailable(RuntimeError):
    """Raised when MT5 broker truth cannot be read safely."""


class LiveStateAtomicReplaceError(RuntimeError):
    """Raised when production state cannot be replaced atomically."""


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
    market_snapshot_journal_path: str = "data/live/lpfs_live_market_snapshots.jsonl"
    market_snapshot_journal_max_bytes: int = DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES
    state_path: str = "data/live/lpfs_live_state.json"
    max_lots_per_order: float | None = None
    max_risk_pct_per_trade: float = 0.75
    risk_buckets_pct: dict[str, float] | None = None
    risk_bucket_scale: float = 0.05
    max_open_risk_pct: float = 0.65
    max_same_symbol_stack: int = 4
    max_concurrent_strategy_trades: int = 17
    strategy_magic: int = 131500
    order_comment_prefix: str = "LPFS"
    pivot_strength: int = 3
    max_bars_from_lp_break: int = 6
    require_lp_pivot_before_fs_mother: bool = True
    max_entry_wait_bars: int = 6
    max_spread_risk_fraction: float = 0.10
    market_recovery_mode: str = "disabled"
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
    diagnostics: dict[str, Any] | None = None
    timestamp_semantics_version: str = LEGACY_HELSINKI_RELOCALIZED_V1
    signal_key_timestamp_semantics_version: str = LEGACY_HELSINKI_RELOCALIZED_V1
    legacy_signal_key: str | None = None

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
        values.setdefault("diagnostics", None)
        values.setdefault("timestamp_semantics_version", LEGACY_HELSINKI_RELOCALIZED_V1)
        values.setdefault("signal_key_timestamp_semantics_version", LEGACY_HELSINKI_RELOCALIZED_V1)
        values.setdefault("legacy_signal_key", None)
        return cls(**values)


@dataclass(frozen=True)
class LiveCloseDealSummary:
    """Compact MT5 exit deal evidence retained for partial/final close accounting."""

    ticket: int
    position_id: int
    volume: float
    price: float
    profit: float
    close_reason: str
    close_time_utc: str
    comment: str
    timestamp_semantics_version: str = MT5_EPOCH_UTC_V2
    raw_mt5_time: int | None = None
    raw_mt5_time_msc: int | None = None
    timestamp_provenance: str = "mt5_epoch"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LiveCloseDealSummary":
        values = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        values.setdefault("volume", 0.0)
        values.setdefault("price", 0.0)
        values.setdefault("profit", 0.0)
        values.setdefault("close_reason", "manual")
        values.setdefault("close_time_utc", "")
        values.setdefault("comment", "")
        values.setdefault("timestamp_semantics_version", MT5_EPOCH_UTC_V2)
        values.setdefault("raw_mt5_time", None)
        values.setdefault("raw_mt5_time_msc", None)
        values.setdefault("timestamp_provenance", "mt5_epoch")
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
    diagnostics: dict[str, Any] | None = None
    timestamp_semantics_version: str = LEGACY_HELSINKI_RELOCALIZED_V1
    raw_mt5_time: int | None = None
    raw_mt5_time_msc: int | None = None
    timestamp_provenance: str = "legacy_state"
    signal_key_timestamp_semantics_version: str = LEGACY_HELSINKI_RELOCALIZED_V1
    legacy_signal_key: str | None = None
    initial_volume: float | None = None
    remaining_volume: float | None = None
    processed_close_deals: tuple[LiveCloseDealSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LiveTrackedPosition":
        values = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        values.setdefault("price_digits", None)
        values.setdefault("diagnostics", None)
        values.setdefault("timestamp_semantics_version", LEGACY_HELSINKI_RELOCALIZED_V1)
        values.setdefault("raw_mt5_time", None)
        values.setdefault("raw_mt5_time_msc", None)
        values.setdefault("timestamp_provenance", "legacy_state")
        values.setdefault("signal_key_timestamp_semantics_version", LEGACY_HELSINKI_RELOCALIZED_V1)
        values.setdefault("legacy_signal_key", None)
        values.setdefault("initial_volume", values.get("volume"))
        values.setdefault("remaining_volume", values.get("volume"))
        values["processed_close_deals"] = tuple(
            LiveCloseDealSummary.from_dict(item) for item in values.get("processed_close_deals", ()) or ()
        )
        return cls(**values)


@dataclass(frozen=True)
class LiveRecoveryAttempt:
    """Durable idempotency marker for one market-recovery DEAL attempt."""

    recovery_attempt_id: str
    signal_key: str
    symbol: str
    timeframe: str
    side: str
    original_entry: float
    fill_price: float
    stop_loss: float
    take_profit: float
    volume: float
    target_risk_pct: float
    actual_risk_pct: float
    magic: int
    comment: str
    setup_id: str
    status: str = "presend_recorded"
    created_time_utc: str = ""
    updated_time_utc: str = ""
    quote_path_evidence: dict[str, Any] | None = None
    order_ticket: int | None = None
    deal_ticket: int | None = None
    position_id: int | None = None
    timestamp_semantics_version: str = MT5_EPOCH_UTC_V2
    timestamp_provenance: str = "system_utc"
    signal_time_utc: str | None = None
    max_entry_wait_bars: int = 6
    strategy_expiry_mode: str = "bar_count"
    broker_backstop_expiration_time_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LiveRecoveryAttempt":
        values = {key: payload[key] for key in cls.__dataclass_fields__ if key in payload}
        values.setdefault("status", "presend_recorded")
        values.setdefault("created_time_utc", "")
        values.setdefault("updated_time_utc", "")
        values.setdefault("quote_path_evidence", None)
        values.setdefault("order_ticket", None)
        values.setdefault("deal_ticket", None)
        values.setdefault("position_id", None)
        values.setdefault("timestamp_semantics_version", MT5_EPOCH_UTC_V2)
        values.setdefault("timestamp_provenance", "system_utc")
        values.setdefault("target_risk_pct", 0.0)
        values.setdefault("actual_risk_pct", 0.0)
        values.setdefault("signal_time_utc", _signal_time_from_signal_key(str(payload.get("signal_key", ""))))
        values.setdefault("max_entry_wait_bars", 6)
        values.setdefault("strategy_expiry_mode", "bar_count")
        values.setdefault("broker_backstop_expiration_time_utc", None)
        return cls(**values)


@dataclass(frozen=True)
class LiveExecutorState:
    """Restart-safe live state for idempotency and lifecycle alerts."""

    processed_signal_keys: tuple[str, ...] = ()
    processed_signal_key_semantics: dict[str, str] = field(default_factory=dict)
    order_checked_signal_keys: tuple[str, ...] = ()
    order_checked_signal_key_semantics: dict[str, str] = field(default_factory=dict)
    pending_orders: tuple[LiveTrackedOrder, ...] = ()
    active_positions: tuple[LiveTrackedPosition, ...] = ()
    notified_event_keys: tuple[str, ...] = ()
    last_seen_close_ticket: int | None = None
    last_seen_close_time_utc: str | None = None
    last_seen_close_timestamp_semantics_version: str | None = None
    telegram_message_ids: dict[str, int] = field(default_factory=dict)
    state_writer_timestamp_semantics_version: str = MT5_EPOCH_UTC_V2
    reconciliation_receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    recovery_attempts: tuple[LiveRecoveryAttempt, ...] = ()

    def __post_init__(self) -> None:
        processed = dict(self.processed_signal_key_semantics)
        checked = dict(self.order_checked_signal_key_semantics)
        for key in self.processed_signal_keys:
            processed.setdefault(key, MT5_EPOCH_UTC_V2)
        for key in self.order_checked_signal_keys:
            checked.setdefault(key, MT5_EPOCH_UTC_V2)
        object.__setattr__(self, "processed_signal_key_semantics", processed)
        object.__setattr__(self, "order_checked_signal_key_semantics", checked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed_signal_keys": list(self.processed_signal_keys),
            "processed_signal_key_semantics": dict(self.processed_signal_key_semantics),
            "order_checked_signal_keys": list(self.order_checked_signal_keys),
            "order_checked_signal_key_semantics": dict(self.order_checked_signal_key_semantics),
            "pending_orders": [order.to_dict() for order in self.pending_orders],
            "active_positions": [position.to_dict() for position in self.active_positions],
            "notified_event_keys": list(self.notified_event_keys),
            "last_seen_close_ticket": self.last_seen_close_ticket,
            "last_seen_close_time_utc": self.last_seen_close_time_utc,
            "last_seen_close_timestamp_semantics_version": self.last_seen_close_timestamp_semantics_version,
            "telegram_message_ids": dict(self.telegram_message_ids),
            "state_writer_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "reconciliation_receipts": dict(self.reconciliation_receipts),
            "recovery_attempts": [attempt.to_dict() for attempt in self.recovery_attempts],
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
    quote_path_evidence: dict[str, Any] | None = None
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
    timestamp_semantics_version: str = MT5_EPOCH_UTC_V2
    raw_mt5_time: int | None = None
    raw_mt5_time_msc: int | None = None
    timestamp_provenance: str = "mt5_epoch"
    close_volume: float | None = None
    initial_volume: float | None = None
    remaining_volume: float | None = None
    aggregate_close_profit: float | None = None
    aggregate_r_result: float | None = None
    close_deal_tickets: tuple[int, ...] = ()
    close_deal_count: int = 1
    close_reason_detail: str = ""
    close_deals: tuple[LiveCloseDealSummary, ...] = ()

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
    frames_skipped: int
    orders_sent: int
    setups_rejected: int
    setups_blocked: int = 0
    market_data_fetch_failures: int = 0
    cycle_degraded: bool = False
    cycle_degraded_reason: str | None = None
    latest_market_data_fetch_error: str | None = None
    market_snapshot_journal_path: str | None = None
    market_snapshot_journal_max_bytes: int | None = None
    market_snapshot_telemetry_write_failures: int = 0
    market_snapshot_telemetry_retention_failures: int = 0
    latest_market_snapshot_telemetry_write_error: str | None = None
    latest_market_snapshot_telemetry_retention_error: str | None = None


@dataclass(frozen=True)
class MarketSnapshotTelemetryOutcome:
    """Best-effort result from writing quote telemetry outside the lifecycle journal."""

    write_failed: bool = False
    retention_failed: bool = False
    write_error: str | None = None
    retention_error: str | None = None


@dataclass(frozen=True)
class ReconciliationOnlyResult:
    """Result of an isolated, no-send reconciliation-only transaction."""

    state: LiveExecutorState
    operation_id: str
    classifications: tuple[dict[str, Any], ...]
    journal_rows_backfilled: int


@dataclass(frozen=True)
class ValidatedBrokerSnapshot:
    """Fail-closed MT5 snapshot collected before local reconciliation writes."""

    account_login: str
    account_server: str
    orders: tuple[Any, ...]
    positions: tuple[Any, ...]
    history_orders: tuple[Any, ...]
    history_deals: tuple[Any, ...]

    def stable_hash(self) -> str:
        payload = {
            "account_login": self.account_login,
            "account_server": self.account_server,
            "orders": _stable_broker_items(self.orders),
            "positions": _stable_broker_items(self.positions),
            "history_orders": _stable_broker_items(self.history_orders),
            "history_deals": _stable_broker_items(self.history_deals),
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reconcile_only_live_state(
    mt5_module: Any,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
) -> ReconciliationOnlyResult:
    """Clean proven stale pending records without scanning setups or writing MT5."""

    snapshot = validated_broker_snapshot(mt5_module, config)
    _validate_operational_signal_keys(state, journal_path=config.journal_path)
    backfilled = _backfill_saved_reconciliation_rows(config, state)
    if snapshot.orders:
        tickets = sorted(int(getattr(order, "ticket", 0) or 0) for order in snapshot.orders)
        raise RuntimeError(f"Reconciliation-only requires zero LPFS broker pending orders; found {tickets}.")
    local_positions = sorted(position.position_id for position in state.active_positions)
    broker_positions = sorted(_position_id(position) for position in snapshot.positions)
    if local_positions != broker_positions:
        raise RuntimeError(
            f"Reconciliation-only active-position mismatch: local={local_positions} broker={broker_positions}."
        )
    if not state.pending_orders:
        if state.reconciliation_receipts:
            return ReconciliationOnlyResult(
                state=state,
                operation_id=sorted(state.reconciliation_receipts)[-1],
                classifications=(),
                journal_rows_backfilled=backfilled,
            )
        return _commit_reconciliation_receipt(
            config,
            state,
            snapshot=snapshot,
            classifications=(),
            broker_positions=broker_positions,
            journal_rows_backfilled=backfilled,
        )

    classifications = tuple(
        _classify_stale_pending_for_reconciliation(
            mt5_module,
            pending,
            snapshot=snapshot,
            active_position_ids=set(broker_positions),
        )
        for pending in state.pending_orders
    )
    unresolved = [item for item in classifications if item["status"] == "unresolved"]
    if unresolved:
        tickets = [item["order_ticket"] for item in unresolved]
        raise RuntimeError(f"Reconciliation-only unresolved local pending records: {tickets}.")

    return _commit_reconciliation_receipt(
        config,
        state,
        snapshot=snapshot,
        classifications=classifications,
        broker_positions=broker_positions,
        journal_rows_backfilled=backfilled,
    )


def _commit_reconciliation_receipt(
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    *,
    snapshot: ValidatedBrokerSnapshot,
    classifications: Sequence[dict[str, Any]],
    broker_positions: Sequence[int],
    journal_rows_backfilled: int,
) -> ReconciliationOnlyResult:
    """Atomically persist one validated reconciliation receipt and its lifecycle rows."""

    reconciliation_kind = "pending_cleanup" if classifications else "clean_noop_migration"
    operation_id = _reconciliation_operation_id(
        state,
        snapshot=snapshot,
        classifications=classifications,
        reconciliation_kind=reconciliation_kind,
    )
    canonical_state = _canonicalize_live_state_signal_keys(state, config)
    receipt = {
        "operation_id": operation_id,
        "reconciliation_kind": reconciliation_kind,
        "state_schema_version": LIVE_STATE_SCHEMA_VERSION,
        "input_state_sha256": _stable_payload_hash(state.to_dict()),
        "snapshot_sha256": snapshot.stable_hash(),
        "account_login": snapshot.account_login,
        "account_server": snapshot.account_server,
        "classifications": list(classifications),
        "active_position_ids": broker_positions,
        "active_position_inventory_sha256": _stable_payload_hash(broker_positions),
    }
    receipts = dict(canonical_state.reconciliation_receipts)
    receipts[operation_id] = receipt
    next_state = replace(canonical_state, pending_orders=(), reconciliation_receipts=receipts)
    _save_live_state(config, next_state)
    journal_rows_backfilled += _append_missing_reconciliation_rows(config, receipt)
    return ReconciliationOnlyResult(
        state=next_state,
        operation_id=operation_id,
        classifications=classifications,
        journal_rows_backfilled=journal_rows_backfilled,
    )


def _classify_stale_pending_for_reconciliation(
    mt5_module: Any,
    pending: LiveTrackedOrder,
    *,
    snapshot: ValidatedBrokerSnapshot,
    active_position_ids: set[int],
) -> dict[str, Any]:
    history_order = next(
        (item for item in snapshot.history_orders if int(getattr(item, "ticket", 0) or 0) == pending.order_ticket),
        None,
    )
    history_deals = [
        item for item in snapshot.history_deals if int(getattr(item, "order", 0) or 0) == pending.order_ticket
    ]
    if history_deals:
        deal_position_ids = {
            int(getattr(item, "position_id", 0) or 0)
            for item in history_deals
            if int(getattr(item, "position_id", 0) or 0)
        }
        if deal_position_ids and deal_position_ids <= active_position_ids:
            return {"order_ticket": pending.order_ticket, "status": "filled_confirmed", "reason": "mt5_deal_history"}
        return {"order_ticket": pending.order_ticket, "status": "unresolved", "reason": "history_deals_present"}
    if history_order is not None and _history_order_manual_cancel_proven(mt5_module, history_order):
        return {"order_ticket": pending.order_ticket, "status": "manual_broker_cancel_confirmed", "reason": "mt5_history"}
    if history_order is not None and _history_order_terminal_state(mt5_module, history_order) in {"expired", "rejected"}:
        return {
            "order_ticket": pending.order_ticket,
            "status": f"{_history_order_terminal_state(mt5_module, history_order)}_confirmed",
            "reason": "mt5_history",
        }
    return {"order_ticket": pending.order_ticket, "status": "unresolved", "reason": "missing_manual_cancel_proof"}


def _history_order_manual_cancel_proven(mt5_module: Any, order: Any) -> bool:
    state = getattr(order, "state", None)
    reason = getattr(order, "reason", None)
    comment = str(getattr(order, "comment", "") or "").casefold()
    state_text = str(state or "").casefold()
    reason_text = str(reason or "").casefold()
    cancelled = state == getattr(mt5_module, "ORDER_STATE_CANCELED", 2) or state_text in {"2", "canceled", "cancelled"}
    manual_reasons = {
        getattr(mt5_module, "ORDER_REASON_CLIENT", object()),
        getattr(mt5_module, "ORDER_REASON_MOBILE", object()),
        getattr(mt5_module, "ORDER_REASON_WEB", object()),
    }
    manual = reason in manual_reasons or any(
        token in reason_text or token in comment for token in ("client", "mobile", "web", "manual", "operator")
    )
    return cancelled and manual


def _history_order_terminal_state(mt5_module: Any, order: Any) -> str | None:
    state = getattr(order, "state", None)
    state_text = str(state or "").casefold()
    if state == getattr(mt5_module, "ORDER_STATE_EXPIRED", 3) or state_text in {"3", "expired"}:
        return "expired"
    if state == getattr(mt5_module, "ORDER_STATE_REJECTED", 4) or state_text in {"4", "rejected"}:
        return "rejected"
    return None


def _reconciliation_operation_id(
    state: LiveExecutorState,
    *,
    snapshot: ValidatedBrokerSnapshot,
    classifications: Sequence[dict[str, Any]],
    reconciliation_kind: str,
) -> str:
    payload = {
        "account_login": snapshot.account_login,
        "account_server": snapshot.account_server,
        "input_state": state.to_dict(),
        "snapshot_sha256": snapshot.stable_hash(),
        "reconciliation_kind": reconciliation_kind,
        "classifications": sorted(classifications, key=lambda item: int(item["order_ticket"])),
        "active_position_ids": sorted(_position_id(item) for item in snapshot.positions),
        "target_state_schema": LIVE_STATE_SCHEMA_VERSION,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _append_missing_reconciliation_rows(config: LiveSendExecutorConfig, receipt: dict[str, Any]) -> int:
    operation_id = str(receipt["operation_id"])
    existing = _reconciliation_journal_event_ids(config.journal_path, operation_id)
    rows = [
        {
            "event": str(classification.get("status") or "reconciliation_classified"),
            "reconciliation_operation_id": operation_id,
            **classification,
        }
        for classification in receipt.get("classifications", ())
    ]
    rows.append(
        {
            "event": "reconciliation_only_complete",
            "reconciliation_operation_id": operation_id,
            "reconciliation_kind": receipt.get("reconciliation_kind"),
            "active_position_ids": receipt.get("active_position_ids", ()),
            "state_schema_version": receipt.get("state_schema_version"),
        }
    )
    appended = 0
    for index, row in enumerate(rows):
        row_id = f"{operation_id}:{index}"
        if row_id in existing:
            continue
        append_audit_event(config.journal_path, row.pop("event"), reconciliation_row_id=row_id, **row)
        appended += 1
    return appended


def _backfill_saved_reconciliation_rows(config: LiveSendExecutorConfig, state: LiveExecutorState) -> int:
    return sum(
        _append_missing_reconciliation_rows(config, receipt)
        for _, receipt in sorted(state.reconciliation_receipts.items())
    )


def _reconciliation_journal_event_ids(path: str | Path, operation_id: str) -> set[str]:
    journal_path = Path(path)
    if not journal_path.exists():
        return set()
    found: set[str] = set()
    with journal_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if operation_id not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_id = row.get("reconciliation_row_id")
            if row_id:
                found.add(str(row_id))
    return found


def _validate_operational_signal_keys(
    state: LiveExecutorState,
    *,
    journal_path: str | Path | None = None,
) -> None:
    for raw_key, _ in _state_signal_records(state):
        try:
            parse_signal_key(raw_key)
        except TimestampSemanticsError:
            if journal_path is not None:
                append_audit_event(journal_path, "malformed_operational_signal_key", signal_key=raw_key)
            raise


def _canonicalize_live_state_signal_keys(
    state: LiveExecutorState,
    config: LiveSendExecutorConfig,
) -> LiveExecutorState:
    def canonical(raw_key: str, semantics: str | None) -> str:
        return canonical_signal_key(
            raw_key,
            semantics or LEGACY_HELSINKI_RELOCALIZED_V1,
            broker_timezone=DEFAULT_LEGACY_BROKER_TIMEZONE,
        )

    processed = tuple(
        canonical(key, state.processed_signal_key_semantics.get(key))
        for key in state.processed_signal_keys
    )
    checked = tuple(
        canonical(key, state.order_checked_signal_key_semantics.get(key))
        for key in state.order_checked_signal_keys
    )
    pending = tuple(
        replace(
            item,
            signal_key=canonical(item.signal_key, item.signal_key_timestamp_semantics_version),
            signal_key_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
            legacy_signal_key=(
                item.signal_key
                if item.signal_key_timestamp_semantics_version == LEGACY_HELSINKI_RELOCALIZED_V1
                else item.legacy_signal_key
            ),
        )
        for item in state.pending_orders
    )
    active = tuple(
        replace(
            item,
            signal_key=canonical(item.signal_key, item.signal_key_timestamp_semantics_version),
            signal_key_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
            legacy_signal_key=(
                item.signal_key
                if item.signal_key_timestamp_semantics_version == LEGACY_HELSINKI_RELOCALIZED_V1
                else item.legacy_signal_key
            ),
        )
        for item in state.active_positions
    )
    return replace(
        state,
        processed_signal_keys=tuple(dict.fromkeys(processed)),
        processed_signal_key_semantics={key: MT5_EPOCH_UTC_V2 for key in processed},
        order_checked_signal_keys=tuple(dict.fromkeys(checked)),
        order_checked_signal_key_semantics={key: MT5_EPOCH_UTC_V2 for key in checked},
        pending_orders=pending,
        active_positions=active,
    )


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
        market_snapshot_journal_path=str(
            _resolve_local_path(
                base_dir,
                live_payload.get("market_snapshot_journal_path", "data/live/lpfs_live_market_snapshots.jsonl"),
            )
        ),
        market_snapshot_journal_max_bytes=int(
            live_payload.get("market_snapshot_journal_max_bytes", DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES)
        ),
        state_path=str(_resolve_local_path(base_dir, live_payload.get("state_path", "data/live/lpfs_live_state.json"))),
        max_lots_per_order=_optional_float(live_payload.get("max_lots_per_order", dry_executor.max_lots_per_order)),
        max_risk_pct_per_trade=float(
            live_payload.get("max_risk_pct_per_trade", dry_executor.max_risk_pct_per_trade)
        ),
        risk_buckets_pct=_optional_risk_buckets(live_payload.get("risk_buckets_pct", dry_executor.risk_buckets_pct)),
        risk_bucket_scale=float(live_payload.get("risk_bucket_scale", 0.05)),
        max_open_risk_pct=float(live_payload.get("max_open_risk_pct", 0.65)),
        max_same_symbol_stack=int(live_payload.get("max_same_symbol_stack", dry_executor.max_same_symbol_stack)),
        max_concurrent_strategy_trades=int(
            live_payload.get("max_concurrent_strategy_trades", dry_executor.max_concurrent_strategy_trades)
        ),
        strategy_magic=int(live_payload.get("strategy_magic", dry_executor.strategy_magic)),
        order_comment_prefix=str(live_payload.get("order_comment_prefix", dry_executor.order_comment_prefix)),
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
        market_recovery_mode=str(live_payload.get("market_recovery_mode", "disabled")),
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
    if config.market_recovery_mode != "disabled":
        raise LocalConfigError("live_send.market_recovery_mode must be 'disabled' during the recovery safety hold.")
    if config.market_recovery_deviation_points < 0:
        raise LocalConfigError("live_send.market_recovery_deviation_points must be zero or positive.")
    if config.market_snapshot_journal_max_bytes <= 0:
        raise LocalConfigError("live_send.market_snapshot_journal_max_bytes must be positive.")
    if _path_identity(config.journal_path) == _path_identity(config.market_snapshot_journal_path):
        raise LocalConfigError("live_send.market_snapshot_journal_path must differ from live_send.journal_path.")


def _path_identity(path: str | Path) -> str:
    try:
        resolved = Path(path).resolve(strict=False)
    except OSError:
        resolved = Path(path).absolute()
    return os.path.normcase(os.path.normpath(str(resolved)))


def load_live_state(path: str | Path) -> LiveExecutorState:
    """Load restart-continuity state, or an empty local view when absent."""

    state_path = Path(path)
    if not state_path.exists():
        return LiveExecutorState()
    envelope = json.loads(state_path.read_text(encoding="utf-8"))
    schema_version = envelope.get("state_schema_version")
    if schema_version is None:
        payload = envelope
    elif int(schema_version) == LIVE_STATE_SCHEMA_VERSION:
        minimum_reader = int(envelope.get("minimum_reader_schema_version", LIVE_STATE_SCHEMA_VERSION))
        if minimum_reader > LIVE_STATE_SCHEMA_VERSION:
            raise RuntimeError(
                f"LPFS live state requires reader schema {minimum_reader}; "
                f"this binary supports {LIVE_STATE_SCHEMA_VERSION}."
            )
        payload = dict(envelope.get("state", {}) or {})
    else:
        raise RuntimeError(
            f"Unsupported LPFS live state schema {schema_version!r}; "
            f"this binary supports legacy flat state and schema {LIVE_STATE_SCHEMA_VERSION}."
        )
    processed_signal_keys = tuple(payload.get("processed_signal_keys", ()))
    checked_signal_keys = tuple(payload.get("order_checked_signal_keys", ()))
    default_key_semantics = (
        LEGACY_HELSINKI_RELOCALIZED_V1 if schema_version is None else MT5_EPOCH_UTC_V2
    )
    state = LiveExecutorState(
        processed_signal_keys=processed_signal_keys,
        processed_signal_key_semantics={
            key: str(dict(payload.get("processed_signal_key_semantics", {}) or {}).get(key, default_key_semantics))
            for key in processed_signal_keys
        },
        order_checked_signal_keys=checked_signal_keys,
        order_checked_signal_key_semantics={
            key: str(dict(payload.get("order_checked_signal_key_semantics", {}) or {}).get(key, default_key_semantics))
            for key in checked_signal_keys
        },
        pending_orders=tuple(LiveTrackedOrder.from_dict(item) for item in payload.get("pending_orders", ())),
        active_positions=tuple(LiveTrackedPosition.from_dict(item) for item in payload.get("active_positions", ())),
        notified_event_keys=tuple(payload.get("notified_event_keys", ())),
        last_seen_close_ticket=payload.get("last_seen_close_ticket"),
        last_seen_close_time_utc=payload.get("last_seen_close_time_utc"),
        last_seen_close_timestamp_semantics_version=payload.get(
            "last_seen_close_timestamp_semantics_version",
            LEGACY_HELSINKI_RELOCALIZED_V1 if payload.get("last_seen_close_time_utc") else None,
        ),
        telegram_message_ids={
            str(key): int(value)
            for key, value in dict(payload.get("telegram_message_ids", {}) or {}).items()
            if value not in (None, "")
        },
        state_writer_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        reconciliation_receipts=dict(payload.get("reconciliation_receipts", {}) or {}),
        recovery_attempts=tuple(LiveRecoveryAttempt.from_dict(item) for item in payload.get("recovery_attempts", ())),
    )
    return state


def save_live_state(
    path: str | Path,
    state: LiveExecutorState,
    *,
    allow_non_atomic_fallback: bool = False,
    kill_switch_path: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> None:
    """Persist restart-continuity state used around broker-affecting operations."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "state_schema_version": LIVE_STATE_SCHEMA_VERSION,
            "minimum_reader_schema_version": MINIMUM_LIVE_STATE_READER_SCHEMA_VERSION,
            # Deliberate tripwire: legacy readers call tuple(None) and stop.
            "processed_signal_keys": None,
            "state": state.to_dict(),
        },
        indent=2,
    )
    temp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(payload, encoding="utf-8")

    last_error: OSError | None = None
    for attempt in range(3):
        try:
            os.replace(temp_path, state_path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))

    if allow_non_atomic_fallback:
        state_path.write_text(payload, encoding="utf-8")
        try:
            temp_path.unlink()
        except OSError:
            pass
        return

    if kill_switch_path is not None:
        _activate_kill_switch(kill_switch_path, "LPFS automatic stop: atomic live-state replacement failed")
    if journal_path is not None:
        try:
            append_audit_event(
                journal_path,
                "live_state_atomic_replace_failed",
                state_path=str(state_path),
                kill_switch_path=None if kill_switch_path is None else str(kill_switch_path),
                error=f"{type(last_error).__name__}: {last_error}",
            )
        except OSError:
            pass
    try:
        temp_path.unlink()
    except OSError:
        pass
    raise LiveStateAtomicReplaceError(f"Atomic LPFS live-state replacement failed for {state_path}: {last_error}")


def _activate_kill_switch(path: str | Path, reason: str) -> None:
    kill_switch = Path(path)
    kill_switch.parent.mkdir(parents=True, exist_ok=True)
    if kill_switch.exists():
        return
    kill_switch.write_text(f"{reason}\n", encoding="utf-8")


def _save_live_state(config: LiveSendExecutorConfig, state: LiveExecutorState) -> None:
    save_live_state(
        config.state_path,
        state,
        kill_switch_path=Path(config.state_path).parent / "KILL_SWITCH",
        journal_path=config.journal_path,
    )


def live_execution_safety_from_config(config: LiveSendExecutorConfig) -> ExecutionSafetyLimits:
    """Return live-send guardrails."""

    return ExecutionSafetyLimits(
        max_risk_pct_per_trade=config.max_risk_pct_per_trade,
        max_open_risk_pct=config.max_open_risk_pct,
        max_lots_per_order=config.max_lots_per_order,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        max_spread_points=None,
        strategy_magic=config.strategy_magic,
        order_comment_prefix=config.order_comment_prefix,
    )


def live_risk_buckets_from_config(config: LiveSendExecutorConfig) -> dict[str, float]:
    """Return timeframe risk buckets as percentage points of account equity."""

    from .execution_contract import V15_EFFICIENT_RISK_BUCKET_PCT

    if config.risk_bucket_scale <= 0:
        raise ValueError("risk_bucket_scale must be positive.")
    buckets = dict(V15_EFFICIENT_RISK_BUCKET_PCT)
    if config.risk_buckets_pct:
        unknown = sorted(set(config.risk_buckets_pct) - set(buckets))
        if unknown:
            raise ValueError(f"risk_buckets_pct contains unsupported timeframe(s): {', '.join(unknown)}.")
        for timeframe, risk_pct in config.risk_buckets_pct.items():
            if risk_pct <= 0:
                raise ValueError("risk_buckets_pct values must be positive.")
            buckets[timeframe] = risk_pct
    return {timeframe: risk_pct * config.risk_bucket_scale for timeframe, risk_pct in buckets.items()}


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
            status="recovery_quote_path_unavailable",
            detail=str(path_block.get("detail", "")),
            quote_path_evidence=_path_block_evidence(path_block),
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
            quote_path_evidence=_path_block_evidence(path_block),
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
            quote_path_evidence=_path_block_evidence(path_block),
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
            quote_path_evidence=_path_block_evidence(path_block),
            **base_fields,
        )
    return MarketRecoveryCheck(
        checked=True,
        recoverable=True,
        status="market_recovery_ready",
        recalculated_take_profit=recalculated_take_profit,
        spread_risk_fraction=spread_gate.spread_risk_fraction,
        max_spread_risk_fraction=spread_gate.max_spread_risk_fraction,
        quote_path_evidence=_path_block_evidence(path_block),
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
        until_time = pd.Timestamp.now(tz="UTC") if until_time_utc is None else _as_utc_timestamp(until_time_utc)
        if from_time_utc is None:
            return {
                "status": "path_unavailable",
                "detail": "missing executable entry-touch time for market recovery",
                "quote_path_semantics": "mt5_tick_bid_ask_v1",
            }
        from_time = _as_utc_timestamp(from_time_utc)
        ticks = _fetch_executable_ticks(
            mt5_module,
            symbol=str(setup.symbol).upper(),
            start_time_utc=from_time,
            end_time_utc=until_time,
            broker_timezone=config.broker_timezone,
        )
    except Exception as exc:
        return {"status": "path_unavailable", "detail": str(exc), "quote_path_semantics": "mt5_tick_bid_ask_v1"}
    if not ticks:
        return {
            "status": "path_unavailable",
            "detail": "copy_ticks_range returned no executable bid/ask ticks",
            "quote_path_semantics": "mt5_tick_bid_ask_v1",
            "path_checked_from_utc": from_time.isoformat(),
            "path_checked_until_utc": until_time.isoformat(),
        }

    stop = float(setup.stop_price)
    target = float(setup.target_price)
    entry = float(setup.entry_price)
    if setup.side == "long":
        entry_quote_side = "ask"
        exit_quote_side = "bid"
        entry_touches = [tick for tick in ticks if tick["ask"] <= entry]
        stop_hits = [tick for tick in ticks if tick["bid"] <= stop]
        target_hits = [tick for tick in ticks if tick["bid"] >= target]
    else:
        entry_quote_side = "bid"
        exit_quote_side = "ask"
        entry_touches = [tick for tick in ticks if tick["bid"] >= entry]
        stop_hits = [tick for tick in ticks if tick["ask"] >= stop]
        target_hits = [tick for tick in ticks if tick["ask"] <= target]

    evidence_base = {
        "quote_path_semantics": "mt5_tick_bid_ask_v1",
        "entry_quote_side": entry_quote_side,
        "exit_quote_side": exit_quote_side,
        "path_checked_from_utc": from_time.isoformat(),
        "path_checked_until_utc": until_time.isoformat(),
        "tick_count": len(ticks),
    }
    if not entry_touches:
        return {
            "status": "path_unavailable",
            "detail": "executable-side entry touch was not proven by MT5 ticks",
            **evidence_base,
        }

    first_entry = entry_touches[0]
    after_entry_ticks = [
        tick for tick in ticks if _as_utc_timestamp(tick["time_utc"]) >= _as_utc_timestamp(first_entry["time_utc"])
    ]
    if setup.side == "long":
        stop_hits = [tick for tick in after_entry_ticks if tick["bid"] <= stop]
        target_hits = [tick for tick in after_entry_ticks if tick["bid"] >= target]
    else:
        stop_hits = [tick for tick in after_entry_ticks if tick["ask"] >= stop]
        target_hits = [tick for tick in after_entry_ticks if tick["ask"] <= target]

    evidence = {**evidence_base, "entry_touch": _tick_evidence(first_entry)}
    first_stop = _first_tick_touch(stop_hits)
    first_target = _first_tick_touch(target_hits)
    if first_stop is not None and (
        first_target is None or pd.Timestamp(first_stop["time_utc"]) <= pd.Timestamp(first_target["time_utc"])
    ):
        return {"status": "stop_touched", **_tick_touch_fields(first_stop), "quote_path_evidence": evidence}
    if first_target is not None:
        return {"status": "target_touched", **_tick_touch_fields(first_target), "quote_path_evidence": evidence}
    return {"status": "clear", "quote_path_evidence": evidence}


def _fetch_executable_ticks(
    mt5_module: Any,
    *,
    symbol: str,
    start_time_utc: pd.Timestamp,
    end_time_utc: pd.Timestamp,
    broker_timezone: str,
) -> list[dict[str, Any]]:
    if not hasattr(mt5_module, "copy_ticks_range"):
        raise RuntimeError("MT5 copy_ticks_range unavailable for executable recovery path proof")
    if end_time_utc < start_time_utc:
        raise RuntimeError("market recovery path end time is before start time")
    flags = getattr(mt5_module, "COPY_TICKS_ALL", 0)
    raw_ticks = mt5_module.copy_ticks_range(
        symbol,
        start_time_utc.to_pydatetime(),
        end_time_utc.to_pydatetime(),
        flags,
    )
    if raw_ticks is None:
        raise RuntimeError("copy_ticks_range returned None")
    ticks: list[dict[str, Any]] = []
    for raw in raw_ticks:
        bid = _optional_float_attr(raw, "bid")
        ask = _optional_float_attr(raw, "ask")
        if bid is None or ask is None:
            continue
        if not math.isfinite(bid) or not math.isfinite(ask):
            continue
        if bid > ask:
            raise RuntimeError("copy_ticks_range returned inverted bid/ask tick")
        raw_time_msc = getattr(raw, "time_msc", None) if not isinstance(raw, dict) else raw.get("time_msc")
        raw_time = getattr(raw, "time", None) if not isinstance(raw, dict) else raw.get("time")
        if raw_time_msc not in (None, 0):
            time_utc = broker_time_epoch_to_utc(raw_time_msc, broker_timezone, unit="ms")
            provenance = "mt5_time_msc"
        else:
            time_utc = broker_time_epoch_to_utc(raw_time, broker_timezone, unit="s")
            provenance = "mt5_time" if time_utc is not None else "unavailable"
        if time_utc is None:
            continue
        ticks.append(
            {
                "time_utc": pd.Timestamp(time_utc).isoformat(),
                "bid": bid,
                "ask": ask,
                "raw_mt5_time": None if raw_time in (None, 0) else int(raw_time),
                "raw_mt5_time_msc": None if raw_time_msc in (None, 0) else int(raw_time_msc),
                "timestamp_semantics_version": MT5_EPOCH_UTC_V2,
                "timestamp_provenance": provenance,
            }
        )
    return sorted(ticks, key=lambda item: pd.Timestamp(item["time_utc"]))


def _optional_float_attr(item: Any, name: str) -> float | None:
    value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
    if value in (None, ""):
        return None
    return float(value)


def _first_tick_touch(ticks: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not ticks:
        return None
    return sorted(ticks, key=lambda item: pd.Timestamp(item["time_utc"]))[0]


def _tick_evidence(tick: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_utc": tick["time_utc"],
        "bid": tick["bid"],
        "ask": tick["ask"],
        "raw_mt5_time": tick.get("raw_mt5_time"),
        "raw_mt5_time_msc": tick.get("raw_mt5_time_msc"),
        "timestamp_semantics_version": tick.get("timestamp_semantics_version"),
        "timestamp_provenance": tick.get("timestamp_provenance"),
    }


def _tick_touch_fields(tick: dict[str, Any]) -> dict[str, Any]:
    evidence = _tick_evidence(tick)
    return {
        "time_utc": evidence["time_utc"],
        "high": evidence["ask"],
        "low": evidence["bid"],
        "bid": evidence["bid"],
        "ask": evidence["ask"],
        "tick_evidence": evidence,
    }


def _first_touch_row(frame: pd.DataFrame) -> dict[str, Any] | None:
    if frame.empty:
        return None
    first = frame.iloc[0]
    return {
        "time_utc": pd.Timestamp(first["time_utc"]).isoformat(),
        "high": float(first["high"]),
        "low": float(first["low"]),
    }


def _path_block_evidence(path_block: dict[str, Any]) -> dict[str, Any]:
    if isinstance(path_block.get("quote_path_evidence"), dict):
        return dict(path_block["quote_path_evidence"])
    keys = (
        "quote_path_semantics",
        "entry_quote_side",
        "exit_quote_side",
        "path_checked_from_utc",
        "path_checked_until_utc",
        "tick_count",
        "detail",
    )
    return {key: path_block[key] for key in keys if key in path_block}


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
    setup_diagnostics: dict[str, Any] | None = None,
    notifier: TelegramNotifier | None = None,
) -> LiveSetupResult:
    signal_key = signal_key_for_setup(setup)
    if setup_diagnostics is None:
        setup_diagnostics = build_setup_diagnostics(setup, config=config, signal_key=signal_key)
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            execution={"stage": "entry_already_touched_before_placement", "execution_path": "market_recovery"},
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            execution={"stage": "pending_expired_before_market_recovery", "execution_path": "market_recovery"},
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
    _append_market_recovery_lifecycle(
        config,
        "market_recovery_candidate",
        **_market_recovery_lifecycle_fields(
            signal_key=signal_key,
            setup=setup,
            recovery_check=recovery_check,
            reason=recovery_check.status,
        ),
        market=asdict(recovery_market),
    )
    if not recovery_check.checked:
        _append_market_recovery_lifecycle(
            config,
            "market_recovery_blocked",
            **_market_recovery_lifecycle_fields(
                signal_key=signal_key,
                setup=setup,
                recovery_check=recovery_check,
                reason=recovery_check.status,
            ),
        )
        event = _rejection_event(
            recovery_check.status,
            recovery_check.detail or "Could not verify market recovery path.",
            signal_key,
            recovery_check.to_dict(),
        )
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=recovery_market,
            execution={"stage": "market_recovery_check_unavailable", "execution_path": "market_recovery"},
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:market_recovery_unavailable", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")
    if not recovery_check.recoverable:
        _append_market_recovery_lifecycle(
            config,
            "market_recovery_blocked",
            **_market_recovery_lifecycle_fields(
                signal_key=signal_key,
                setup=setup,
                recovery_check=recovery_check,
                reason=recovery_check.status,
            ),
        )
        event = _rejection_event(
            recovery_check.status,
            recovery_check.detail or "Missed pending entry is not eligible for market recovery.",
            signal_key,
            recovery_check.to_dict(),
        )
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=recovery_market,
            execution={
                "stage": recovery_check.status,
                "execution_path": "market_recovery",
                "spread_risk_fraction": recovery_check.spread_risk_fraction,
            },
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=recovery_market,
            execution={"stage": "market_recovery_intent_failed", "execution_path": "market_recovery"},
        )
        next_state = _with_processed_key(state, signal_key)
        next_state = _record_event_once(config, next_state, notifier, f"setup_rejected:{signal_key}:market_recovery_intent", event)
        return LiveSetupResult(state=next_state, signal_key=signal_key, status="rejected")

    intent_diagnostics = enrich_diagnostics(
        setup_diagnostics,
        market=recovery_market,
        execution={
            "stage": "market_recovery_intent_created",
            "execution_path": "market_recovery",
            "broker_money_risk_per_lot": risk_per_lot,
            "spread_risk_fraction": recovery_check.spread_risk_fraction,
        },
    )
    append_audit_event(
        config.journal_path,
        "market_recovery_intent_created",
        signal_key=signal_key,
        recovery_check=recovery_check.to_dict(),
        intent=intent.to_dict(),
        broker_money_risk_per_lot=risk_per_lot,
        diagnostic_schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        diagnostics=intent_diagnostics,
    )
    recovery_attempt_id = _recovery_attempt_id(intent, recovery_check)
    existing_recovery_attempt = _unresolved_recovery_attempt_for_id(state, recovery_attempt_id)
    try:
        recovery_snapshot = validated_broker_snapshot(mt5_module, config)
    except BrokerSnapshotUnavailable as exc:
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="broker_snapshot_unavailable_before_recovery_send",
            error=str(exc),
        )
        return LiveSetupResult(state=state, signal_key=signal_key, status="blocked")
    adopted = _adopt_market_recovery_from_broker(
        mt5_module,
        intent,
        config=config,
        state=state,
        symbol_spec=symbol_spec,
        snapshot=recovery_snapshot,
        recovery_check=recovery_check,
        recovery_attempt_id=recovery_attempt_id,
        notifier=notifier,
        diagnostics=intent_diagnostics,
    )
    if adopted is not None:
        return adopted
    history_only_reason = _history_only_recovery_execution_reason(
        mt5_module,
        intent,
        recovery_snapshot,
        symbol_spec,
        reason="history_deal_without_matching_open_position_before_send",
        ambiguous_reason="ambiguous_history_deals_before_send",
    )
    if history_only_reason is not None:
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason=history_only_reason,
        )
        blocked_state = state
        if existing_recovery_attempt is not None:
            blocked_state = _mark_recovery_attempt(blocked_state, existing_recovery_attempt, status="reconcile_required")
            _save_live_state(config, blocked_state)
        return LiveSetupResult(state=blocked_state, signal_key=signal_key, status="blocked")
    if existing_recovery_attempt is not None:
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="unresolved_recovery_attempt_without_broker_execution",
        )
        blocked_state = _mark_recovery_attempt(state, existing_recovery_attempt, status="reconcile_required")
        _save_live_state(config, blocked_state)
        return LiveSetupResult(state=blocked_state, signal_key=signal_key, status="blocked")
    processed_state = _with_processed_key(state, signal_key)
    order_check = run_market_order_check(
        mt5_module,
        intent,
        deviation_points=config.market_recovery_deviation_points,
    )
    checked_state = _with_checked_key(processed_state, signal_key)
    if not order_check.passed:
        if _is_market_closed_block(order_check.retcode, order_check.comment):
            event = _retryable_broker_block_event(
                "market_closed",
                signal_key,
                order_check.retcode,
                order_check.comment,
                {"execution_type": "market_recovery", **recovery_check.to_dict()},
            )
            event = _with_event_diagnostics(
                event,
                intent_diagnostics,
                market=recovery_market,
                execution={
                    "stage": "market_recovery_order_check_blocked",
                    "execution_path": "market_recovery",
                    "order_check_retcode": order_check.retcode,
                    "order_check_comment": order_check.comment,
                },
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:market_closed", event)
            return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check)
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
        event = _with_event_diagnostics(
            event,
            intent_diagnostics,
            market=recovery_market,
            execution={
                "stage": "market_recovery_order_check_failed",
                "execution_path": "market_recovery",
                "order_check_retcode": order_check.retcode,
                "order_check_comment": order_check.comment,
            },
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"market_recovery_check_failed:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_check_failed", order_check=order_check)

    attempt = _recovery_attempt_from_intent(intent, recovery_check, recovery_attempt_id)
    checked_state = _record_market_recovery_presend(
        config,
        checked_state,
        attempt=attempt,
        intent=intent,
        recovery_check=recovery_check,
    )
    outcome = send_market_recovery_order(
        mt5_module,
        intent,
        deviation_points=config.market_recovery_deviation_points,
        checked_request=order_check.request,
    )
    if not outcome.sent:
        try:
            post_send_snapshot = validated_broker_snapshot(mt5_module, config)
        except BrokerSnapshotUnavailable as exc:
            _record_market_recovery_reconcile_required(
                config,
                signal_key=signal_key,
                setup=setup,
                intent=intent,
                recovery_check=recovery_check,
                recovery_attempt_id=recovery_attempt_id,
                reason="broker_snapshot_unavailable_after_recovery_send_attempt",
                error=str(exc),
            )
            reconcile_state = _mark_recovery_attempt(checked_state, attempt, status="reconcile_required")
            _save_live_state(config, reconcile_state)
            return LiveSetupResult(
                state=reconcile_state,
                signal_key=signal_key,
                status="blocked",
                order_check=order_check,
                order_send=outcome,
            )
        adopted_after_send = _adopt_market_recovery_from_broker(
            mt5_module,
            intent,
            config=config,
            state=checked_state,
            symbol_spec=symbol_spec,
            snapshot=post_send_snapshot,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            notifier=notifier,
            diagnostics=intent_diagnostics,
        )
        if adopted_after_send is not None:
            return adopted_after_send
        history_only_reason = _history_only_recovery_execution_reason(
            mt5_module,
            intent,
            post_send_snapshot,
            symbol_spec,
            reason="history_deal_without_matching_open_position_after_send_attempt",
            ambiguous_reason="ambiguous_history_deals_after_send_attempt",
        )
        if history_only_reason is not None:
            _record_market_recovery_reconcile_required(
                config,
                signal_key=signal_key,
                setup=setup,
                intent=intent,
                recovery_check=recovery_check,
                recovery_attempt_id=recovery_attempt_id,
                reason=history_only_reason,
            )
            reconcile_state = _mark_recovery_attempt(checked_state, attempt, status="reconcile_required")
            _save_live_state(config, reconcile_state)
            return LiveSetupResult(
                state=reconcile_state,
                signal_key=signal_key,
                status="blocked",
                order_check=order_check,
                order_send=outcome,
            )
        retry_status = _retryable_order_send_block_status(outcome)
        if retry_status is not None:
            event = _retryable_broker_block_event(
                retry_status,
                signal_key,
                outcome.retcode,
                outcome.comment,
                {
                    "execution_type": "market_recovery",
                    **recovery_check.to_dict(),
                },
            )
            event = _with_event_diagnostics(
                event,
                intent_diagnostics,
                market=recovery_market,
                execution={
                    "stage": "market_recovery_order_send_blocked",
                    "execution_path": "market_recovery",
                    "order_check_retcode": order_check.retcode,
                    "order_send_retcode": outcome.retcode,
                    "order_send_comment": outcome.comment,
                },
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:{retry_status}", event)
            return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check, order_send=outcome)
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="ambiguous_or_unknown_recovery_send_result",
            error=f"retcode={outcome.retcode!r} comment={outcome.comment!r}",
        )
        reconcile_state = _mark_recovery_attempt(checked_state, attempt, status="reconcile_required")
        _save_live_state(config, reconcile_state)
        return LiveSetupResult(
            state=reconcile_state,
            signal_key=signal_key,
            status="blocked",
            order_check=order_check,
            order_send=outcome,
        )

    try:
        post_send_snapshot = validated_broker_snapshot(mt5_module, config)
    except BrokerSnapshotUnavailable as exc:
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="broker_snapshot_unavailable_after_recovery_send",
            error=str(exc),
        )
        reconcile_state = _mark_recovery_attempt(checked_state, attempt, status="reconcile_required")
        _save_live_state(config, reconcile_state)
        return LiveSetupResult(
            state=reconcile_state,
            signal_key=signal_key,
            status="blocked",
            order_check=order_check,
            order_send=outcome,
        )
    position = _matching_recovery_position_from_snapshot(mt5_module, intent, post_send_snapshot, symbol_spec)
    if position is None:
        reason = _history_only_recovery_execution_reason(
            mt5_module,
            intent,
            post_send_snapshot,
            symbol_spec,
            reason="history_deal_without_matching_open_position_after_recovery_send",
            ambiguous_reason="ambiguous_history_deals_after_recovery_send",
        )
        if reason is None:
            reason = "broker_position_missing_after_recovery_send"
        _record_market_recovery_reconcile_required(
            config,
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason=reason,
        )
        reconcile_state = _mark_recovery_attempt(checked_state, attempt, status="reconcile_required")
        _save_live_state(config, reconcile_state)
        return LiveSetupResult(
            state=reconcile_state,
            signal_key=signal_key,
            status="blocked",
            order_check=order_check,
            order_send=outcome,
        )
    deal = _matching_recovery_entry_deal_from_snapshot(mt5_module, intent, post_send_snapshot, symbol_spec)
    send_diagnostics = enrich_diagnostics(
        intent_diagnostics,
        market=recovery_market,
        execution={
            "stage": "market_recovery_sent",
            "execution_path": "market_recovery",
            "order_check_retcode": order_check.retcode,
            "order_check_comment": order_check.comment,
            "order_send_retcode": outcome.retcode,
            "order_send_comment": outcome.comment,
            "signal_to_fill_seconds": _signal_to_event_seconds(signal_key, intent.timeframe, _position_time_utc(position, config)),
        },
    )
    tracked_position = _tracked_position_from_intent(
        intent,
        position,
        config,
        price_digits=symbol_spec.digits,
        diagnostics=send_diagnostics,
    )
    next_state = replace(checked_state, active_positions=(*checked_state.active_positions, tracked_position))
    next_state = _mark_recovery_attempt(
        next_state,
        attempt,
        status="sent",
        order_ticket=outcome.order_ticket or tracked_position.order_ticket,
        deal_ticket=outcome.deal_ticket or (None if deal is None else _optional_int(getattr(deal, "ticket", None))),
        position_id=tracked_position.position_id,
    )
    # Persist broker-affecting state before best-effort notification delivery.
    _save_live_state(config, next_state)
    event = _market_recovery_sent_event(tracked_position, outcome, recovery_check, recovery_attempt_id=recovery_attempt_id)
    thread_key = f"order:{tracked_position.order_ticket}"
    next_state = _record_event_once(
        config,
        next_state,
        notifier,
        f"market_recovery_sent:{tracked_position.position_id}:{outcome.deal_ticket or outcome.order_ticket or 0}",
        event,
        store_thread_key=thread_key,
    )
    _append_market_recovery_lifecycle(
        config,
        "market_recovery_sent",
        **_market_recovery_lifecycle_fields(
            signal_key=signal_key,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="broker_position_confirmed_after_send",
            broker_item=position,
        ),
        order_send=outcome.to_dict(),
        broker_deal=None if deal is None else _broker_item_dict(deal),
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
    setup_diagnostics = build_setup_diagnostics(setup, config=config, signal_key=signal_key)
    try:
        already_processed = _state_has_equivalent_signal_key(state, signal_key, config=config)
    except TimestampSemanticsError as exc:
        append_audit_event(
            config.journal_path,
            "malformed_operational_signal_key",
            signal_key=signal_key,
            error=str(exc),
        )
        return LiveSetupResult(state=state, signal_key=signal_key, status="blocked")
    if already_processed:
        append_audit_event(
            config.journal_path,
            "signal_already_processed",
            signal_key=signal_key,
            diagnostic_schema_version=DIAGNOSTIC_SCHEMA_VERSION,
            diagnostics=setup_diagnostics,
        )
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=first_market,
            execution={"stage": "missed_entry_check_unavailable", "execution_path": "pending_limit"},
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=first_market,
            execution={"stage": "bar_expiry_check_unavailable", "execution_path": "pending_limit"},
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
            setup_diagnostics=setup_diagnostics,
            notifier=notifier,
        )

    if bar_expiry.expired:
        event = _rejection_event(
            "pending_expired",
            "The pullback window expired by actual MT5 bar count before live placement.",
            signal_key,
            bar_expiry.to_dict(),
        )
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=first_market,
            execution={"stage": "pending_expired_before_placement", "execution_path": "pending_limit"},
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
        event = _with_event_diagnostics(
            event,
            setup_diagnostics,
            market=first_market,
            spread_gate=pre_spread,
            execution={"stage": "pre_spread_gate", "execution_path": "pending_limit"},
        )
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
    decision_event = notification_from_execution_decision(
        decision,
        mode="LIVE",
        setup=setup,
        market=first_market,
        price_digits=symbol_spec.digits,
    )
    decision_diagnostics = enrich_diagnostics(
        setup_diagnostics,
        market=first_market,
        spread_gate=pre_spread,
        execution={
            "stage": "order_intent_created",
            "execution_path": "pending_limit",
            "decision_status": decision.status,
            "rejection_reason": decision.rejection_reason,
            "broker_money_risk_per_lot": risk_per_lot,
        },
    )
    decision_event = _with_event_diagnostics(decision_event, decision_diagnostics)
    append_audit_event(
        config.journal_path,
        decision_event.kind,
        signal_key=signal_key,
        notification=format_notification_message(decision_event),
        decision=decision.to_dict(),
        broker_money_risk_per_lot=risk_per_lot,
        diagnostic_schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        diagnostics=decision_diagnostics,
    )
    processed_state = _with_processed_key(state, signal_key)
    if not decision.ready or decision.intent is None:
        processed_state = _record_event_once(config, processed_state, notifier, f"setup_rejected:{signal_key}", decision_event)
        return LiveSetupResult(state=processed_state, signal_key=signal_key, status="rejected")

    order_check = run_order_check(mt5_module, decision.intent)
    checked_state = _with_checked_key(processed_state, signal_key)
    if not order_check.passed:
        if _is_market_closed_block(order_check.retcode, order_check.comment):
            event = _retryable_broker_block_event("market_closed", signal_key, order_check.retcode, order_check.comment)
            event = _with_event_diagnostics(
                event,
                decision_diagnostics,
                market=first_market,
                spread_gate=pre_spread,
                execution={
                    "stage": "order_check_blocked",
                    "execution_path": "pending_limit",
                    "order_check_retcode": order_check.retcode,
                    "order_check_comment": order_check.comment,
                },
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:market_closed", event)
            return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check)
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
        event = _with_event_diagnostics(
            event,
            decision_diagnostics,
            market=first_market,
            spread_gate=pre_spread,
            execution={
                "stage": "order_check_failed",
                "execution_path": "pending_limit",
                "order_check_retcode": order_check.retcode,
                "order_check_comment": order_check.comment,
            },
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"order_check_failed:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_check_failed", order_check=order_check)

    try:
        final_market = market_snapshot_from_mt5(mt5_module, setup.symbol, broker_timezone=config.broker_timezone)
    except Exception as exc:
        event = _rejection_event(
            "final_quote_unavailable_before_send",
            "Could not refresh executable quote immediately before order_send.",
            signal_key,
            {
                "signal_key": signal_key,
                "symbol": setup.symbol,
                "timeframe": setup.timeframe,
                "side": setup.side,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "order_check_retcode": order_check.retcode,
                "order_check_comment": order_check.comment,
            },
        )
        event = _with_event_diagnostics(
            event,
            decision_diagnostics,
            market=first_market,
            spread_gate=pre_spread,
            execution={
                "stage": "final_quote_unavailable_before_send",
                "execution_path": "pending_limit",
                "order_check_retcode": order_check.retcode,
                "order_check_comment": order_check.comment,
                "quote_error_type": type(exc).__name__,
                "quote_error": str(exc),
            },
        )
        retry_state = _without_processed_key(checked_state, signal_key)
        retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:final_quote_unavailable", event)
        return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check)
    final_spread = dynamic_spread_gate(
        setup,
        symbol_spec,
        final_market,
        max_spread_risk_fraction=config.max_spread_risk_fraction,
    )
    if not final_spread.passed:
        event = _rejection_event("spread_too_wide_before_send", "Spread widened before order_send.", signal_key, final_spread.to_dict())
        event = _with_event_diagnostics(
            event,
            decision_diagnostics,
            market=final_market,
            spread_gate=final_spread,
            execution={"stage": "final_spread_gate", "execution_path": "pending_limit"},
        )
        retry_state = _without_processed_key(checked_state, signal_key)
        retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:final_spread", event)
        return LiveSetupResult(state=retry_state, signal_key=signal_key, status="blocked", order_check=order_check)

    send_diagnostics = enrich_diagnostics(
        decision_diagnostics,
        market=final_market,
        spread_gate=final_spread,
        execution={
            "stage": "pre_order_send",
            "execution_path": "pending_limit",
            "order_check_retcode": order_check.retcode,
            "order_check_comment": order_check.comment,
        },
    )
    # WARNING: Keep exact broker-item adoption before order_send. Moving this
    # later can duplicate pending orders when broker truth leads local state.
    adopted = _adopt_existing_broker_item(
        mt5_module,
        decision.intent,
        config=config,
        state=checked_state,
        symbol_spec=symbol_spec,
        notifier=notifier,
        diagnostics=send_diagnostics,
    )
    if adopted is not None:
        return adopted

    outcome = send_pending_order(mt5_module, decision.intent)
    if not outcome.sent or outcome.order_ticket is None:
        retry_status = _retryable_order_send_block_status(outcome)
        if retry_status is not None:
            event = _retryable_broker_block_event(retry_status, signal_key, outcome.retcode, outcome.comment)
            event = _with_event_diagnostics(
                event,
                send_diagnostics,
                market=final_market,
                spread_gate=final_spread,
                execution={
                    "stage": "order_send_blocked",
                    "execution_path": "pending_limit",
                    "order_send_retcode": outcome.retcode,
                    "order_send_comment": outcome.comment,
                },
            )
            retry_state = _without_processed_key(checked_state, signal_key)
            retry_state = _record_event_once(config, retry_state, notifier, f"setup_blocked:{signal_key}:{retry_status}", event)
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
        event = _with_event_diagnostics(
            event,
            send_diagnostics,
            market=final_market,
            spread_gate=final_spread,
            execution={
                "stage": "order_rejected",
                "execution_path": "pending_limit",
                "order_send_retcode": outcome.retcode,
                "order_send_comment": outcome.comment,
            },
        )
        checked_state = _record_event_once(config, checked_state, notifier, f"order_rejected:{signal_key}", event)
        return LiveSetupResult(state=checked_state, signal_key=signal_key, status="order_rejected", order_check=order_check, order_send=outcome)

    placed_diagnostics = enrich_diagnostics(
        send_diagnostics,
        market=final_market,
        spread_gate=final_spread,
        execution={
            "stage": "order_sent",
            "execution_path": "pending_limit",
            "order_send_retcode": outcome.retcode,
            "order_send_comment": outcome.comment,
        },
    )
    placed = _tracked_order_from_intent(
        decision.intent,
        outcome.order_ticket,
        price_digits=symbol_spec.digits,
        diagnostics=placed_diagnostics,
    )
    next_state = replace(checked_state, pending_orders=(*checked_state.pending_orders, placed))
    # Persist broker-affecting state before best-effort notification delivery.
    _save_live_state(config, next_state)
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

    snapshot = validated_broker_snapshot(mt5_module, config)
    _validate_operational_signal_keys(state, journal_path=config.journal_path)
    orders = {int(getattr(order, "ticket")): order for order in snapshot.orders}
    positions = snapshot.positions
    next_state = _reconcile_market_recovery_attempts(
        mt5_module,
        config=config,
        state=state,
        snapshot=snapshot,
        notifier=notifier,
    )
    kept_pending: list[LiveTrackedOrder] = []
    new_active: list[LiveTrackedPosition] = list(next_state.active_positions)

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

        position = _matching_position_for_order(mt5_module, pending, positions, config, snapshot=snapshot)
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

        classification = _classify_stale_pending_for_reconciliation(
            mt5_module,
            pending,
            snapshot=snapshot,
            active_position_ids={_position_id(item) for item in positions},
        )
        if classification["status"] == "unresolved":
            kept_pending.append(pending)
            append_audit_event(
                config.journal_path,
                "pending_missing_unresolved",
                pending=pending.to_dict(),
                classification=classification,
            )
            continue
        history_order = _history_order_for_ticket(mt5_module, pending, config, snapshot=snapshot)
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
        broker_position = positions_by_id.get(active.position_id)
        if broker_position is not None:
            broker_volume = _broker_position_volume(broker_position)
            tracked_remaining = _position_remaining_volume(active)
            if broker_volume > tracked_remaining + CLOSE_VOLUME_TOLERANCE:
                kept_active.append(active)
                append_audit_event(
                    config.journal_path,
                    "active_position_volume_mismatch",
                    signal_key=active.signal_key,
                    position_id=active.position_id,
                    tracked_remaining_volume=tracked_remaining,
                    broker_current_volume=broker_volume,
                    position=active.to_dict(),
                )
                continue
            if broker_volume < tracked_remaining - CLOSE_VOLUME_TOLERANCE:
                close_deals = _exit_deal_summaries_for_position(mt5_module, active, config, snapshot=snapshot)
                unprocessed = _unprocessed_close_deals(active, close_deals)
                expected_delta = tracked_remaining - broker_volume
                actual_delta = _close_deal_volume(unprocessed)
                if not _volume_equal(actual_delta, expected_delta):
                    kept_active.append(active)
                    append_audit_event(
                        config.journal_path,
                        "active_position_partial_close_unresolved",
                        signal_key=active.signal_key,
                        position_id=active.position_id,
                        tracked_remaining_volume=tracked_remaining,
                        broker_current_volume=broker_volume,
                        expected_closed_volume=expected_delta,
                        unprocessed_close_volume=actual_delta,
                        unprocessed_close_deals=_close_deals_payload(unprocessed),
                        position=active.to_dict(),
                    )
                    continue
                merged_deals = _merge_close_deal_summaries(active.processed_close_deals, unprocessed)
                updated_active = replace(
                    _active_with_initialized_close_ledger(active),
                    remaining_volume=broker_volume,
                    processed_close_deals=merged_deals,
                )
                append_audit_event(
                    config.journal_path,
                    "position_partially_closed",
                    signal_key=active.signal_key,
                    position_id=active.position_id,
                    symbol=active.symbol,
                    timeframe=active.timeframe,
                    side=active.side,
                    initial_volume=_position_initial_volume(active),
                    previous_remaining_volume=tracked_remaining,
                    closed_volume=actual_delta,
                    remaining_volume=broker_volume,
                    close_profit=sum(float(deal.profit) for deal in unprocessed),
                    aggregate_r_result=_aggregate_close_r(active, unprocessed),
                    close_deal_tickets=[deal.ticket for deal in unprocessed],
                    close_deal_count=len(unprocessed),
                    close_deals=_close_deals_payload(unprocessed),
                    close_reason_detail=_aggregate_close_reason(unprocessed)[1],
                )
                kept_active.append(updated_active)
                continue
            kept_active.append(_active_with_initialized_close_ledger(active, broker_volume=broker_volume))
            continue

        close_deals = _exit_deal_summaries_for_position(mt5_module, active, config, snapshot=snapshot)
        merged_deals = _merge_close_deal_summaries(active.processed_close_deals, close_deals)
        if not merged_deals:
            kept_active.append(active)
            append_audit_event(config.journal_path, "active_position_missing_close", position=active.to_dict())
            continue
        closed_volume = _close_deal_volume(merged_deals)
        initial_volume = _position_initial_volume(active)
        if not _volume_equal(closed_volume, initial_volume):
            kept_active.append(active)
            append_audit_event(
                config.journal_path,
                "active_position_final_close_unresolved",
                signal_key=active.signal_key,
                position_id=active.position_id,
                initial_volume=initial_volume,
                closed_volume=closed_volume,
                close_deals=_close_deals_payload(merged_deals),
                position=active.to_dict(),
            )
            continue
        close = _aggregate_close_event(active, merged_deals)
        event = _close_event(active, close)
        next_state = _record_event_once(
            config,
            next_state,
            None if _close_is_old(next_state, close) else notifier,
            f"close:{active.position_id}:{_close_deal_ticket_hash(merged_deals)}",
            event,
            reply_thread_key=f"order:{active.order_ticket}",
        )
        next_state = replace(
            next_state,
            last_seen_close_ticket=close.ticket,
            last_seen_close_time_utc=close.close_time_utc,
            last_seen_close_timestamp_semantics_version=close.timestamp_semantics_version,
        )

    next_state = replace(next_state, active_positions=tuple(kept_active))
    _save_live_state(config, next_state)
    return next_state


def _reconcile_market_recovery_attempts(
    mt5_module: Any,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    snapshot: ValidatedBrokerSnapshot,
    notifier: TelegramNotifier | None,
) -> LiveExecutorState:
    """Adopt or hold unresolved market-recovery presend markers before scanning."""

    next_state = state
    for attempt in state.recovery_attempts:
        if attempt.status not in {"presend_recorded", "reconcile_required"}:
            continue
        try:
            intent = _intent_from_recovery_attempt(attempt)
            symbol_spec = symbol_spec_from_mt5(mt5_module, intent.symbol)
        except Exception as exc:
            _record_market_recovery_reconcile_required(
                config,
                signal_key=attempt.signal_key,
                setup=None,
                intent=None,
                recovery_check=_market_recovery_check_from_attempt(attempt),
                recovery_attempt_id=attempt.recovery_attempt_id,
                reason="recovery_attempt_reconstruction_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            next_state = _mark_recovery_attempt(next_state, attempt, status="reconcile_required")
            continue
        recovery_check = _market_recovery_check_from_attempt(attempt)
        result = _adopt_market_recovery_from_broker(
            mt5_module,
            intent,
            config=config,
            state=next_state,
            symbol_spec=symbol_spec,
            snapshot=snapshot,
            recovery_check=recovery_check,
            recovery_attempt_id=attempt.recovery_attempt_id,
            notifier=notifier,
            diagnostics={"execution": {"stage": "market_recovery_restart_reconcile", "execution_path": "market_recovery"}},
        )
        if result is not None:
            next_state = result.state
            continue
        reason = _history_only_recovery_execution_reason(
            mt5_module,
            intent,
            snapshot,
            symbol_spec,
            reason="history_deal_without_matching_open_position",
            ambiguous_reason="ambiguous_history_deals_without_matching_open_position",
        )
        if reason is None:
            reason = "unresolved_recovery_attempt_without_broker_execution"
        _record_market_recovery_reconcile_required(
            config,
            signal_key=attempt.signal_key,
            setup=None,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=attempt.recovery_attempt_id,
            reason=reason,
        )
        next_state = _mark_recovery_attempt(next_state, attempt, status="reconcile_required")
    return next_state


def _market_recovery_check_from_attempt(attempt: LiveRecoveryAttempt) -> MarketRecoveryCheck:
    return MarketRecoveryCheck(
        checked=True,
        recoverable=True,
        status="market_recovery_ready",
        original_entry=float(attempt.original_entry),
        fill_price=float(attempt.fill_price),
        stop_loss=float(attempt.stop_loss),
        original_take_profit=None,
        recalculated_take_profit=float(attempt.take_profit),
        quote_path_evidence=attempt.quote_path_evidence,
    )


def retain_market_snapshot_journal(path: str | Path, max_bytes: int) -> None:
    """Keep newest complete telemetry JSONL rows under a lower target using atomic replacement."""

    telemetry_path = Path(path)
    max_size = int(max_bytes)
    if max_size <= 0 or not telemetry_path.exists():
        return
    current_size = telemetry_path.stat().st_size
    if current_size <= max_size:
        return

    trim_target = max(1, int(max_size * MARKET_SNAPSHOT_RETENTION_TRIM_TARGET_FRACTION))
    start_offset = max(0, current_size - trim_target)
    with telemetry_path.open("rb") as handle:
        handle.seek(start_offset - 1)
        if handle.read(1) != b"\n":
            handle.readline()
        payload = handle.read()
    if payload and not payload.endswith(b"\n"):
        boundary = payload.rfind(b"\n")
        payload = b"" if boundary < 0 else payload[: boundary + 1]

    temp_path = telemetry_path.with_name(f".{telemetry_path.name}.{os.getpid()}.retain.tmp")
    try:
        temp_path.write_bytes(payload)
        os.replace(temp_path, telemetry_path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def append_market_snapshot_telemetry(
    config: LiveSendExecutorConfig,
    symbol: str,
    timeframe: str,
    market: MT5MarketSnapshot,
) -> MarketSnapshotTelemetryOutcome:
    """Write quote telemetry best-effort while auditing failures to the lifecycle journal."""

    write_error: str | None = None
    retention_error: str | None = None
    try:
        append_market_snapshot(config.market_snapshot_journal_path, symbol, timeframe, market)
    except Exception as exc:
        write_error = f"{type(exc).__name__}: {exc}"
        try:
            append_audit_event(
                config.journal_path,
                "market_snapshot_telemetry_write_failed",
                symbol=symbol,
                timeframe=timeframe,
                market_snapshot_journal_path=config.market_snapshot_journal_path,
                error=write_error,
            )
        except Exception:
            pass
        return MarketSnapshotTelemetryOutcome(write_failed=True, write_error=write_error)

    try:
        retain_market_snapshot_journal(
            config.market_snapshot_journal_path,
            config.market_snapshot_journal_max_bytes,
        )
    except Exception as exc:
        retention_error = f"{type(exc).__name__}: {exc}"
        try:
            append_audit_event(
                config.journal_path,
                "market_snapshot_telemetry_retention_failed",
                symbol=symbol,
                timeframe=timeframe,
                market_snapshot_journal_path=config.market_snapshot_journal_path,
                market_snapshot_journal_max_bytes=config.market_snapshot_journal_max_bytes,
                error=retention_error,
            )
        except Exception:
            pass
    return MarketSnapshotTelemetryOutcome(
        retention_failed=retention_error is not None,
        retention_error=retention_error,
    )


def run_live_send_cycle(
    mt5_module: Any,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    notifier: TelegramNotifier | None = None,
    setup_provider: SetupProvider = default_setup_provider,
) -> LiveCycleResult:
    """Run one finite live-send polling cycle."""

    # Reconcile MT5 broker truth before scanning completed candles for new sends.
    current_state = reconcile_live_state(mt5_module, config=config, state=state, notifier=notifier)
    _save_live_state(config, current_state)
    frames_processed = 0
    frames_skipped = 0
    orders_sent = 0
    setups_rejected = 0
    setups_blocked = 0
    market_data_fetch_failures = 0
    latest_market_data_fetch_error: str | None = None
    market_data_failure_frames: list[dict[str, Any]] = []
    telemetry_write_failures = 0
    telemetry_retention_failures = 0
    latest_telemetry_write_error: str | None = None
    latest_telemetry_retention_error: str | None = None

    def record_market_data_failure(symbol: str, timeframe: str, exc: Exception) -> None:
        nonlocal frames_skipped, market_data_fetch_failures, latest_market_data_fetch_error
        frames_skipped += 1
        market_data_fetch_failures += 1
        latest_market_data_fetch_error = f"{type(exc).__name__}: {exc}"
        market_data_failure_frames.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "history_bars": int(config.history_bars),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )

    for symbol in config.symbols:
        for timeframe in config.timeframes:
            try:
                frame = fetch_closed_candles(
                    mt5_module,
                    symbol=symbol,
                    timeframe=timeframe,
                    bars=config.history_bars,
                    broker_timezone=config.broker_timezone,
                )
            except Exception as exc:
                record_market_data_failure(symbol, timeframe, exc)
                continue
            try:
                market = market_snapshot_from_mt5(mt5_module, symbol, broker_timezone=config.broker_timezone)
            except Exception as exc:
                record_market_data_failure(symbol, timeframe, exc)
                continue
            telemetry = append_market_snapshot_telemetry(config, symbol, timeframe, market)
            if telemetry.write_failed:
                telemetry_write_failures += 1
                latest_telemetry_write_error = telemetry.write_error
            if telemetry.retention_failed:
                telemetry_retention_failures += 1
                latest_telemetry_retention_error = telemetry.retention_error
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
                _save_live_state(config, current_state)
                orders_sent += 1 if result.status in {"order_sent", "market_recovery_sent"} else 0
                setups_rejected += 1 if result.status == "rejected" else 0
                setups_blocked += 1 if result.status == "blocked" else 0
    _save_live_state(config, current_state)
    total_frames = len(tuple(config.symbols)) * len(tuple(config.timeframes))
    cycle_degraded = market_data_fetch_failures > 0
    cycle_degraded_reason = None
    if cycle_degraded:
        cycle_degraded_reason = (
            "all_market_data_fetch_failed"
            if total_frames > 0 and frames_skipped >= total_frames
            else "partial_market_data_fetch_failure"
        )
        append_audit_event(
            config.journal_path,
            "market_data_frame_fetch_failures",
            severity="warning",
            failure_count=market_data_fetch_failures,
            frames_skipped=frames_skipped,
            frames_processed=frames_processed,
            total_configured_frames=total_frames,
            affected_frames=market_data_failure_frames,
            affected_symbols=sorted({frame["symbol"] for frame in market_data_failure_frames}),
            affected_timeframes=sorted({frame["timeframe"] for frame in market_data_failure_frames}),
            latest_error=latest_market_data_fetch_error,
            all_frames_failed=total_frames > 0 and frames_skipped >= total_frames,
            cycle_degraded=True,
            cycle_degraded_reason=cycle_degraded_reason,
            timestamp_semantics_version=MT5_EPOCH_UTC_V2,
            timestamp_provenance="system_utc",
        )
    return LiveCycleResult(
        state=current_state,
        frames_processed=frames_processed,
        frames_skipped=frames_skipped,
        orders_sent=orders_sent,
        setups_rejected=setups_rejected,
        setups_blocked=setups_blocked,
        market_data_fetch_failures=market_data_fetch_failures,
        cycle_degraded=cycle_degraded,
        cycle_degraded_reason=cycle_degraded_reason,
        latest_market_data_fetch_error=latest_market_data_fetch_error,
        market_snapshot_journal_path=config.market_snapshot_journal_path,
        market_snapshot_journal_max_bytes=config.market_snapshot_journal_max_bytes,
        market_snapshot_telemetry_write_failures=telemetry_write_failures,
        market_snapshot_telemetry_retention_failures=telemetry_retention_failures,
        latest_market_snapshot_telemetry_write_error=latest_telemetry_write_error,
        latest_market_snapshot_telemetry_retention_error=latest_telemetry_retention_error,
    )


def current_strategy_orders(mt5_module: Any, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    """Return configured-symbol broker pending orders filtered by strategy magic."""

    orders: list[Any] = []
    for symbol in config.symbols:
        result = mt5_module.orders_get(symbol=symbol)
        if result is None:
            raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "orders_get", symbol=symbol))
        orders.extend(list(result))
    return tuple(order for order in orders if int(getattr(order, "magic", 0) or 0) == config.strategy_magic)


def current_strategy_positions(mt5_module: Any, config: LiveSendExecutorConfig) -> tuple[Any, ...]:
    """Return configured-symbol broker positions filtered by strategy magic."""

    positions: list[Any] = []
    for symbol in config.symbols:
        result = mt5_module.positions_get(symbol=symbol)
        if result is None:
            raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "positions_get", symbol=symbol))
        positions.extend(list(result))
    return tuple(position for position in positions if int(getattr(position, "magic", 0) or 0) == config.strategy_magic)


def validated_broker_snapshot(mt5_module: Any, config: LiveSendExecutorConfig) -> ValidatedBrokerSnapshot:
    """Collect required MT5 broker truth or fail before local mutation."""

    account = mt5_module.account_info()
    if account is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "account_info"))
    orders = current_strategy_orders(mt5_module, config)
    positions = current_strategy_positions(mt5_module, config)
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    history_orders_result = mt5_module.history_orders_get(start.to_pydatetime(), end.to_pydatetime())
    if history_orders_result is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_orders_get"))
    history_deals_result = mt5_module.history_deals_get(start.to_pydatetime(), end.to_pydatetime())
    if history_deals_result is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_deals_get"))
    # Preserve full history: exit-side deals may omit strategy magic but still
    # prove the lifecycle of a tracked LPFS position or pending order.
    history_orders = tuple(history_orders_result)
    history_deals = tuple(history_deals_result)
    return ValidatedBrokerSnapshot(
        account_login=str(getattr(account, "login", "") or ""),
        account_server=str(getattr(account, "server", "") or ""),
        orders=orders,
        positions=positions,
        history_orders=history_orders,
        history_deals=history_deals,
    )


def latest_close_for_position(
    mt5_module: Any,
    active: LiveTrackedPosition,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> LiveCloseEvent | None:
    close_deals = _exit_deal_summaries_for_position(mt5_module, active, config, snapshot=snapshot)
    if not close_deals:
        return None
    deal = close_deals[-1]
    return LiveCloseEvent(
        ticket=deal.ticket,
        position_id=active.position_id,
        close_reason=deal.close_reason,
        close_time_utc=deal.close_time_utc,
        close_price=deal.price,
        close_profit=deal.profit,
        close_comment=deal.comment,
        timestamp_semantics_version=deal.timestamp_semantics_version,
        raw_mt5_time=deal.raw_mt5_time,
        raw_mt5_time_msc=deal.raw_mt5_time_msc,
        timestamp_provenance=deal.timestamp_provenance,
        close_volume=deal.volume,
        initial_volume=_position_initial_volume(active),
        remaining_volume=0.0,
        aggregate_close_profit=deal.profit,
        aggregate_r_result=_aggregate_close_r(active, (deal,)),
        close_deal_tickets=(deal.ticket,),
        close_deal_count=1,
        close_reason_detail=f"single_{deal.close_reason}_deal",
        close_deals=(deal,),
    )


def _exit_deal_summaries_for_position(
    mt5_module: Any,
    active: LiveTrackedPosition,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> tuple[LiveCloseDealSummary, ...]:
    deals = _history_deals_for_close_lookup(mt5_module, active, config, snapshot=snapshot)
    history_orders = snapshot.history_orders if snapshot is not None else ()
    summaries = [
        _close_deal_summary(mt5_module, deal, config)
        for deal in deals
        if _deal_is_exit(mt5_module, deal)
        and _deal_matches_tracked_position_close(
            mt5_module,
            deal,
            active,
            config,
            history_orders=history_orders,
        )
    ]
    return tuple(sorted(summaries, key=_close_deal_sort_key))


def _history_deals_for_close_lookup(
    mt5_module: Any,
    active: LiveTrackedPosition,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> tuple[Any, ...]:
    return _history_deals_for_position(mt5_module, active.position_id, config, snapshot=snapshot)


def _deal_matches_tracked_position_close(
    mt5_module: Any,
    deal: Any,
    active: LiveTrackedPosition,
    config: LiveSendExecutorConfig,
    *,
    history_orders: Sequence[Any] = (),
) -> bool:
    linked_position_id = _deal_linked_position_id(deal, history_orders)
    if linked_position_id is not None:
        return linked_position_id == active.position_id
    return _fallback_close_deal_matches_active(mt5_module, deal, active, config, history_orders=history_orders)


def _deal_linked_position_id(deal: Any, history_orders: Sequence[Any]) -> int | None:
    linked = _optional_int(getattr(deal, "position_id", None))
    if linked is not None:
        return linked
    order_ticket = _optional_int(getattr(deal, "order", None))
    if order_ticket is None:
        return None
    for order in history_orders:
        if int(getattr(order, "ticket", 0) or 0) != order_ticket:
            continue
        for attr in ("position_id", "position_by_id"):
            linked = _optional_int(getattr(order, attr, None))
            if linked is not None:
                return linked
    return None


def _fallback_close_deal_matches_active(
    mt5_module: Any,
    deal: Any,
    active: LiveTrackedPosition,
    config: LiveSendExecutorConfig,
    *,
    history_orders: Sequence[Any] = (),
) -> bool:
    if str(getattr(deal, "symbol", "") or "").upper() != active.symbol.upper():
        return False
    if int(getattr(deal, "magic", 0) or 0) != int(active.magic):
        return False
    if not _deal_close_side_matches(mt5_module, deal, active):
        return False
    if not _deal_not_before_active_open(deal, active, config):
        return False

    order_ticket = _optional_int(getattr(deal, "order", None))
    if order_ticket is not None:
        for order in history_orders:
            if int(getattr(order, "ticket", 0) or 0) != order_ticket:
                continue
            if str(getattr(order, "symbol", "") or "").upper() != active.symbol.upper():
                return False
            raw_magic = getattr(order, "magic", None)
            order_magic = active.magic if raw_magic in (None, "") else int(raw_magic)
            if int(order_magic) != int(active.magic):
                return False
            order_comment = str(getattr(order, "comment", "") or "")
            if order_comment and active.comment and active.comment not in order_comment:
                return False
            return True

    deal_comment = str(getattr(deal, "comment", "") or "")
    return bool(active.comment and deal_comment and active.comment in deal_comment)


def _deal_close_side_matches(mt5_module: Any, deal: Any, active: LiveTrackedPosition) -> bool:
    fallback_type = getattr(mt5_module, "DEAL_TYPE_SELL", getattr(mt5_module, "ORDER_TYPE_SELL", 1))
    if active.side == "short":
        fallback_type = getattr(mt5_module, "DEAL_TYPE_BUY", getattr(mt5_module, "ORDER_TYPE_BUY", 0))
    expected_type = int(fallback_type)
    raw_type = getattr(deal, "type", None)
    deal_type = expected_type if raw_type in (None, "") else int(raw_type)
    return deal_type == expected_type


def _deal_not_before_active_open(deal: Any, active: LiveTrackedPosition, config: LiveSendExecutorConfig) -> bool:
    try:
        deal_time = _as_utc_timestamp(_deal_time_utc(deal, config))
        open_time = _as_utc_timestamp(_normalized_position_opened_time(active))
    except Exception:
        return False
    return deal_time >= open_time


def _close_deal_summary(mt5_module: Any, deal: Any, config: LiveSendExecutorConfig) -> LiveCloseDealSummary:
    timestamp_fields = _deal_timestamp_fields(deal, config)
    return LiveCloseDealSummary(
        ticket=int(getattr(deal, "ticket", 0) or 0),
        position_id=int(getattr(deal, "position_id", 0) or 0),
        volume=float(getattr(deal, "volume", 0.0) or 0.0),
        price=float(getattr(deal, "price", 0.0) or 0.0),
        profit=float(getattr(deal, "profit", 0.0) or 0.0),
        close_reason=_close_reason(mt5_module, deal),
        close_time_utc=timestamp_fields["normalized_utc"],
        comment=str(getattr(deal, "comment", "") or ""),
        timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        raw_mt5_time=timestamp_fields["raw_time"],
        raw_mt5_time_msc=timestamp_fields["raw_time_msc"],
        timestamp_provenance=timestamp_fields["provenance"],
    )


def _close_deal_sort_key(deal: LiveCloseDealSummary) -> tuple[int, int]:
    try:
        close_ns = int(_as_utc_timestamp(deal.close_time_utc).value)
    except Exception:
        close_ns = 0
    return close_ns, int(deal.ticket)


def _position_initial_volume(active: LiveTrackedPosition) -> float:
    return float(active.initial_volume if active.initial_volume not in (None, "") else active.volume)


def _position_remaining_volume(active: LiveTrackedPosition) -> float:
    if active.remaining_volume not in (None, ""):
        return float(active.remaining_volume)
    processed_volume = _close_deal_volume(active.processed_close_deals)
    return max(0.0, _position_initial_volume(active) - processed_volume)


def _broker_position_volume(position: Any) -> float:
    return float(getattr(position, "volume", 0.0) or 0.0)


def _close_deal_volume(deals: Sequence[LiveCloseDealSummary]) -> float:
    return sum(float(deal.volume or 0.0) for deal in deals)


def _volume_equal(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= CLOSE_VOLUME_TOLERANCE


def _merge_close_deal_summaries(*groups: Sequence[LiveCloseDealSummary]) -> tuple[LiveCloseDealSummary, ...]:
    by_ticket: dict[int, LiveCloseDealSummary] = {}
    for group in groups:
        for deal in group:
            by_ticket[int(deal.ticket)] = deal
    return tuple(sorted(by_ticket.values(), key=_close_deal_sort_key))


def _unprocessed_close_deals(
    active: LiveTrackedPosition,
    deals: Sequence[LiveCloseDealSummary],
) -> tuple[LiveCloseDealSummary, ...]:
    processed = {int(deal.ticket) for deal in active.processed_close_deals}
    return tuple(deal for deal in deals if int(deal.ticket) not in processed)


def _aggregate_close_r(active: LiveTrackedPosition, deals: Sequence[LiveCloseDealSummary]) -> float | None:
    initial_volume = _position_initial_volume(active)
    risk_price = abs(active.entry_price - active.stop_loss)
    if initial_volume <= 0 or risk_price <= 0:
        return None
    total = 0.0
    for deal in deals:
        deal_r = (float(deal.price) - active.entry_price) / risk_price
        if active.side == "short":
            deal_r *= -1
        total += deal_r * (float(deal.volume) / initial_volume)
    return total


def _weighted_close_price(deals: Sequence[LiveCloseDealSummary]) -> float:
    total_volume = _close_deal_volume(deals)
    if total_volume <= 0:
        return 0.0
    return sum(float(deal.price) * float(deal.volume) for deal in deals) / total_volume


def _aggregate_close_reason(deals: Sequence[LiveCloseDealSummary]) -> tuple[str, str]:
    reasons = [str(deal.close_reason or "manual") for deal in deals]
    unique = set(reasons)
    if unique == {"tp"}:
        return "tp", "all_close_deals_tp"
    if unique == {"sl"}:
        return "sl", "all_close_deals_sl"
    detail = "mixed_or_manual_close_reasons:" + ",".join(sorted(unique or {"manual"}))
    return "manual", detail


def _aggregate_close_event(active: LiveTrackedPosition, deals: Sequence[LiveCloseDealSummary]) -> LiveCloseEvent:
    ordered = tuple(sorted(deals, key=_close_deal_sort_key))
    latest = ordered[-1]
    reason, reason_detail = _aggregate_close_reason(ordered)
    profit = sum(float(deal.profit) for deal in ordered)
    tickets = tuple(int(deal.ticket) for deal in ordered)
    return LiveCloseEvent(
        ticket=latest.ticket,
        position_id=active.position_id,
        close_reason=reason,
        close_time_utc=latest.close_time_utc,
        close_price=_weighted_close_price(ordered),
        close_profit=profit,
        close_comment=latest.comment,
        timestamp_semantics_version=latest.timestamp_semantics_version,
        raw_mt5_time=latest.raw_mt5_time,
        raw_mt5_time_msc=latest.raw_mt5_time_msc,
        timestamp_provenance=latest.timestamp_provenance,
        close_volume=_close_deal_volume(ordered),
        initial_volume=_position_initial_volume(active),
        remaining_volume=0.0,
        aggregate_close_profit=profit,
        aggregate_r_result=_aggregate_close_r(active, ordered),
        close_deal_tickets=tickets,
        close_deal_count=len(ordered),
        close_reason_detail=reason_detail,
        close_deals=ordered,
    )


def _close_deal_ticket_hash(deals: Sequence[LiveCloseDealSummary]) -> str:
    payload = ",".join(str(ticket) for ticket in sorted(int(deal.ticket) for deal in deals))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _close_deals_payload(deals: Sequence[LiveCloseDealSummary]) -> list[dict[str, Any]]:
    return [deal.to_dict() for deal in sorted(deals, key=_close_deal_sort_key)]


def _active_with_initialized_close_ledger(active: LiveTrackedPosition, *, broker_volume: float | None = None) -> LiveTrackedPosition:
    initial_volume = _position_initial_volume(active)
    remaining_volume = _position_remaining_volume(active) if broker_volume is None else float(broker_volume)
    return replace(active, initial_volume=initial_volume, remaining_volume=remaining_volume)


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
    if _notification_event_already_recorded(state, event_key, event):
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
    _save_live_state(config, next_state)
    return next_state


def _with_event_diagnostics(
    event: NotificationEvent,
    diagnostics: dict[str, Any] | None,
    *,
    market: MT5MarketSnapshot | None = None,
    spread_gate: DynamicSpreadGate | None = None,
    execution: dict[str, Any] | None = None,
) -> NotificationEvent:
    if not diagnostics and market is None and spread_gate is None and not execution:
        return event
    return replace(
        event,
        fields=fields_with_diagnostics(
            event.fields,
            diagnostics,
            market=market,
            spread_gate=spread_gate,
            execution=execution,
        ),
    )


def _tracked_order_from_intent(
    intent: MT5OrderIntent,
    order_ticket: int,
    *,
    price_digits: int | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> LiveTrackedOrder:
    broker_backstop = intent.broker_backstop_expiration_time_utc or intent.expiration_time_utc
    signal_time = intent.signal_time_utc
    _, legacy_signal_key = canonical_and_legacy_signal_keys(intent.signal_key)
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
        diagnostics=diagnostics,
        timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        signal_key_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        legacy_signal_key=legacy_signal_key,
    )


def _order_signal_timing_fields(order: LiveTrackedOrder) -> dict[str, Any]:
    fields: dict[str, Any] = {"placed_time_utc": order.placed_time_utc}
    signal_closed = _signal_closed_time_utc(order.signal_time_utc, order.timeframe)
    if signal_closed is not None:
        closed_iso = signal_closed.isoformat()
        fields["signal_closed_time_utc"] = closed_iso
        fields["latest_closed_candle_time_utc"] = closed_iso
    lag_seconds = _placement_lag_seconds(order.placed_time_utc, signal_closed)
    if lag_seconds is not None:
        fields["placement_lag_seconds"] = lag_seconds
    return fields


def _signal_closed_time_utc(signal_time_utc: Any, timeframe: str) -> pd.Timestamp | None:
    if signal_time_utc in (None, ""):
        return None
    try:
        return _as_utc_timestamp(signal_time_utc) + timeframe_delta(str(timeframe).upper())
    except Exception:
        return None


def _placement_lag_seconds(placed_time_utc: Any, signal_closed_time_utc: pd.Timestamp | None) -> int | None:
    if signal_closed_time_utc is None or placed_time_utc in (None, ""):
        return None
    try:
        placed = _as_utc_timestamp(placed_time_utc)
    except Exception:
        return None
    return int(max(0, (placed - signal_closed_time_utc).total_seconds()))


def _signal_to_event_seconds(signal_key: str, timeframe: str, event_time_utc: Any) -> int | None:
    signal_closed = _signal_closed_time_utc(_signal_time_from_signal_key(signal_key), timeframe)
    if signal_closed is None:
        return None
    try:
        event_time = _as_utc_timestamp(event_time_utc)
    except Exception:
        return None
    return int(max(0, (event_time - signal_closed).total_seconds()))


def _seconds_between(start_utc: Any, end_utc: Any) -> int | None:
    try:
        start = _as_utc_timestamp(start_utc)
        end = _as_utc_timestamp(end_utc)
    except Exception:
        return None
    return int(max(0, (end - start).total_seconds()))


def _tracked_position_from_pending(pending: LiveTrackedOrder, position: Any, config: LiveSendExecutorConfig) -> LiveTrackedPosition:
    timestamp_fields = _position_timestamp_fields(position, config)
    volume = float(getattr(position, "volume", pending.volume) or pending.volume)
    return LiveTrackedPosition(
        signal_key=pending.signal_key,
        position_id=_position_id(position),
        order_ticket=pending.order_ticket,
        symbol=pending.symbol,
        timeframe=pending.timeframe,
        side=pending.side,
        volume=volume,
        entry_price=float(getattr(position, "price_open", pending.entry_price) or pending.entry_price),
        stop_loss=float(getattr(position, "sl", pending.stop_loss) or pending.stop_loss),
        take_profit=float(getattr(position, "tp", pending.take_profit) or pending.take_profit),
        target_risk_pct=pending.target_risk_pct,
        actual_risk_pct=pending.actual_risk_pct,
        opened_time_utc=timestamp_fields["normalized_utc"],
        magic=pending.magic,
        comment=pending.comment,
        setup_id=pending.setup_id,
        price_digits=pending.price_digits,
        diagnostics=pending.diagnostics,
        timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        raw_mt5_time=timestamp_fields["raw_time"],
        raw_mt5_time_msc=timestamp_fields["raw_time_msc"],
        timestamp_provenance=timestamp_fields["provenance"],
        signal_key_timestamp_semantics_version=pending.signal_key_timestamp_semantics_version,
        legacy_signal_key=(
            pending.signal_key
            if pending.signal_key_timestamp_semantics_version == LEGACY_HELSINKI_RELOCALIZED_V1
            else pending.legacy_signal_key
        ),
        initial_volume=volume,
        remaining_volume=volume,
    )


def _tracked_position_from_intent(
    intent: MT5OrderIntent,
    position: Any,
    config: LiveSendExecutorConfig,
    *,
    price_digits: int | None,
    diagnostics: dict[str, Any] | None = None,
) -> LiveTrackedPosition:
    position_id = _position_id(position)
    timestamp_fields = _position_timestamp_fields(position, config)
    _, legacy_signal_key = canonical_and_legacy_signal_keys(intent.signal_key)
    volume = float(getattr(position, "volume", intent.volume) or intent.volume)
    return LiveTrackedPosition(
        signal_key=intent.signal_key,
        position_id=position_id,
        order_ticket=int(getattr(position, "ticket", 0) or position_id),
        symbol=intent.symbol,
        timeframe=intent.timeframe,
        side=intent.side,
        volume=volume,
        entry_price=float(getattr(position, "price_open", intent.entry_price) or intent.entry_price),
        stop_loss=float(getattr(position, "sl", intent.stop_loss) or intent.stop_loss),
        take_profit=float(getattr(position, "tp", intent.take_profit) or intent.take_profit),
        target_risk_pct=intent.target_risk_pct,
        actual_risk_pct=intent.actual_risk_pct,
        opened_time_utc=timestamp_fields["normalized_utc"],
        magic=intent.magic,
        comment=intent.comment,
        setup_id=intent.setup_id,
        price_digits=price_digits,
        diagnostics=diagnostics,
        timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        raw_mt5_time=timestamp_fields["raw_time"],
        raw_mt5_time_msc=timestamp_fields["raw_time_msc"],
        timestamp_provenance=timestamp_fields["provenance"],
        signal_key_timestamp_semantics_version=MT5_EPOCH_UTC_V2,
        legacy_signal_key=legacy_signal_key,
        initial_volume=volume,
        remaining_volume=volume,
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
    base_comment = _live_order_comment(setup, config.order_comment_prefix)
    attempt_id = _recovery_attempt_id_from_fields(
        signal_key=signal_key,
        symbol=str(setup.symbol).upper(),
        side=setup.side,
        original_entry=float(recovery_check.original_entry),
        entry_price=rounded_fill,
        stop_loss=rounded_stop,
        take_profit=rounded_take_profit,
        magic=limits.strategy_magic,
        volume=float(volume_decision["volume"]),
        comment=base_comment,
        strategy_identity=_market_recovery_strategy_identity(base_comment),
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
        comment=_market_recovery_comment_with_marker(base_comment, attempt_id),
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
    """Build local continuity metadata when an acknowledged fill is not yet visible.

    This fallback is not broker truth. Later MT5 reconciliation remains
    authoritative for the position lifecycle.
    """

    ticket = outcome.order_ticket or outcome.deal_ticket
    if ticket is None:
        raise BrokerSnapshotUnavailable("MT5 market-recovery fill acknowledgment did not include an order or deal ticket.")
    position_type = getattr(mt5_module, "ORDER_TYPE_BUY", 0) if intent.side == "long" else getattr(mt5_module, "ORDER_TYPE_SELL", 1)
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
        time_msc=None,
        time=None,
        inferred_time_utc=pd.Timestamp.now(tz="UTC").isoformat(),
        timestamp_provenance="inferred_local_send_time",
    )


def _round_price_for_spec(value: float, spec: MT5SymbolExecutionSpec) -> float:
    return round(float(value), int(spec.digits))


def _round_volume_down(volume: float, step: float) -> float:
    units = math.floor(float(volume) / float(step) + 1e-12)
    return units * float(step)


def _live_order_comment(setup: TradeSetup, prefix: str = "LPFS") -> str:
    signal_index = "na" if setup.signal_index is None else str(setup.signal_index)
    safe_prefix = str(prefix or "LPFS").strip() or "LPFS"
    return f"{safe_prefix} {str(setup.timeframe).upper()} {str(setup.side)[0].upper()} {signal_index}"[:31]


def _recovery_attempt_id_from_fields(**fields: Any) -> str:
    payload = {key: fields[key] for key in sorted(fields)}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _market_recovery_comment_with_marker(base_comment: str, recovery_attempt_id: str) -> str:
    marker = f" R{recovery_attempt_id[:8]}"
    base = str(base_comment or "LPFS").strip() or "LPFS"
    if len(base) + len(marker) <= 31:
        return f"{base}{marker}"
    return f"{base[: 31 - len(marker)]}{marker}"


def _market_recovery_base_comment(comment: str) -> str:
    text = str(comment or "")
    marker_index = text.rfind(" R")
    if marker_index >= 0:
        suffix = text[marker_index + 2 :]
        if len(suffix) == 8 and all(char in "0123456789abcdef" for char in suffix.casefold()):
            return text[:marker_index]
    return text


def _market_recovery_strategy_identity(base_comment: str) -> str:
    text = str(base_comment or "").strip()
    return (text.split(" ", 1)[0] if text else "LPFS")


def _recovery_attempt_id(intent: MT5OrderIntent, recovery_check: MarketRecoveryCheck) -> str:
    base_comment = _market_recovery_base_comment(intent.comment)
    return _recovery_attempt_id_from_fields(
        signal_key=intent.signal_key,
        symbol=intent.symbol,
        side=intent.side,
        original_entry=float(recovery_check.original_entry),
        entry_price=float(intent.entry_price),
        stop_loss=float(intent.stop_loss),
        take_profit=float(intent.take_profit),
        magic=int(intent.magic),
        volume=float(intent.volume),
        comment=base_comment,
        strategy_identity=_market_recovery_strategy_identity(base_comment),
    )


def _recovery_attempt_from_intent(
    intent: MT5OrderIntent,
    recovery_check: MarketRecoveryCheck,
    recovery_attempt_id: str,
) -> LiveRecoveryAttempt:
    now = pd.Timestamp.now(tz="UTC").isoformat()
    return LiveRecoveryAttempt(
        recovery_attempt_id=recovery_attempt_id,
        signal_key=intent.signal_key,
        symbol=intent.symbol,
        timeframe=intent.timeframe,
        side=intent.side,
        original_entry=float(recovery_check.original_entry),
        fill_price=float(intent.entry_price),
        stop_loss=float(intent.stop_loss),
        take_profit=float(intent.take_profit),
        volume=float(intent.volume),
        target_risk_pct=float(intent.target_risk_pct),
        actual_risk_pct=float(intent.actual_risk_pct),
        magic=int(intent.magic),
        comment=intent.comment,
        setup_id=intent.setup_id,
        status="presend_recorded",
        created_time_utc=now,
        updated_time_utc=now,
        quote_path_evidence=recovery_check.quote_path_evidence,
        signal_time_utc=None if intent.signal_time_utc is None else intent.signal_time_utc.isoformat(),
        max_entry_wait_bars=int(intent.max_entry_wait_bars),
        strategy_expiry_mode=intent.strategy_expiry_mode,
        broker_backstop_expiration_time_utc=None
        if intent.broker_backstop_expiration_time_utc is None
        else intent.broker_backstop_expiration_time_utc.isoformat(),
    )


def _intent_from_recovery_attempt(attempt: LiveRecoveryAttempt) -> MT5OrderIntent:
    signal_time = _as_utc_timestamp(attempt.signal_time_utc) if attempt.signal_time_utc else None
    expiration = (
        _as_utc_timestamp(attempt.broker_backstop_expiration_time_utc)
        if attempt.broker_backstop_expiration_time_utc
        else pd.Timestamp.now(tz="UTC")
    )
    return MT5OrderIntent(
        signal_key=attempt.signal_key,
        symbol=attempt.symbol,
        timeframe=attempt.timeframe,
        side=attempt.side,
        order_type="BUY" if attempt.side == "long" else "SELL",  # type: ignore[arg-type]
        volume=float(attempt.volume),
        entry_price=float(attempt.fill_price),
        stop_loss=float(attempt.stop_loss),
        take_profit=float(attempt.take_profit),
        target_risk_pct=float(attempt.target_risk_pct),
        actual_risk_pct=float(attempt.actual_risk_pct),
        expiration_time_utc=expiration,
        magic=int(attempt.magic),
        comment=attempt.comment,
        setup_id=attempt.setup_id,
        signal_time_utc=signal_time,
        max_entry_wait_bars=int(attempt.max_entry_wait_bars),
        strategy_expiry_mode=attempt.strategy_expiry_mode,
        broker_backstop_expiration_time_utc=expiration,
    )


def _with_recovery_attempt(state: LiveExecutorState, attempt: LiveRecoveryAttempt) -> LiveExecutorState:
    attempts = [item for item in state.recovery_attempts if item.recovery_attempt_id != attempt.recovery_attempt_id]
    attempts.append(attempt)
    return replace(state, recovery_attempts=tuple(attempts))


def _unresolved_recovery_attempt_for_id(
    state: LiveExecutorState,
    recovery_attempt_id: str,
) -> LiveRecoveryAttempt | None:
    for attempt in state.recovery_attempts:
        if attempt.recovery_attempt_id != recovery_attempt_id:
            continue
        if attempt.status in {"presend_recorded", "reconcile_required"}:
            return attempt
    return None


def _mark_recovery_attempt(
    state: LiveExecutorState,
    attempt: LiveRecoveryAttempt,
    *,
    status: str,
    order_ticket: int | None = None,
    deal_ticket: int | None = None,
    position_id: int | None = None,
) -> LiveExecutorState:
    updated = replace(
        attempt,
        status=status,
        updated_time_utc=pd.Timestamp.now(tz="UTC").isoformat(),
        order_ticket=attempt.order_ticket if order_ticket is None else order_ticket,
        deal_ticket=attempt.deal_ticket if deal_ticket is None else deal_ticket,
        position_id=attempt.position_id if position_id is None else position_id,
    )
    return _with_recovery_attempt(state, updated)


def _market_recovery_lifecycle_fields(
    *,
    signal_key: str,
    setup: TradeSetup | None = None,
    intent: MT5OrderIntent | None = None,
    recovery_check: MarketRecoveryCheck | None = None,
    recovery_attempt_id: str | None = None,
    reason: str | None = None,
    broker_item: Any | None = None,
) -> dict[str, Any]:
    symbol = intent.symbol if intent is not None else (str(setup.symbol).upper() if setup is not None else None)
    timeframe = intent.timeframe if intent is not None else (str(setup.timeframe).upper() if setup is not None else None)
    side = intent.side if intent is not None else (str(setup.side) if setup is not None else None)
    fields: dict[str, Any] = {
        "signal_key": signal_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "original_entry": None if recovery_check is None else recovery_check.original_entry,
        "executable_fill_quote": None if recovery_check is None else recovery_check.fill_price,
        "stop_loss": intent.stop_loss if intent is not None else (None if recovery_check is None else recovery_check.stop_loss),
        "take_profit": intent.take_profit if intent is not None else (None if recovery_check is None else recovery_check.recalculated_take_profit),
        "recovery_decision_reason": reason,
        "quote_path_evidence_semantics": None
        if recovery_check is None or not recovery_check.quote_path_evidence
        else recovery_check.quote_path_evidence.get("quote_path_semantics"),
        "quote_path_evidence": None if recovery_check is None else recovery_check.quote_path_evidence,
        "recovery_attempt_id": recovery_attempt_id,
        "timestamp_semantics_version": MT5_EPOCH_UTC_V2,
        "timestamp_provenance": "system_utc",
    }
    if broker_item is not None:
        fields.update(_broker_recovery_ids(broker_item))
    return fields


def _broker_recovery_ids(item: Any) -> dict[str, Any]:
    return {
        "broker_order_ticket": _optional_int(getattr(item, "order", None)) or _optional_int(getattr(item, "ticket", None)),
        "broker_deal_ticket": _optional_int(getattr(item, "deal", None)),
        "broker_position_id": _optional_int(getattr(item, "position_id", None)) or _optional_int(getattr(item, "identifier", None)),
    }


def _append_market_recovery_lifecycle(config: LiveSendExecutorConfig, event: str, **fields: Any) -> None:
    append_audit_event(config.journal_path, event, **fields)


def _record_market_recovery_reconcile_required(
    config: LiveSendExecutorConfig,
    *,
    signal_key: str,
    setup: TradeSetup | None,
    intent: MT5OrderIntent | None,
    recovery_check: MarketRecoveryCheck | None,
    recovery_attempt_id: str | None,
    reason: str,
    error: str | None = None,
) -> None:
    _append_market_recovery_lifecycle(
        config,
        "market_recovery_reconcile_required",
        **_market_recovery_lifecycle_fields(
            signal_key=signal_key,
            setup=setup,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason=reason,
        ),
        error=error,
    )


def _record_market_recovery_presend(
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    *,
    attempt: LiveRecoveryAttempt,
    intent: MT5OrderIntent,
    recovery_check: MarketRecoveryCheck,
) -> LiveExecutorState:
    marked_state = _with_recovery_attempt(state, attempt)
    _save_live_state(config, marked_state)
    _append_market_recovery_lifecycle(
        config,
        "market_recovery_presend_recorded",
        **_market_recovery_lifecycle_fields(
            signal_key=intent.signal_key,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=attempt.recovery_attempt_id,
            reason="presend_marker_persisted",
        ),
        intent=intent.to_dict(),
    )
    return marked_state


def _matching_recovery_position_from_snapshot(
    mt5_module: Any,
    intent: MT5OrderIntent,
    snapshot: ValidatedBrokerSnapshot,
    spec: MT5SymbolExecutionSpec,
) -> Any | None:
    expected_type = getattr(mt5_module, "ORDER_TYPE_BUY", 0) if intent.side == "long" else getattr(mt5_module, "ORDER_TYPE_SELL", 1)
    for position in snapshot.positions:
        if str(getattr(position, "symbol", "") or "").upper() != intent.symbol:
            continue
        if int(getattr(position, "type", expected_type) or expected_type) != expected_type:
            continue
        if str(getattr(position, "comment", "") or "") != intent.comment:
            continue
        if not _any_volume_matches(position, intent.volume, spec):
            continue
        if not _price_attr_matches(position, ("price_open", "price"), intent.entry_price, spec):
            continue
        if not _price_attr_matches(position, ("sl",), intent.stop_loss, spec):
            continue
        if not _price_attr_matches(position, ("tp",), intent.take_profit, spec):
            continue
        return position
    return None


def _matching_recovery_entry_deal_from_snapshot(
    mt5_module: Any,
    intent: MT5OrderIntent,
    snapshot: ValidatedBrokerSnapshot,
    spec: MT5SymbolExecutionSpec,
) -> Any | None:
    matches = _matching_recovery_entry_deals_from_snapshot(mt5_module, intent, snapshot, spec)
    if len(matches) != 1:
        return None
    return matches[0]


def _matching_recovery_entry_deals_from_snapshot(
    mt5_module: Any,
    intent: MT5OrderIntent,
    snapshot: ValidatedBrokerSnapshot,
    spec: MT5SymbolExecutionSpec,
) -> tuple[Any, ...]:
    expected_type = getattr(mt5_module, "DEAL_TYPE_BUY", getattr(mt5_module, "ORDER_TYPE_BUY", 0)) if intent.side == "long" else getattr(mt5_module, "DEAL_TYPE_SELL", getattr(mt5_module, "ORDER_TYPE_SELL", 1))
    entry_in = int(getattr(mt5_module, "DEAL_ENTRY_IN", 0))
    entry_inout = int(getattr(mt5_module, "DEAL_ENTRY_INOUT", 2))
    matches: list[Any] = []
    for deal in snapshot.history_deals:
        if str(getattr(deal, "symbol", "") or "").upper() != intent.symbol:
            continue
        if int(getattr(deal, "magic", intent.magic) or intent.magic) != intent.magic:
            continue
        if int(getattr(deal, "type", expected_type) or expected_type) != expected_type:
            continue
        if int(getattr(deal, "entry", entry_in) or entry_in) not in {entry_in, entry_inout}:
            continue
        comment = str(getattr(deal, "comment", "") or "")
        if comment and comment != intent.comment:
            continue
        if not _any_volume_matches(deal, intent.volume, spec):
            continue
        if not _price_attr_matches(deal, ("price",), intent.entry_price, spec):
            continue
        matches.append(deal)
    return tuple(matches)


def _history_only_recovery_execution_exists(
    mt5_module: Any,
    intent: MT5OrderIntent,
    snapshot: ValidatedBrokerSnapshot,
    spec: MT5SymbolExecutionSpec,
) -> bool:
    return (
        _history_only_recovery_execution_reason(
            mt5_module,
            intent,
            snapshot,
            spec,
            reason="history_deal_without_matching_open_position",
            ambiguous_reason="ambiguous_history_deals_without_matching_open_position",
        )
        is not None
    )


def _history_only_recovery_execution_reason(
    mt5_module: Any,
    intent: MT5OrderIntent,
    snapshot: ValidatedBrokerSnapshot,
    spec: MT5SymbolExecutionSpec,
    *,
    reason: str,
    ambiguous_reason: str,
) -> str | None:
    matches = _matching_recovery_entry_deals_from_snapshot(mt5_module, intent, snapshot, spec)
    if len(matches) == 1:
        return reason
    if len(matches) > 1:
        return ambiguous_reason
    return None


def _adopt_market_recovery_from_broker(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    symbol_spec: MT5SymbolExecutionSpec,
    snapshot: ValidatedBrokerSnapshot,
    recovery_check: MarketRecoveryCheck,
    recovery_attempt_id: str,
    notifier: TelegramNotifier | None,
    diagnostics: dict[str, Any] | None,
) -> LiveSetupResult | None:
    position = _matching_recovery_position_from_snapshot(mt5_module, intent, snapshot, symbol_spec)
    if position is None:
        return None
    deal = _matching_recovery_entry_deal_from_snapshot(mt5_module, intent, snapshot, symbol_spec)
    tracked_position = _tracked_position_from_intent(
        intent,
        position,
        config,
        price_digits=symbol_spec.digits,
        diagnostics=diagnostics,
    )
    base_state = _with_processed_key(state, intent.signal_key)
    next_state = replace(base_state, active_positions=(*base_state.active_positions, tracked_position))
    next_state = _mark_recovery_attempt(
        next_state,
        _recovery_attempt_from_intent(intent, recovery_check, recovery_attempt_id),
        status="adopted",
        order_ticket=tracked_position.order_ticket,
        deal_ticket=None if deal is None else _optional_int(getattr(deal, "ticket", None)),
        position_id=tracked_position.position_id,
    )
    _save_live_state(config, next_state)
    event = _market_recovery_adopted_event(tracked_position, recovery_check, broker_position=position, broker_deal=deal)
    next_state = _record_event_once(
        config,
        next_state,
        notifier,
        f"market_recovery_adopted:{recovery_attempt_id}:{tracked_position.position_id}",
        event,
        store_thread_key=f"order:{tracked_position.order_ticket}",
    )
    _append_market_recovery_lifecycle(
        config,
        "market_recovery_adopted",
        **_market_recovery_lifecycle_fields(
            signal_key=intent.signal_key,
            intent=intent,
            recovery_check=recovery_check,
            recovery_attempt_id=recovery_attempt_id,
            reason="matched_existing_broker_position",
            broker_item=position,
        ),
        broker_deal=None if deal is None else _broker_item_dict(deal),
    )
    return LiveSetupResult(
        state=next_state,
        signal_key=intent.signal_key,
        status="market_recovery_adopted",
        order_send=_adopted_outcome(mt5_module, intent, tracked_position.order_ticket, "existing market recovery position"),
    )


def _adopt_existing_broker_item(
    mt5_module: Any,
    intent: MT5OrderIntent,
    *,
    config: LiveSendExecutorConfig,
    state: LiveExecutorState,
    symbol_spec: MT5SymbolExecutionSpec,
    notifier: TelegramNotifier | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> LiveSetupResult | None:
    order = _matching_broker_order_for_intent(mt5_module, intent, config, symbol_spec)
    if order is not None:
        ticket = int(getattr(order, "ticket", 0) or 0)
        if ticket <= 0:
            return None
        tracked = _tracked_order_from_intent(intent, ticket, price_digits=symbol_spec.digits, diagnostics=diagnostics)
        next_state = replace(state, pending_orders=(*state.pending_orders, tracked))
        _save_live_state(config, next_state)
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
    tracked_position = _tracked_position_from_intent(
        intent,
        position,
        config,
        price_digits=symbol_spec.digits,
        diagnostics=diagnostics,
    )
    next_state = replace(state, active_positions=(*state.active_positions, tracked_position))
    _save_live_state(config, next_state)
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
    if intent.order_type in {"BUY", "SELL"}:
        request = build_market_order_request(mt5_module, intent, deviation_points=0)
    else:
        request = build_order_check_request(mt5_module, intent)
    return LiveOrderSendOutcome(
        sent=True,
        request=request,
        retcode=None,
        comment=f"adopted {source}; no order_send call",
        order_ticket=ticket,
    )


def _market_recovery_adopted_event(
    active: LiveTrackedPosition,
    recovery_check: MarketRecoveryCheck,
    *,
    broker_position: Any,
    broker_deal: Any | None,
) -> NotificationEvent:
    opened_utc = _normalized_position_opened_time(active)
    fields = fields_with_diagnostics(
        {
            "adoption_source": "market recovery broker reconciliation",
            "position_id": active.position_id,
            "order_ticket": active.order_ticket,
            "deal_ticket": None if broker_deal is None else _optional_int(getattr(broker_deal, "ticket", None)),
            "order_type": "BUY" if active.side == "long" else "SELL",
            "original_entry": recovery_check.original_entry,
            "fill_price": active.entry_price,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "volume": active.volume,
            "actual_risk_pct": active.actual_risk_pct,
            "target_risk_pct": active.target_risk_pct,
            "quote_path_evidence": recovery_check.quote_path_evidence,
            "opened_utc": opened_utc,
            "opened_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "opened_source_timestamp_semantics_version": active.timestamp_semantics_version,
            "opened_timestamp_provenance": active.timestamp_provenance,
            "opened_raw_mt5_time": active.raw_mt5_time,
            "opened_raw_mt5_time_msc": active.raw_mt5_time_msc,
            "price_digits": active.price_digits,
            "broker_position": _broker_item_dict(broker_position),
            "broker_deal": None if broker_deal is None else _broker_item_dict(broker_deal),
        },
        active.diagnostics,
        execution={
            "stage": "market_recovery_adopted",
            "execution_path": "market_recovery",
        },
    )
    return NotificationEvent(
        kind="market_recovery_adopted",
        mode="LIVE",
        title="Live market recovery position adopted",
        severity="info",
        symbol=active.symbol,
        timeframe=active.timeframe,
        side=active.side,
        status="open",
        signal_key=active.signal_key,
        fields=fields,
        message="Existing broker market-recovery execution matched the durable recovery attempt marker; no duplicate send was placed.",
    )


def _order_sent_event(order: LiveTrackedOrder, outcome: LiveOrderSendOutcome, spread: DynamicSpreadGate) -> NotificationEvent:
    fields = fields_with_diagnostics(
        {
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
            **_order_signal_timing_fields(order),
            "max_entry_wait_bars": order.max_entry_wait_bars,
            "strategy_expiry_mode": order.strategy_expiry_mode,
            "broker_backstop_expiration_utc": order.broker_backstop_expiration_time_utc,
            "spread_risk_pct": spread.spread_risk_fraction * 100,
            "price_digits": order.price_digits,
            "retcode": outcome.retcode,
            "comment": outcome.comment,
        },
        order.diagnostics,
        spread_gate=spread,
        execution={
            "stage": "order_sent",
            "execution_path": "pending_limit",
            "order_send_retcode": outcome.retcode,
            "order_send_comment": outcome.comment,
        },
    )
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
        fields=fields,
        message="closed-candle LP + Force Strike setup, 50% pullback entry, FS structure stop, 1R target.",
    )


def _market_recovery_sent_event(
    active: LiveTrackedPosition,
    outcome: LiveOrderSendOutcome,
    recovery_check: MarketRecoveryCheck,
    *,
    recovery_attempt_id: str | None = None,
) -> NotificationEvent:
    opened_utc = _normalized_position_opened_time(active)
    fields = fields_with_diagnostics(
        {
            "recovery_attempt_id": recovery_attempt_id,
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
            "quote_path_evidence": recovery_check.quote_path_evidence,
            "opened_utc": opened_utc,
            "opened_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "opened_source_timestamp_semantics_version": active.timestamp_semantics_version,
            "opened_timestamp_provenance": active.timestamp_provenance,
            "opened_raw_mt5_time": active.raw_mt5_time,
            "opened_raw_mt5_time_msc": active.raw_mt5_time_msc,
            "price_digits": active.price_digits,
            "retcode": outcome.retcode,
            "comment": outcome.comment,
        },
        active.diagnostics,
        execution={
            "stage": "market_recovery_sent",
            "execution_path": "market_recovery",
            "order_send_retcode": outcome.retcode,
            "order_send_comment": outcome.comment,
        },
    )
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
        fields=fields,
        message="Missed pending touch recovered with better-than-entry executable price, original structure stop, and recalculated 1R target.",
    )


def _order_adopted_event(item: LiveTrackedOrder | LiveTrackedPosition, *, source: str, broker_item: Any) -> NotificationEvent:
    fields = fields_with_diagnostics(
        {
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
        item.diagnostics,
        execution={"stage": "order_adopted", "execution_path": "adopted_existing_broker_item"},
    )
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
        fields=fields,
        message=f"Existing MT5 {source} matched this LPFS setup; no new order sent.",
    )


def _position_opened_event(active: LiveTrackedPosition, position: Any) -> NotificationEvent:
    opened_utc = _normalized_position_opened_time(active)
    fields = fields_with_diagnostics(
        {
            "position_id": active.position_id,
            "order_ticket": active.order_ticket,
            "fill_price": active.entry_price,
            "volume": active.volume,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "actual_risk_pct": active.actual_risk_pct,
            "target_risk_pct": active.target_risk_pct,
            "opened_utc": opened_utc,
            "opened_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "opened_source_timestamp_semantics_version": active.timestamp_semantics_version,
            "opened_timestamp_provenance": active.timestamp_provenance,
            "opened_raw_mt5_time": active.raw_mt5_time,
            "opened_raw_mt5_time_msc": active.raw_mt5_time_msc,
            "price_digits": active.price_digits,
            "broker_comment": str(getattr(position, "comment", "") or ""),
        },
        active.diagnostics,
        execution={
            "stage": "position_opened",
            "execution_path": "pending_limit",
            "signal_to_fill_seconds": _signal_to_event_seconds(active.signal_key, active.timeframe, opened_utc),
        },
    )
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
        fields=fields,
    )


def _close_event(active: LiveTrackedPosition, close: LiveCloseEvent) -> NotificationEvent:
    opened_utc = _normalized_position_opened_time(active)
    closed_utc = normalize_recorded_timestamp(close.close_time_utc, close.timestamp_semantics_version).isoformat()
    risk_price = abs(active.entry_price - active.stop_loss)
    if close.aggregate_r_result is not None:
        r_result = close.aggregate_r_result
    else:
        r_result = 0.0 if risk_price <= 0 else (close.close_price - active.entry_price) / risk_price
        if active.side == "short":
            r_result *= -1
    if close.close_reason == "tp":
        kind = "take_profit_hit"
    elif close.close_reason == "sl":
        kind = "stop_loss_hit"
    else:
        kind = "position_closed"
    prior_execution = (active.diagnostics or {}).get("execution", {}) if isinstance(active.diagnostics, dict) else {}
    execution_path = "market_recovery" if prior_execution.get("execution_path") == "market_recovery" else "pending_limit"
    close_diagnostics = enrich_diagnostics(
        active.diagnostics,
        execution={
            "stage": kind,
            "execution_path": execution_path,
            "fill_to_close_seconds": _seconds_between(opened_utc, closed_utc),
            "close_reason": close.close_reason,
            "close_reason_detail": close.close_reason_detail,
            "close_deal_count": close.close_deal_count,
        },
    )
    initial_volume = close.initial_volume if close.initial_volume is not None else _position_initial_volume(active)
    close_volume = close.close_volume if close.close_volume is not None else _close_deal_volume(close.close_deals)
    remaining_volume = close.remaining_volume if close.remaining_volume is not None else 0.0
    close_profit = close.aggregate_close_profit if close.aggregate_close_profit is not None else close.close_profit
    fields = fields_with_diagnostics(
        {
            "position_id": active.position_id,
            "deal_ticket": close.ticket,
            "close_deal_tickets": list(close.close_deal_tickets or (close.ticket,)),
            "close_deal_count": close.close_deal_count,
            "entry": active.entry_price,
            "stop_loss": active.stop_loss,
            "take_profit": active.take_profit,
            "volume": initial_volume,
            "initial_volume": initial_volume,
            "closed_volume": close_volume,
            "remaining_volume": remaining_volume,
            "close_price": close.close_price,
            "close_profit": close_profit,
            "aggregate_close_profit": close_profit,
            "r_result": r_result,
            "aggregate_r_result": r_result,
            "opened_utc": opened_utc,
            "opened_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "opened_source_timestamp_semantics_version": active.timestamp_semantics_version,
            "opened_timestamp_provenance": active.timestamp_provenance,
            "opened_raw_mt5_time": active.raw_mt5_time,
            "opened_raw_mt5_time_msc": active.raw_mt5_time_msc,
            "closed_utc": closed_utc,
            "closed_timestamp_semantics_version": MT5_EPOCH_UTC_V2,
            "closed_source_timestamp_semantics_version": close.timestamp_semantics_version,
            "closed_timestamp_provenance": close.timestamp_provenance,
            "closed_raw_mt5_time": close.raw_mt5_time,
            "closed_raw_mt5_time_msc": close.raw_mt5_time_msc,
            "price_digits": active.price_digits,
            "broker_comment": close.close_comment,
            "close_reason": close.close_reason,
            "close_reason_detail": close.close_reason_detail,
            "close_deals": _close_deals_payload(close.close_deals),
        },
        close_diagnostics,
    )
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
        fields=fields,
    )


def _normalized_position_opened_time(active: LiveTrackedPosition) -> str:
    return normalize_recorded_timestamp(active.opened_time_utc, active.timestamp_semantics_version).isoformat()


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
    fields = fields_with_diagnostics(
        fields,
        order.diagnostics,
        execution={"stage": "pending_expired" if expired else "pending_cancelled", "execution_path": "pending_limit"},
    )
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
    fields = fields_with_diagnostics(
        {
            "order_ticket": order.order_ticket,
            "price_digits": order.price_digits,
            "broker_comment": "" if history_order is None else str(getattr(history_order, "comment", "") or ""),
        },
        order.diagnostics,
        execution={"stage": "pending_missing", "execution_path": "pending_limit"},
    )
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
        fields=fields,
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


def _retryable_broker_block_event(
    status: str,
    signal_key: str,
    retcode: Any,
    comment: str,
    fields: dict[str, Any] | None = None,
) -> NotificationEvent:
    messages = {
        "autotrading_disabled": "MT5 AutoTrading is disabled by the client terminal.",
        "market_closed": "Broker market is closed for this symbol.",
    }
    payload = {"retcode": retcode, "comment": comment}
    if fields:
        payload.update(fields)
    return _rejection_event(status, messages.get(status, "Broker temporarily blocked order placement."), signal_key, payload)


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
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
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
    linked_position_id = _position_id_from_order_history(mt5_module, order, config, snapshot=snapshot)
    if linked_position_id is None:
        return None
    for position in candidates:
        if _position_id(position) == linked_position_id:
            return position
    return None


def _position_id_from_order_history(
    mt5_module: Any,
    order: LiveTrackedOrder,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> int | None:
    history_order = _history_order_for_ticket(mt5_module, order, config, snapshot=snapshot)
    if history_order is not None:
        for attr in ("position_id", "position_by_id"):
            value = _optional_int(getattr(history_order, attr, None))
            if value is not None:
                return value
    for deal in _history_deals_for_order_ticket(mt5_module, order.order_ticket, config, snapshot=snapshot):
        value = _optional_int(getattr(deal, "position_id", None))
        if value is not None:
            return value
    return None


def _history_deals_for_order_ticket(
    mt5_module: Any,
    order_ticket: int,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> tuple[Any, ...]:
    if snapshot is not None:
        return tuple(deal for deal in snapshot.history_deals if int(getattr(deal, "order", 0) or 0) == int(order_ticket))
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    result = mt5_module.history_deals_get(start.to_pydatetime(), end.to_pydatetime())
    if result is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_deals_get"))
    deals = list(result)
    return tuple(deal for deal in deals if int(getattr(deal, "order", 0) or 0) == int(order_ticket))


def _history_deals_for_position(
    mt5_module: Any,
    position_id: int,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> tuple[Any, ...]:
    try:
        direct = mt5_module.history_deals_get(position=position_id)
    except TypeError:
        direct = ...
    if direct is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_deals_get", symbol=f"position={position_id}"))
    if direct is not ...:
        direct_deals = tuple(direct)
        if direct_deals:
            return direct_deals
    if snapshot is not None:
        return tuple(snapshot.history_deals)
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=config.history_lookback_days)
    fallback = mt5_module.history_deals_get(start.to_pydatetime(), end.to_pydatetime())
    if fallback is None:
        raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_deals_get"))
    return tuple(fallback)


def _history_order_for_ticket(
    mt5_module: Any,
    order: LiveTrackedOrder,
    config: LiveSendExecutorConfig,
    *,
    snapshot: ValidatedBrokerSnapshot | None = None,
) -> Any | None:
    if snapshot is not None:
        result = snapshot.history_orders
    else:
        end = pd.Timestamp.now(tz="UTC")
        start = end - pd.Timedelta(days=config.history_lookback_days)
        raw_result = mt5_module.history_orders_get(start.to_pydatetime(), end.to_pydatetime())
        if raw_result is None:
            raise BrokerSnapshotUnavailable(_broker_read_error(mt5_module, "history_orders_get"))
        result = tuple(raw_result)
    for item in result:
        if int(getattr(item, "ticket", 0) or 0) != order.order_ticket:
            continue
        if int(getattr(item, "magic", 0) or 0) != order.magic:
            continue
        if str(getattr(item, "symbol", "") or "").upper() != order.symbol:
            continue
        return item
    return None


def _broker_read_error(mt5_module: Any, operation: str, *, symbol: str = "") -> str:
    try:
        last_error = mt5_module.last_error()
    except Exception:
        last_error = "unavailable"
    suffix = f" symbol={symbol}" if symbol else ""
    return f"MT5 {operation} returned None{suffix}; last_error={last_error!r}."


def _broker_item_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "_asdict"):
        return dict(item._asdict())
    if hasattr(item, "__dict__"):
        return dict(vars(item))
    return {"repr": repr(item)}


def _stable_broker_items(items: Sequence[Any]) -> list[dict[str, Any]]:
    rows = [_broker_item_dict(item) for item in items]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))


def _stable_payload_hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    return _deal_timestamp_fields(deal, config)["normalized_utc"]


def _position_id(position: Any) -> int:
    return int(getattr(position, "identifier", None) or getattr(position, "ticket", 0) or 0)


def _position_time_utc(position: Any, config: LiveSendExecutorConfig) -> str:
    return _position_timestamp_fields(position, config)["normalized_utc"]


def _deal_timestamp_fields(deal: Any, config: LiveSendExecutorConfig) -> dict[str, Any]:
    return _broker_timestamp_fields(deal, config, label="deal")


def _position_timestamp_fields(position: Any, config: LiveSendExecutorConfig) -> dict[str, Any]:
    return _broker_timestamp_fields(position, config, label="position")


def _broker_timestamp_fields(item: Any, config: LiveSendExecutorConfig, *, label: str) -> dict[str, Any]:
    raw_msc = _optional_int(getattr(item, "time_msc", None))
    raw_time = _optional_int(getattr(item, "time", None))
    timestamp = broker_time_epoch_to_utc(raw_msc, config.broker_timezone, unit="ms") if raw_msc else None
    provenance = "mt5_time_msc"
    if timestamp is None and raw_time:
        timestamp = broker_time_epoch_to_utc(raw_time, config.broker_timezone, unit="s")
        provenance = "mt5_time"
    if timestamp is None and getattr(item, "timestamp_provenance", "") == "inferred_local_send_time":
        timestamp = _as_utc_timestamp(getattr(item, "inferred_time_utc", None))
        provenance = "inferred_local_send_time"
    if timestamp is None:
        raise BrokerSnapshotUnavailable(f"MT5 {label} timestamp unavailable.")
    return {
        "raw_time": raw_time,
        "raw_time_msc": raw_msc,
        "normalized_utc": timestamp.isoformat(),
        "timestamp_semantics_version": MT5_EPOCH_UTC_V2,
        "provenance": provenance,
    }


def _as_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _close_is_old(state: LiveExecutorState, close: LiveCloseEvent) -> bool:
    if state.last_seen_close_time_utc is None:
        return False
    cursor_semantics = state.last_seen_close_timestamp_semantics_version or LEGACY_HELSINKI_RELOCALIZED_V1
    last_time = normalize_recorded_timestamp(state.last_seen_close_time_utc, cursor_semantics)
    close_time = normalize_recorded_timestamp(close.close_time_utc, close.timestamp_semantics_version)
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
        existing_signal_keys=_expanded_existing_signal_keys(state),
    )


def _state_signal_records(state: LiveExecutorState) -> tuple[tuple[str, str | None], ...]:
    records: list[tuple[str, str | None]] = [
        (key, state.processed_signal_key_semantics.get(key))
        for key in state.processed_signal_keys
    ]
    records.extend((item.signal_key, item.signal_key_timestamp_semantics_version) for item in state.pending_orders)
    records.extend((item.signal_key, item.signal_key_timestamp_semantics_version) for item in state.active_positions)
    return tuple(records)


def _state_has_equivalent_signal_key(
    state: LiveExecutorState,
    canonical_key: str,
    *,
    config: LiveSendExecutorConfig,
) -> bool:
    parse_signal_key(canonical_key)
    return any(
        signal_key_matches_canonical(
            recorded_key,
            canonical_key,
            recorded_semantics=semantics,
            broker_timezone=DEFAULT_LEGACY_BROKER_TIMEZONE,
        )
        for recorded_key, semantics in _state_signal_records(state)
    )


def _expanded_existing_signal_keys(state: LiveExecutorState) -> tuple[str, ...]:
    keys: set[str] = set()
    for raw_key, semantics in _state_signal_records(state):
        parsed = parse_signal_key(raw_key)
        if semantics == LEGACY_HELSINKI_RELOCALIZED_V1:
            canonical_time = normalize_recorded_timestamp(parsed.signal_time_utc, semantics)
            keys.add(parsed.with_timestamp(canonical_time).to_key())
            continue
        if semantics == MT5_EPOCH_UTC_V2:
            keys.add(parsed.to_key())
            continue
        canonical, legacy = canonical_and_legacy_signal_keys(parsed.to_key())
        keys.update((canonical, legacy))
    return tuple(sorted(keys))


def _notification_event_already_recorded(
    state: LiveExecutorState,
    event_key: str,
    event: NotificationEvent,
) -> bool:
    if event_key in state.notified_event_keys:
        return True
    signal_key = str(event.signal_key or "")
    if not signal_key or signal_key not in event_key:
        return False
    try:
        canonical, legacy = canonical_and_legacy_signal_keys(signal_key)
    except TimestampSemanticsError:
        return False
    variants = {
        event_key.replace(signal_key, canonical, 1),
        event_key.replace(signal_key, legacy, 1),
    }
    return any(candidate in state.notified_event_keys for candidate in variants)


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


def _retryable_order_send_block_status(outcome: LiveOrderSendOutcome) -> str | None:
    """Return operator/environment send block status values that can clear later."""

    try:
        retcode = None if outcome.retcode is None else int(outcome.retcode)
    except (TypeError, ValueError):
        retcode = None
    if retcode == TRADE_RETCODE_CLIENT_DISABLES_AT:
        return "autotrading_disabled"
    if _is_market_closed_block(outcome.retcode, outcome.comment):
        return "market_closed"
    return None


def _is_market_closed_block(retcode: Any, comment: str) -> bool:
    try:
        if retcode is not None and int(retcode) == TRADE_RETCODE_MARKET_CLOSED:
            return True
    except (TypeError, ValueError):
        pass
    return "market closed" in str(comment or "").casefold()


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
    semantics = dict(state.processed_signal_key_semantics)
    semantics[signal_key] = MT5_EPOCH_UTC_V2
    return replace(
        state,
        processed_signal_keys=_append_unique(state.processed_signal_keys, signal_key),
        processed_signal_key_semantics=semantics,
    )


def _without_processed_key(state: LiveExecutorState, signal_key: str) -> LiveExecutorState:
    """Re-arm a signal after an explicitly retryable WAITING outcome."""

    semantics = dict(state.processed_signal_key_semantics)
    semantics.pop(signal_key, None)
    return replace(
        state,
        processed_signal_keys=tuple(key for key in state.processed_signal_keys if key != signal_key),
        processed_signal_key_semantics=semantics,
    )


def _with_checked_key(state: LiveExecutorState, signal_key: str) -> LiveExecutorState:
    semantics = dict(state.order_checked_signal_key_semantics)
    semantics[signal_key] = MT5_EPOCH_UTC_V2
    return replace(
        state,
        order_checked_signal_keys=_append_unique(state.order_checked_signal_keys, signal_key),
        order_checked_signal_key_semantics=semantics,
    )


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


def _optional_risk_buckets(value: Any) -> dict[str, float] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise LocalConfigError("risk_buckets_pct must be an object keyed by timeframe.")
    return {str(timeframe).upper(): float(risk_pct) for timeframe, risk_pct in value.items()}


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
        max_risk_pct_per_trade=config.max_risk_pct_per_trade,
        risk_buckets_pct=config.risk_buckets_pct,
        risk_bucket_scale=config.risk_bucket_scale,
        max_open_risk_pct=config.max_open_risk_pct,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        strategy_magic=config.strategy_magic,
        order_comment_prefix=config.order_comment_prefix,
        pivot_strength=config.pivot_strength,
        max_bars_from_lp_break=config.max_bars_from_lp_break,
        require_lp_pivot_before_fs_mother=config.require_lp_pivot_before_fs_mother,
        max_entry_wait_bars=config.max_entry_wait_bars,
    )
