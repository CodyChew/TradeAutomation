"""Dry-run MT5 executor support for LP + Force Strike order checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

from backtest_engine_lab import TradeSetup

from .execution_contract import (
    ExistingStrategyExposure,
    ExecutionSafetyLimits,
    MT5AccountSnapshot,
    MT5MarketSnapshot,
    MT5OrderIntent,
    MT5SymbolExecutionSpec,
    V15_EFFICIENT_RISK_BUCKET_PCT,
    build_mt5_order_intent,
    signal_key_for_setup,
)
from .experiment import SkippedTrade, TradeModelCandidate, add_atr
from .notifications import (
    NotificationDelivery,
    NotificationEvent,
    TelegramConfig,
    TelegramNotifier,
    format_notification_message,
    notification_from_execution_decision,
)
from .signals import LPForceStrikeSignal, detect_lp_force_strike_signals


TIMEFRAME_TO_MT5_ATTR: dict[str, str] = {
    "H4": "TIMEFRAME_H4",
    "H8": "TIMEFRAME_H8",
    "H12": "TIMEFRAME_H12",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
}
CANONICAL_CANDLE_COLUMNS = [
    "time_utc",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "real_volume",
    "spread_points",
]
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "broker",
        "chat_id",
        "login",
        "expected_login",
        "expected_server",
        "mt5_login",
        "mt5_expected_login",
        "mt5_expected_server",
        "mt5_password",
        "mt5_server",
        "password",
        "server",
        "telegram_bot_token",
        "telegram_chat_id",
        "token",
    }
)


class LocalConfigError(ValueError):
    """Raised when ignored local dry-run config is missing required values."""


@dataclass(frozen=True)
class DryRunLocalConfig:
    """Sensitive local-only settings for the MT5 dry-run adapter."""

    use_existing_terminal_session: bool = True
    expected_login: str | None = None
    expected_server: str | None = None
    mt5_login: str | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_path: str | None = None
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_dry_run: bool = True

    def safe_dict(self) -> dict[str, Any]:
        return {
            "use_existing_terminal_session": self.use_existing_terminal_session,
            "expected_login_set": bool(self.expected_login),
            "expected_server_set": bool(self.expected_server),
            "mt5_login_set": bool(self.mt5_login),
            "mt5_password_set": bool(self.mt5_password),
            "mt5_server_set": bool(self.mt5_server),
            "mt5_path_set": bool(self.mt5_path),
            "telegram_enabled": self.telegram_enabled,
            "telegram_bot_token_set": bool(self.telegram_bot_token),
            "telegram_chat_id_set": bool(self.telegram_chat_id),
            "telegram_dry_run": self.telegram_dry_run,
        }


@dataclass(frozen=True)
class DryRunExecutorConfig:
    """Non-secret dry-run executor settings."""

    symbols: tuple[str, ...] = ("EURUSD",)
    timeframes: tuple[str, ...] = ("H4", "H8", "H12", "D1", "W1")
    broker_timezone: str = "UTC"
    history_bars: int = 300
    journal_path: str = "data/live/lpfs_dry_run_journal.jsonl"
    state_path: str = "data/live/lpfs_dry_run_state.json"
    max_spread_points: float | None = None
    max_lots_per_order: float | None = None
    max_risk_pct_per_trade: float = 0.75
    risk_buckets_pct: dict[str, float] | None = None
    risk_bucket_scale: float = 1.0
    max_open_risk_pct: float = 6.0
    max_same_symbol_stack: int = 4
    max_concurrent_strategy_trades: int = 17
    strategy_magic: int = 131500
    pivot_strength: int = 3
    max_bars_from_lp_break: int = 6
    require_lp_pivot_before_fs_mother: bool = True
    max_entry_wait_bars: int = 6


@dataclass(frozen=True)
class DryRunSettings:
    """Resolved local plus non-secret dry-run settings."""

    local: DryRunLocalConfig
    executor: DryRunExecutorConfig

    def safe_dict(self) -> dict[str, Any]:
        return {"local": self.local.safe_dict(), "executor": asdict(self.executor)}


@dataclass(frozen=True)
class DryRunExecutorState:
    """Restart-safe local state used for idempotent dry-run processing."""

    processed_signal_keys: tuple[str, ...] = ()
    order_checked_signal_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderCheckOutcome:
    """Result of calling MT5 order_check for a validated intent."""

    passed: bool
    request: dict[str, Any]
    retcode: int | None
    comment: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DryRunSetupResult:
    """Result of one setup through the dry-run order-check path."""

    state: DryRunExecutorState
    signal_key: str
    status: str
    order_check: OrderCheckOutcome | None = None


@dataclass(frozen=True)
class DryRunCycleResult:
    """Summary of one finite dry-run polling cycle."""

    state: DryRunExecutorState
    frames_processed: int
    setups_checked: int
    setups_rejected: int


SetupProvider = Callable[[pd.DataFrame, str, str, DryRunExecutorConfig], Sequence[TradeSetup | SkippedTrade]]


def load_dry_run_settings(
    path: str | Path = "config.local.json",
    *,
    env: dict[str, str] | None = None,
) -> DryRunSettings:
    """Load ignored local dry-run settings, using environment values as fallback."""

    config_path = Path(path)
    payload: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8-sig") as handle:
            payload = dict(json.load(handle))
    base_dir = config_path.parent if config_path.parent != Path("") else Path(".")
    source_env = os.environ if env is None else env

    mt5_payload = dict(payload.get("mt5", {}) or {})
    telegram_payload = dict(payload.get("telegram", {}) or {})
    dry_run_payload = dict(payload.get("dry_run", {}) or {})

    local = DryRunLocalConfig(
        use_existing_terminal_session=_optional_bool(
            _first_value(
                mt5_payload.get("use_existing_terminal_session"),
                source_env.get("MT5_USE_EXISTING_TERMINAL_SESSION"),
            ),
            default=True,
        ),
        expected_login=_first_value(mt5_payload.get("expected_login"), source_env.get("MT5_EXPECTED_LOGIN")),
        expected_server=_first_value(mt5_payload.get("expected_server"), source_env.get("MT5_EXPECTED_SERVER")),
        mt5_login=_first_value(mt5_payload.get("login"), source_env.get("MT5_LOGIN")),
        mt5_password=_first_value(mt5_payload.get("password"), source_env.get("MT5_PASSWORD")),
        mt5_server=_first_value(mt5_payload.get("server"), source_env.get("MT5_SERVER")),
        mt5_path=_first_value(mt5_payload.get("path"), source_env.get("MT5_PATH")),
        telegram_enabled=bool(telegram_payload.get("enabled", False)),
        telegram_bot_token=_first_value(telegram_payload.get("bot_token"), source_env.get("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=_first_value(telegram_payload.get("chat_id"), source_env.get("TELEGRAM_CHAT_ID")),
        telegram_dry_run=bool(telegram_payload.get("dry_run", True)),
    )
    executor = DryRunExecutorConfig(
        symbols=_tuple_of_strings(dry_run_payload.get("symbols"), ("EURUSD",)),
        timeframes=_tuple_of_strings(dry_run_payload.get("timeframes"), ("H4", "H8", "H12", "D1", "W1")),
        broker_timezone=str(dry_run_payload.get("broker_timezone", "UTC")),
        history_bars=int(dry_run_payload.get("history_bars", 300)),
        journal_path=str(_resolve_local_path(base_dir, dry_run_payload.get("journal_path", "data/live/lpfs_dry_run_journal.jsonl"))),
        state_path=str(_resolve_local_path(base_dir, dry_run_payload.get("state_path", "data/live/lpfs_dry_run_state.json"))),
        max_spread_points=_optional_float(dry_run_payload.get("max_spread_points")),
        max_lots_per_order=_optional_float(dry_run_payload.get("max_lots_per_order")),
        max_risk_pct_per_trade=float(dry_run_payload.get("max_risk_pct_per_trade", 0.75)),
        risk_buckets_pct=_optional_risk_buckets(dry_run_payload.get("risk_buckets_pct")),
        risk_bucket_scale=float(dry_run_payload.get("risk_bucket_scale", 1.0)),
        max_open_risk_pct=float(dry_run_payload.get("max_open_risk_pct", 6.0)),
        max_same_symbol_stack=int(dry_run_payload.get("max_same_symbol_stack", 4)),
        max_concurrent_strategy_trades=int(dry_run_payload.get("max_concurrent_strategy_trades", 17)),
        strategy_magic=int(dry_run_payload.get("strategy_magic", 131500)),
        pivot_strength=int(dry_run_payload.get("pivot_strength", 3)),
        max_bars_from_lp_break=int(dry_run_payload.get("max_bars_from_lp_break", 6)),
        require_lp_pivot_before_fs_mother=_optional_bool(
            dry_run_payload.get("require_lp_pivot_before_fs_mother"),
            default=True,
        ),
        max_entry_wait_bars=int(dry_run_payload.get("max_entry_wait_bars", 6)),
    )
    return DryRunSettings(local=local, executor=executor)


def require_mt5_credentials(local_config: DryRunLocalConfig) -> None:
    """Fail fast when the dry-run MT5 local setup is incomplete."""

    if local_config.use_existing_terminal_session:
        missing_expected = []
        if not local_config.expected_login:
            missing_expected.append("MT5_EXPECTED_LOGIN")
        if not local_config.expected_server:
            missing_expected.append("MT5_EXPECTED_SERVER")
        if missing_expected:
            raise LocalConfigError(
                "Missing MT5 account check value(s): "
                + ", ".join(missing_expected)
                + ". Open MT5 manually and set expected_login/expected_server in config.local.json."
            )
        return

    missing = []
    if not local_config.mt5_login:
        missing.append("MT5_LOGIN")
    if not local_config.mt5_password:
        missing.append("MT5_PASSWORD")
    if not local_config.mt5_server:
        missing.append("MT5_SERVER")
    if missing:
        raise LocalConfigError(
            "Missing MT5 local setup value(s): "
            + ", ".join(missing)
            + ". Copy config.local.example.json to config.local.json or set environment variables."
        )


def telegram_notifier_from_settings(settings: DryRunSettings) -> tuple[TelegramNotifier | None, str | None]:
    """Build a Telegram notifier or return a clear disabled/warning status."""

    local = settings.local
    if not local.telegram_enabled:
        return None, "telegram_disabled"
    if not local.telegram_bot_token or not local.telegram_chat_id:
        return None, "telegram_disabled_missing_credentials"
    return (
        TelegramNotifier(
            TelegramConfig(
                bot_token=local.telegram_bot_token,
                chat_id=local.telegram_chat_id,
                dry_run=local.telegram_dry_run,
            )
        ),
        None,
    )


def initialize_mt5_session(mt5_module: Any, local_config: DryRunLocalConfig) -> None:
    """Initialize MT5 and verify the connected account without logging secrets."""

    require_mt5_credentials(local_config)
    if local_config.use_existing_terminal_session:
        kwargs: dict[str, Any] = {}
        if local_config.mt5_path:
            kwargs["path"] = str(local_config.mt5_path)
        if not mt5_module.initialize(**kwargs):
            raise RuntimeError("MT5 initialize failed. Open and log in to the expected MT5 terminal first.")
        validate_mt5_account(mt5_module.account_info(), local_config)
        return

    try:
        mt5_login = int(str(local_config.mt5_login))
    except ValueError as exc:
        raise LocalConfigError("MT5_LOGIN must be numeric in local dry-run config.") from exc
    kwargs: dict[str, Any] = {
        "login": mt5_login,
        "password": str(local_config.mt5_password),
        "server": str(local_config.mt5_server),
    }
    if local_config.mt5_path:
        kwargs["path"] = str(local_config.mt5_path)
    if not mt5_module.initialize(**kwargs):
        raise RuntimeError("MT5 initialize failed. Check local MT5 config and terminal state.")
    validate_mt5_account(mt5_module.account_info(), local_config)


def validate_mt5_account(account: Any, local_config: DryRunLocalConfig) -> None:
    """Ensure the connected MT5 account is the intended local account."""

    if account is None:
        raise RuntimeError("MT5 account_info unavailable after initialization.")
    expected_login = local_config.expected_login
    expected_server = local_config.expected_server
    if not local_config.use_existing_terminal_session:
        expected_login = expected_login or local_config.mt5_login
        expected_server = expected_server or local_config.mt5_server

    if expected_login:
        try:
            expected_login_int = int(str(expected_login))
        except ValueError as exc:
            raise LocalConfigError("MT5 expected login must be numeric in local dry-run config.") from exc
        if int(getattr(account, "login", 0) or 0) != expected_login_int:
            raise LocalConfigError("Connected MT5 account login does not match expected local config.")

    if expected_server:
        connected_server = str(getattr(account, "server", "") or "").strip()
        if connected_server != str(expected_server).strip():
            raise LocalConfigError("Connected MT5 account server does not match expected local config.")


def load_dry_run_state(path: str | Path) -> DryRunExecutorState:
    state_path = Path(path)
    if not state_path.exists():
        return DryRunExecutorState()
    with state_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return DryRunExecutorState(
        processed_signal_keys=tuple(payload.get("processed_signal_keys", ())),
        order_checked_signal_keys=tuple(payload.get("order_checked_signal_keys", ())),
    )


def save_dry_run_state(path: str | Path, state: DryRunExecutorState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as handle:
        json.dump(state.to_dict(), handle, indent=2)


def append_audit_event(
    path: str | Path,
    event: str,
    *,
    occurred_at_utc: str | pd.Timestamp | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Append one sanitized JSONL audit row and return the row written."""

    timestamp = pd.Timestamp.now(tz="UTC") if occurred_at_utc is None else _as_utc_timestamp(occurred_at_utc)
    row = sanitize_for_logging({"event": event, "occurred_at_utc": timestamp.isoformat(), **payload})
    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str, sort_keys=True) + "\n")
    return row


def sanitize_for_logging(value: Any) -> Any:
    """Redact local-only sensitive values before writing logs."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                sanitized[key] = "<redacted>" if item not in (None, "") else ""
            else:
                sanitized[key] = sanitize_for_logging(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_logging(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_logging(item) for item in value)
    return value


def broker_time_epoch_to_utc(raw_time: int | float | None, broker_timezone: str, *, unit: str = "s") -> pd.Timestamp | None:
    """Convert MT5 broker-time epoch fields to canonical UTC timestamps."""

    if raw_time in (None, 0):
        return None
    timestamp = pd.Timestamp(int(raw_time), unit=unit, tz="UTC")
    return timestamp.tz_localize(None).tz_localize(broker_timezone).tz_convert("UTC")


def mt5_timeframe_constant(mt5_module: Any, timeframe: str) -> Any:
    key = str(timeframe).upper()
    attr = TIMEFRAME_TO_MT5_ATTR.get(key)
    if attr is None or not hasattr(mt5_module, attr):
        raise ValueError(f"Unsupported MT5 dry-run timeframe {timeframe!r}.")
    return getattr(mt5_module, attr)


def fetch_closed_candles(
    mt5_module: Any,
    *,
    symbol: str,
    timeframe: str,
    bars: int,
    broker_timezone: str,
) -> pd.DataFrame:
    """Fetch recent MT5 bars and drop the newest still-forming candle."""

    timeframe_constant = mt5_timeframe_constant(mt5_module, timeframe)
    raw_rates = mt5_module.copy_rates_from_pos(symbol, timeframe_constant, 0, int(bars) + 1)
    if raw_rates is None:
        raise RuntimeError(f"copy_rates_from_pos failed for {symbol} {timeframe}.")
    frame = pd.DataFrame(raw_rates)
    if len(frame) <= 1:
        return pd.DataFrame(columns=CANONICAL_CANDLE_COLUMNS)

    data = frame.copy()
    data["time_utc"] = [
        broker_time_epoch_to_utc(raw_time, broker_timezone) for raw_time in data["time"].tolist()
    ]
    data["spread_points"] = pd.to_numeric(data.get("spread"), errors="coerce")
    if "tick_volume" not in data.columns:
        data["tick_volume"] = pd.NA
    if "real_volume" not in data.columns:
        data["real_volume"] = pd.NA
    data = data.loc[:, CANONICAL_CANDLE_COLUMNS].sort_values("time_utc").reset_index(drop=True)
    return data.iloc[:-1].reset_index(drop=True)


def account_snapshot_from_mt5(mt5_module: Any) -> MT5AccountSnapshot:
    account = mt5_module.account_info()
    if account is None:
        raise RuntimeError("MT5 account_info unavailable for dry-run.")
    return MT5AccountSnapshot(
        equity=float(getattr(account, "equity", 0.0) or 0.0),
        currency=str(getattr(account, "currency", "") or ""),
    )


def symbol_spec_from_mt5(mt5_module: Any, symbol: str) -> MT5SymbolExecutionSpec:
    info = mt5_module.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"MT5 symbol_info unavailable for {symbol}.")
    if not bool(getattr(info, "visible", True)):
        if not mt5_module.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select failed for {symbol}.")
        info = replace_namespace(info, visible=True)
    return MT5SymbolExecutionSpec(
        symbol=str(symbol).upper(),
        digits=int(getattr(info, "digits", 0) or 0),
        point=float(getattr(info, "point", 0.0) or 0.0),
        trade_tick_value=float(getattr(info, "trade_tick_value", 0.0) or 0.0),
        trade_tick_size=float(getattr(info, "trade_tick_size", 0.0) or 0.0),
        volume_min=float(getattr(info, "volume_min", 0.0) or 0.0),
        volume_max=float(getattr(info, "volume_max", 0.0) or 0.0),
        volume_step=float(getattr(info, "volume_step", 0.0) or 0.0),
        trade_stops_level_points=int(getattr(info, "trade_stops_level", 0) or 0),
        trade_freeze_level_points=int(getattr(info, "trade_freeze_level", 0) or 0),
        visible=bool(getattr(info, "visible", True)),
        trade_allowed=bool(getattr(info, "trade_allowed", True)),
    )


def replace_namespace(value: Any, **changes: Any) -> Any:
    """Return a simple object with selected attributes replaced."""

    data = dict(vars(value)) if hasattr(value, "__dict__") else {
        name: getattr(value, name) for name in dir(value) if not name.startswith("_")
    }
    data.update(changes)
    return type("Namespace", (), data)()


def market_snapshot_from_mt5(mt5_module: Any, symbol: str, *, broker_timezone: str) -> MT5MarketSnapshot:
    info = mt5_module.symbol_info(symbol)
    tick = mt5_module.symbol_info_tick(symbol)
    if info is None or tick is None:
        raise RuntimeError(f"MT5 quote unavailable for {symbol}.")
    point = float(getattr(info, "point", 0.0) or 0.0)
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    spread_points = None if point <= 0 else (ask - bid) / point
    raw_time_msc = getattr(tick, "time_msc", None)
    if raw_time_msc not in (None, 0):
        time_utc = broker_time_epoch_to_utc(raw_time_msc, broker_timezone, unit="ms")
    else:
        time_utc = broker_time_epoch_to_utc(getattr(tick, "time", None), broker_timezone, unit="s")
    return MT5MarketSnapshot(bid=bid, ask=ask, time_utc=time_utc, spread_points=spread_points)


def execution_safety_from_config(config: DryRunExecutorConfig) -> ExecutionSafetyLimits:
    return ExecutionSafetyLimits(
        max_risk_pct_per_trade=config.max_risk_pct_per_trade,
        max_open_risk_pct=config.max_open_risk_pct,
        max_lots_per_order=config.max_lots_per_order,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        max_spread_points=config.max_spread_points,
        strategy_magic=config.strategy_magic,
    )


def risk_buckets_from_config(config: DryRunExecutorConfig) -> dict[str, float]:
    """Return configured risk buckets scaled for dry-run sizing tests."""

    scale = float(config.risk_bucket_scale)
    if scale <= 0:
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
    return {timeframe: risk_pct * scale for timeframe, risk_pct in buckets.items()}


def build_order_check_request(mt5_module: Any, intent: MT5OrderIntent) -> dict[str, Any]:
    """Translate a validated intent to an MT5 order_check request."""

    if intent.order_type not in {"BUY_LIMIT", "SELL_LIMIT"}:
        raise ValueError("build_order_check_request only supports pending order intents.")
    order_type = (
        mt5_module.ORDER_TYPE_BUY_LIMIT
        if intent.order_type == "BUY_LIMIT"
        else mt5_module.ORDER_TYPE_SELL_LIMIT
    )
    request = {
        "action": mt5_module.TRADE_ACTION_PENDING,
        "symbol": intent.symbol,
        "volume": intent.volume,
        "type": order_type,
        "price": intent.entry_price,
        "sl": intent.stop_loss,
        "tp": intent.take_profit,
        "deviation": 0,
        "magic": intent.magic,
        "comment": intent.comment,
        "type_filling": mt5_module.ORDER_FILLING_RETURN,
    }
    request.update(_pending_order_time_fields(mt5_module, intent))
    return request


def _pending_order_time_fields(mt5_module: Any, intent: MT5OrderIntent) -> dict[str, Any]:
    mode = _select_pending_order_time_mode(mt5_module, intent.symbol)
    expiration = intent.broker_backstop_expiration_time_utc or intent.expiration_time_utc
    fields = {"type_time": mode}
    if mode in {
        getattr(mt5_module, "ORDER_TIME_SPECIFIED", object()),
        getattr(mt5_module, "ORDER_TIME_SPECIFIED_DAY", object()),
    }:
        fields["expiration"] = int(pd.Timestamp(expiration).timestamp())
    else:
        fields["expiration"] = 0
    return fields


def _select_pending_order_time_mode(mt5_module: Any, symbol: str) -> Any:
    if _symbol_allows_expiration_mode(mt5_module, symbol, "ORDER_TIME_SPECIFIED"):
        return getattr(mt5_module, "ORDER_TIME_SPECIFIED")
    if _symbol_allows_expiration_mode(mt5_module, symbol, "ORDER_TIME_SPECIFIED_DAY"):
        return getattr(mt5_module, "ORDER_TIME_SPECIFIED_DAY")
    if hasattr(mt5_module, "ORDER_TIME_GTC"):
        return getattr(mt5_module, "ORDER_TIME_GTC")
    return getattr(mt5_module, "ORDER_TIME_SPECIFIED")


def _symbol_allows_expiration_mode(mt5_module: Any, symbol: str, order_time_name: str) -> bool:
    if not hasattr(mt5_module, order_time_name):
        return False
    symbol_info = getattr(mt5_module, "symbol_info", lambda _symbol: None)(symbol)
    expiration_mode = getattr(symbol_info, "expiration_mode", None)
    if expiration_mode is None:
        return True
    flag_name_by_order_time = {
        "ORDER_TIME_GTC": "SYMBOL_EXPIRATION_GTC",
        "ORDER_TIME_DAY": "SYMBOL_EXPIRATION_DAY",
        "ORDER_TIME_SPECIFIED": "SYMBOL_EXPIRATION_SPECIFIED",
        "ORDER_TIME_SPECIFIED_DAY": "SYMBOL_EXPIRATION_SPECIFIED_DAY",
    }
    default_flag_by_order_time = {
        "ORDER_TIME_GTC": 1,
        "ORDER_TIME_DAY": 2,
        "ORDER_TIME_SPECIFIED": 4,
        "ORDER_TIME_SPECIFIED_DAY": 8,
    }
    flag_name = flag_name_by_order_time[order_time_name]
    flag = getattr(mt5_module, flag_name, default_flag_by_order_time[order_time_name])
    return bool(int(expiration_mode) & int(flag))


def run_order_check(mt5_module: Any, intent: MT5OrderIntent) -> OrderCheckOutcome:
    request = build_order_check_request(mt5_module, intent)
    result = mt5_module.order_check(request)
    retcode = None if result is None else getattr(result, "retcode", None)
    comment = "order_check returned None" if result is None else str(getattr(result, "comment", "") or "")
    expected_retcode = getattr(mt5_module, "TRADE_RETCODE_DONE", None)
    accepted_retcodes = {0}
    if expected_retcode is not None:
        accepted_retcodes.add(expected_retcode)
    passed = result is not None and retcode is not None and int(retcode) in accepted_retcodes
    return OrderCheckOutcome(passed=passed, request=request, retcode=retcode, comment=comment)


def build_current_v15_candidate() -> TradeModelCandidate:
    return TradeModelCandidate(
        candidate_id="signal_zone_0p5_pullback__fs_structure__1r",
        entry_model="signal_zone_pullback",
        entry_zone=0.5,
        stop_model="fs_structure",
        target_r=1.0,
    )


def default_setup_provider(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    config: DryRunExecutorConfig,
) -> Sequence[TradeSetup | SkippedTrade]:
    if frame.empty:
        return []
    latest_closed_index = len(frame) - 1
    signals = detect_lp_force_strike_signals(
        frame,
        timeframe,
        pivot_strength=config.pivot_strength,
        max_bars_from_lp_break=config.max_bars_from_lp_break,
        require_lp_pivot_before_fs_mother=config.require_lp_pivot_before_fs_mother,
    )
    latest_signals = [signal for signal in signals if int(signal.fs_signal_index) == latest_closed_index]
    candidate = build_current_v15_candidate()
    return [
        build_pending_trade_setup(
            frame,
            signal,
            candidate,
            symbol=symbol,
            timeframe=timeframe,
        )
        for signal in latest_signals
    ]


def build_pending_trade_setup(
    frame: pd.DataFrame,
    signal: LPForceStrikeSignal,
    candidate: TradeModelCandidate,
    *,
    symbol: str,
    timeframe: str,
) -> TradeSetup | SkippedTrade:
    """Build the live pending-order setup from a just-closed signal candle.

    The historical experiment builder waits for a later candle to prove the
    pullback entry was reached. The dry-run executor must instead place/check
    the pending pullback order immediately after the signal candle closes.
    """

    data = add_atr(frame)
    signal_index = int(signal.fs_signal_index)
    if signal_index < 0 or signal_index >= len(data):
        return _pending_skip(candidate, symbol, timeframe, signal, "signal_index_out_of_range")

    if candidate.entry_model not in {"signal_midpoint_pullback", "signal_zone_pullback"}:
        return _pending_skip(candidate, symbol, timeframe, signal, "unsupported_entry_model")
    if candidate.stop_model != "fs_structure":
        return _pending_skip(candidate, symbol, timeframe, signal, "unsupported_stop_model")

    signal_row = data.loc[signal_index]
    signal_high = float(signal_row["high"])
    signal_low = float(signal_row["low"])
    if signal_high <= signal_low:
        return _pending_skip(candidate, symbol, timeframe, signal, "invalid_entry_range")

    side = "long" if signal.side == "bullish" else "short"
    structure_low = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "low"].min())
    structure_high = float(data.loc[signal.fs_mother_index : signal.fs_signal_index, "high"].max())
    stop_price = structure_low if side == "long" else structure_high
    zone = 0.5 if candidate.entry_model == "signal_midpoint_pullback" else float(candidate.entry_zone or 0.5)
    entry_price = signal_low + (signal_high - signal_low) * zone
    if signal.side == "bearish":
        entry_price = signal_high - (signal_high - signal_low) * zone

    risk = float(entry_price - stop_price) if side == "long" else float(stop_price - entry_price)
    atr = float(data.loc[signal_index, "atr"])
    target_price = entry_price + risk * candidate.target_r if side == "long" else entry_price - risk * candidate.target_r
    return TradeSetup(
        setup_id=f"{symbol}_{timeframe}_{signal.fs_signal_index}_{candidate.candidate_id}",
        side=side,
        entry_index=signal_index + 1,
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        target_price=float(target_price),
        symbol=symbol,
        timeframe=timeframe,
        signal_index=signal.fs_signal_index,
        metadata={
            "candidate_id": candidate.candidate_id,
            "entry_model": candidate.entry_model,
            "entry_wait_mode": "fixed_bars",
            "entry_wait_same_bar_priority": "entry",
            "entry_zone": candidate.entry_zone,
            "stop_model": candidate.stop_model,
            "exit_model": candidate.exit_model,
            "target_r": candidate.target_r,
            "max_risk_atr": candidate.max_risk_atr,
            "partial_target_r": candidate.partial_target_r,
            "partial_fraction": candidate.partial_fraction,
            "lp_price": signal.lp_price,
            "lp_break_index": signal.lp_break_index,
            "lp_break_time_utc": str(signal.lp_break_time_utc),
            "fs_mother_index": signal.fs_mother_index,
            "fs_signal_index": signal.fs_signal_index,
            "fs_signal_time_utc": str(signal.fs_signal_time_utc),
            "fs_total_bars": signal.fs_total_bars,
            "bars_from_lp_break": signal.bars_from_lp_break,
            "structure_low": structure_low,
            "structure_high": structure_high,
            "atr": None if pd.isna(atr) else atr,
            "risk_atr": None if pd.isna(atr) or atr <= 0 else risk / atr,
            "pending_from_latest_closed_signal": True,
        },
    )


def _pending_skip(
    candidate: TradeModelCandidate,
    symbol: str,
    timeframe: str,
    signal: LPForceStrikeSignal,
    reason: str,
    *,
    detail: str = "",
) -> SkippedTrade:
    return SkippedTrade(
        candidate_id=candidate.candidate_id,
        symbol=symbol,
        timeframe=timeframe,
        side=signal.side,
        signal_index=signal.fs_signal_index,
        signal_time_utc=signal.fs_signal_time_utc,
        reason=reason,
        detail=detail,
    )


def process_trade_setup_dry_run(
    mt5_module: Any,
    setup: TradeSetup,
    *,
    config: DryRunExecutorConfig,
    state: DryRunExecutorState,
    market: MT5MarketSnapshot | None = None,
    notifier: TelegramNotifier | None = None,
) -> DryRunSetupResult:
    """Run one tested setup through intent building and MT5 order_check only."""

    signal_key = signal_key_for_setup(setup)
    if signal_key in state.order_checked_signal_keys:
        append_audit_event(config.journal_path, "signal_already_checked", signal_key=signal_key)
        return DryRunSetupResult(state=state, signal_key=signal_key, status="already_checked")

    signal_event = NotificationEvent(
        kind="signal_detected",
        mode="DRY_RUN",
        title="LP + Force Strike signal detected",
        severity="info",
        symbol=str(setup.symbol).upper(),
        timeframe=str(setup.timeframe).upper(),
        side=setup.side,
        signal_key=signal_key,
        fields={
            "setup_id": setup.setup_id,
            "entry": setup.entry_price,
            "stop_loss": setup.stop_price,
            "take_profit": setup.target_price,
        },
    )
    append_audit_event(
        config.journal_path,
        signal_event.kind,
        signal_key=signal_key,
        notification=format_notification_message(signal_event),
        setup_id=setup.setup_id,
    )

    account = account_snapshot_from_mt5(mt5_module)
    symbol_spec = symbol_spec_from_mt5(mt5_module, setup.symbol)
    market_snapshot = market or market_snapshot_from_mt5(
        mt5_module,
        setup.symbol,
        broker_timezone=config.broker_timezone,
    )
    if market is None:
        append_market_snapshot(config.journal_path, setup.symbol, setup.timeframe, market_snapshot)
    decision = build_mt5_order_intent(
        setup,
        account=account,
        symbol_spec=symbol_spec,
        market=market_snapshot,
        safety=execution_safety_from_config(config),
        exposure=ExistingStrategyExposure(existing_signal_keys=state.order_checked_signal_keys),
        risk_buckets=risk_buckets_from_config(config),
    )
    decision_event = notification_from_execution_decision(decision, mode="DRY_RUN")
    append_audit_event(
        config.journal_path,
        decision_event.kind,
        signal_key=signal_key,
        notification=format_notification_message(decision_event),
        decision=decision.to_dict(),
    )
    processed_state = _state_with_processed_key(state, signal_key)
    if not decision.ready or decision.intent is None:
        deliver_notification_best_effort(notifier, decision_event)
        return DryRunSetupResult(state=processed_state, signal_key=signal_key, status="rejected")

    outcome = run_order_check(mt5_module, decision.intent)
    order_check_event = NotificationEvent(
        kind="order_check_passed" if outcome.passed else "order_check_failed",
        mode="DRY_RUN",
        title="MT5 order_check passed" if outcome.passed else "MT5 order_check failed",
        severity="info" if outcome.passed else "warning",
        symbol=decision.intent.symbol,
        timeframe=decision.intent.timeframe,
        side=decision.intent.side,
        status="passed" if outcome.passed else "failed",
        signal_key=signal_key,
        fields={"retcode": outcome.retcode, "comment": outcome.comment},
    )
    append_audit_event(
        config.journal_path,
        order_check_event.kind,
        signal_key=signal_key,
        notification=format_notification_message(order_check_event),
        order_check=outcome.to_dict(),
    )
    deliver_notification_best_effort(notifier, order_check_event)
    checked_state = _state_with_checked_key(processed_state, signal_key)
    return DryRunSetupResult(
        state=checked_state,
        signal_key=signal_key,
        status="order_check_passed" if outcome.passed else "order_check_failed",
        order_check=outcome,
    )


def run_dry_run_cycle(
    mt5_module: Any,
    *,
    config: DryRunExecutorConfig,
    state: DryRunExecutorState,
    notifier: TelegramNotifier | None = None,
    setup_provider: SetupProvider = default_setup_provider,
) -> DryRunCycleResult:
    """Run one finite dry-run polling cycle over configured symbols/timeframes."""

    frames_processed = 0
    setups_checked = 0
    setups_rejected = 0
    current_state = state
    for symbol in config.symbols:
        for timeframe in config.timeframes:
            frame = fetch_closed_candles(
                mt5_module,
                symbol=symbol,
                timeframe=timeframe,
                bars=config.history_bars,
                broker_timezone=config.broker_timezone,
            )
            market = market_snapshot_from_mt5(mt5_module, symbol, broker_timezone=config.broker_timezone)
            append_market_snapshot(config.journal_path, symbol, timeframe, market)
            frames_processed += 1
            for item in setup_provider(frame, symbol, timeframe, config):
                if isinstance(item, SkippedTrade):
                    setups_rejected += 1
                    append_audit_event(config.journal_path, "setup_skipped", skipped=item.to_dict())
                    continue
                result = process_trade_setup_dry_run(
                    mt5_module,
                    item,
                    config=config,
                    state=current_state,
                    market=market,
                    notifier=notifier,
                )
                current_state = result.state
                setups_checked += 1 if result.order_check is not None else 0
                setups_rejected += 1 if result.status == "rejected" else 0
    save_dry_run_state(config.state_path, current_state)
    return DryRunCycleResult(
        state=current_state,
        frames_processed=frames_processed,
        setups_checked=setups_checked,
        setups_rejected=setups_rejected,
    )


def append_market_snapshot(
    journal_path: str | Path,
    symbol: str,
    timeframe: str,
    market: MT5MarketSnapshot,
) -> dict[str, Any]:
    return append_audit_event(
        journal_path,
        "market_snapshot",
        symbol=symbol,
        timeframe=timeframe,
        bid=market.bid,
        ask=market.ask,
        spread_points=market.spread_points,
        market_time_utc=None if market.time_utc is None else str(market.time_utc),
    )


def deliver_notification_best_effort(
    notifier: TelegramNotifier | None,
    event: NotificationEvent,
    *,
    reply_to_message_id: int | None = None,
) -> NotificationDelivery | None:
    """Send Telegram without letting delivery failure affect trade validity."""

    if notifier is None:
        return None
    try:
        return notifier.send_event(event, reply_to_message_id=reply_to_message_id)
    except Exception as exc:
        return NotificationDelivery(
            status="failed",
            attempted=True,
            sent=False,
            message=format_notification_message(event),
            error=f"{type(exc).__name__}: {exc}",
            reply_to_message_id=reply_to_message_id,
        )


def _first_value(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


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


def _tuple_of_strings(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _resolve_local_path(base_dir: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _as_utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return lower in SENSITIVE_FIELD_NAMES or lower.endswith("_token") or lower.endswith("_password")


def _append_unique(values: Iterable[str], value: str) -> tuple[str, ...]:
    items = tuple(values)
    if value in items:
        return items
    return (*items, value)


def _state_with_processed_key(state: DryRunExecutorState, signal_key: str) -> DryRunExecutorState:
    return replace(state, processed_signal_keys=_append_unique(state.processed_signal_keys, signal_key))


def _state_with_checked_key(state: DryRunExecutorState, signal_key: str) -> DryRunExecutorState:
    return replace(state, order_checked_signal_keys=_append_unique(state.order_checked_signal_keys, signal_key))
