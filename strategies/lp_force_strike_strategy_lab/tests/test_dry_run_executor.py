from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
for src_root in [
    PROJECT_ROOT / "src",
    WORKSPACE_ROOT / "concepts" / "lp_levels_lab" / "src",
    WORKSPACE_ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    WORKSPACE_ROOT / "shared" / "backtest_engine_lab" / "src",
]:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from backtest_engine_lab import TradeSetup  # noqa: E402
from lp_force_strike_strategy_lab import (  # noqa: E402
    DryRunExecutorConfig,
    DryRunExecutorState,
    DryRunLocalConfig,
    DryRunSettings,
    LocalConfigError,
    NotificationEvent,
    SkippedTrade,
    TelegramConfig,
    TelegramNotifier,
    TradeModelCandidate,
    account_snapshot_from_mt5,
    append_audit_event,
    append_market_snapshot,
    broker_time_epoch_to_utc,
    build_current_v15_candidate,
    build_order_check_request,
    build_pending_trade_setup,
    default_setup_provider,
    deliver_notification_best_effort,
    execution_safety_from_config,
    fetch_closed_candles,
    initialize_mt5_session,
    load_dry_run_settings,
    load_dry_run_state,
    market_snapshot_from_mt5,
    mt5_timeframe_constant,
    process_trade_setup_dry_run,
    require_mt5_credentials,
    risk_buckets_from_config,
    run_dry_run_cycle,
    run_order_check,
    sanitize_for_logging,
    save_dry_run_state,
    signal_key_for_setup,
    symbol_spec_from_mt5,
    telegram_notifier_from_settings,
    validate_mt5_account,
)
from lp_force_strike_strategy_lab.dry_run_executor import _optional_bool, replace_namespace  # noqa: E402
import lp_force_strike_strategy_lab.dry_run_executor as dry_run_module  # noqa: E402


def _setup(*, side: str = "long", entry: float = 1.1000, stop: float = 1.0950, target: float = 1.1050) -> TradeSetup:
    return TradeSetup(
        setup_id="EURUSD_H4_long",
        side=side,  # type: ignore[arg-type]
        entry_index=11,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        symbol="EURUSD",
        timeframe="H4",
        signal_index=10,
        metadata={
            "candidate_id": "signal_zone_0p5_pullback__fs_structure__1r",
            "fs_signal_time_utc": "2026-01-01T00:00:00Z",
        },
    )


def _short_setup() -> TradeSetup:
    return _setup(side="short", entry=1.2000, stop=1.2100, target=1.1900)


def _signal(*, side: str = "bullish", signal_index: int = 1, mother_index: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        side=side,
        scenario="force_bottom" if side == "bullish" else "force_top",
        lp_price=1.0,
        lp_break_index=0,
        lp_break_time_utc=pd.Timestamp("2026-01-01T00:00:00Z"),
        lp_pivot_index=0,
        lp_pivot_time_utc=pd.Timestamp("2025-12-31T20:00:00Z"),
        fs_mother_index=mother_index,
        fs_signal_index=signal_index,
        fs_mother_time_utc=pd.Timestamp("2026-01-01T00:00:00Z"),
        fs_signal_time_utc=pd.Timestamp("2026-01-01T04:00:00Z"),
        bars_from_lp_break=2,
        fs_total_bars=2,
    )


def _pending_frame(*, rows: int = 2, signal_high: float = 1.3, signal_low: float = 1.0) -> pd.DataFrame:
    times = pd.date_range("2026-01-01T00:00:00Z", periods=rows, freq="4h")
    frame = pd.DataFrame(
        {
            "time_utc": times,
            "open": [1.1] * rows,
            "high": [1.2] * rows,
            "low": [0.9] * rows,
            "close": [1.1] * rows,
        }
    )
    frame.loc[rows - 1, ["high", "low"]] = [signal_high, signal_low]
    return frame


def _journal_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class FakeMT5:
    TIMEFRAME_H4 = 240
    TIMEFRAME_H8 = 480
    TIMEFRAME_H12 = 720
    TIMEFRAME_D1 = 1440
    TIMEFRAME_W1 = 10080
    TRADE_ACTION_PENDING = 5
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_TIME_SPECIFIED = 2
    ORDER_TIME_SPECIFIED_DAY = 3
    SYMBOL_EXPIRATION_GTC = 1
    SYMBOL_EXPIRATION_DAY = 2
    SYMBOL_EXPIRATION_SPECIFIED = 4
    SYMBOL_EXPIRATION_SPECIFIED_DAY = 8
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009

    def __init__(self) -> None:
        self.initialize_result = True
        self.initialize_kwargs: dict | None = None
        self.select_result = True
        self.account = SimpleNamespace(login=123, server="Demo", equity=100_000.0, currency="USD")
        self.info = SimpleNamespace(
            digits=5,
            point=0.0001,
            trade_tick_value=10.0,
            trade_tick_size=0.0001,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            trade_stops_level=0,
            trade_freeze_level=0,
            visible=True,
            trade_allowed=True,
        )
        self.tick = SimpleNamespace(
            bid=1.1018,
            ask=1.1020,
            time_msc=int(pd.Timestamp("2026-01-01 03:00:00+00:00").timestamp() * 1000),
            time=0,
        )
        self.rates = [
            {
                "time": int(pd.Timestamp("2026-01-01 00:00:00+00:00").timestamp()),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "tick_volume": 10,
                "spread": 2,
            },
            {
                "time": int(pd.Timestamp("2026-01-01 04:00:00+00:00").timestamp()),
                "open": 1.1,
                "high": 1.2,
                "low": 1.0,
                "close": 1.15,
                "tick_volume": 11,
                "spread": 3,
            },
            {
                "time": int(pd.Timestamp("2026-01-01 08:00:00+00:00").timestamp()),
                "open": 1.2,
                "high": 1.3,
                "low": 1.1,
                "close": 1.25,
                "tick_volume": 12,
                "spread": 4,
            },
        ]
        self.order_check_result = SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, comment="check ok")
        self.order_check_requests: list[dict] = []

    def initialize(self, **kwargs) -> bool:
        self.initialize_kwargs = kwargs
        return self.initialize_result

    def account_info(self):
        return self.account

    def symbol_info(self, symbol: str):
        self.last_symbol = symbol
        return self.info

    def symbol_select(self, symbol: str, visible: bool) -> bool:
        self.selected = (symbol, visible)
        return self.select_result

    def symbol_info_tick(self, symbol: str):
        self.last_tick_symbol = symbol
        return self.tick

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, count: int):
        self.last_rates_request = (symbol, timeframe, start_pos, count)
        return self.rates

    def order_check(self, request: dict):
        self.order_check_requests.append(request)
        return self.order_check_result


class FakeNotifierClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.payloads: list[dict] = []

    def post_json(self, url: str, payload: dict, *, timeout_seconds: float) -> dict:
        self.calls += 1
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return {"ok": True, "result": {"message_id": 1}}


class SlotObject:
    __slots__ = ("visible", "value")

    def __init__(self) -> None:
        self.visible = False
        self.value = 1


class FakeMT5WithoutExpectedRetcode:
    TRADE_ACTION_PENDING = 5
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_SPECIFIED = 2
    ORDER_FILLING_RETURN = 2

    def __init__(self) -> None:
        self.order_check_result = SimpleNamespace(retcode=123, comment="no expected constant")
        self.order_check_requests: list[dict] = []

    def order_check(self, request: dict):
        self.order_check_requests.append(request)
        return self.order_check_result


class DryRunExecutorTests(unittest.TestCase):
    def test_load_settings_merges_ignored_file_and_env_without_exposing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {
                            "use_existing_terminal_session": True,
                            "expected_login": "123",
                            "path": "terminal.exe",
                        },
                        "telegram": {"enabled": True, "dry_run": False},
                        "dry_run": {
                            "symbols": "EURUSD",
                            "timeframes": ["H4"],
                            "broker_timezone": "Europe/Helsinki",
                            "history_bars": 12,
                            "journal_path": "data/live/journal.jsonl",
                            "state_path": "data/live/state.json",
                            "max_spread_points": "15",
                            "max_lots_per_order": "0.5",
                            "risk_bucket_scale": "0.1",
                            "require_lp_pivot_before_fs_mother": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = load_dry_run_settings(
                config_path,
                env={
                    "MT5_PASSWORD": "fixture-password",
                    "MT5_EXPECTED_SERVER": "Demo",
                    "MT5_SERVER": "Secret-Demo",
                    "TELEGRAM_BOT_TOKEN": "fixture-token",
                    "TELEGRAM_CHAT_ID": "secret-chat",
                },
            )

            self.assertTrue(settings.local.use_existing_terminal_session)
            self.assertEqual(settings.local.expected_login, "123")
            self.assertEqual(settings.local.expected_server, "Demo")
            self.assertIsNone(settings.local.mt5_login)
            self.assertEqual(settings.local.mt5_password, "fixture-password")
            self.assertEqual(settings.local.mt5_server, "Secret-Demo")
            self.assertEqual(settings.local.telegram_bot_token, "fixture-token")
            self.assertEqual(settings.executor.symbols, ("EURUSD",))
            self.assertEqual(settings.executor.timeframes, ("H4",))
            self.assertEqual(settings.executor.max_spread_points, 15.0)
            self.assertEqual(settings.executor.max_lots_per_order, 0.5)
            self.assertEqual(settings.executor.risk_bucket_scale, 0.1)
            self.assertFalse(settings.executor.require_lp_pivot_before_fs_mother)
            self.assertTrue(Path(settings.executor.journal_path).is_absolute())
            self.assertNotIn("secret", str(settings.safe_dict()).lower())

            env_settings = load_dry_run_settings(
                Path(tmpdir) / "missing.local.json",
                env={
                    "MT5_USE_EXISTING_TERMINAL_SESSION": "false",
                    "MT5_LOGIN": "1",
                    "MT5_PASSWORD": "2",
                    "MT5_SERVER": "3",
                },
            )
            self.assertEqual(env_settings.local.mt5_server, "3")
            self.assertFalse(env_settings.local.use_existing_terminal_session)
            self.assertEqual(env_settings.executor.symbols, ("EURUSD",))
            self.assertTrue(env_settings.executor.require_lp_pivot_before_fs_mother)

    def test_load_settings_accepts_powershell_utf8_bom_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mt5": {"expected_login": "123", "expected_server": "Demo"},
                        "dry_run": {"symbols": ["EURUSD"], "timeframes": ["H4"]},
                    }
                ),
                encoding="utf-8-sig",
            )

            settings = load_dry_run_settings(config_path, env={})

            self.assertEqual(settings.local.expected_login, "123")
            self.assertEqual(settings.local.expected_server, "Demo")
            self.assertEqual(settings.executor.symbols, ("EURUSD",))

    def test_required_credentials_and_initialize_fail_without_leaking_secrets(self) -> None:
        with self.assertRaisesRegex(LocalConfigError, "MT5_EXPECTED_LOGIN, MT5_EXPECTED_SERVER"):
            require_mt5_credentials(DryRunLocalConfig())
        with self.assertRaisesRegex(LocalConfigError, "MT5_EXPECTED_SERVER"):
            require_mt5_credentials(DryRunLocalConfig(expected_login="123"))
        with self.assertRaisesRegex(LocalConfigError, "MT5_LOGIN, MT5_PASSWORD, MT5_SERVER"):
            require_mt5_credentials(DryRunLocalConfig(use_existing_terminal_session=False))
        with self.assertRaisesRegex(LocalConfigError, "MT5_PASSWORD"):
            require_mt5_credentials(
                DryRunLocalConfig(
                    use_existing_terminal_session=False,
                    mt5_login="1",
                    mt5_server="server",
                )
            )

        mt5 = FakeMT5()
        initialize_mt5_session(
            mt5,
            DryRunLocalConfig(
                use_existing_terminal_session=True,
                expected_login="123",
                expected_server="Demo",
                mt5_path="path.exe",
            ),
        )
        self.assertEqual(mt5.initialize_kwargs, {"path": "path.exe"})

        explicit_mt5 = FakeMT5()
        initialize_mt5_session(
            explicit_mt5,
            DryRunLocalConfig(
                use_existing_terminal_session=False,
                mt5_login="123",
                mt5_password="secret",
                mt5_server="Demo",
                mt5_path="path.exe",
            ),
        )
        self.assertEqual(
            explicit_mt5.initialize_kwargs,
            {"login": 123, "password": "secret", "server": "Demo", "path": "path.exe"},
        )

        with self.assertRaisesRegex(LocalConfigError, "account login"):
            initialize_mt5_session(
                FakeMT5(),
                DryRunLocalConfig(
                    use_existing_terminal_session=True,
                    expected_login="999",
                    expected_server="Demo",
                ),
            )
        with self.assertRaisesRegex(LocalConfigError, "account server"):
            validate_mt5_account(
                SimpleNamespace(login=123, server="Other"),
                DryRunLocalConfig(expected_login="123", expected_server="Demo"),
            )
        with self.assertRaisesRegex(LocalConfigError, "expected login must be numeric"):
            validate_mt5_account(
                SimpleNamespace(login=123, server="Demo"),
                DryRunLocalConfig(expected_login="abc", expected_server="Demo"),
            )
        with self.assertRaisesRegex(RuntimeError, "account_info unavailable"):
            validate_mt5_account(None, DryRunLocalConfig(expected_login="123", expected_server="Demo"))
        validate_mt5_account(SimpleNamespace(login=123, server="Demo"), DryRunLocalConfig())
        validate_mt5_account(
            SimpleNamespace(login=123, server="Demo"),
            DryRunLocalConfig(expected_login="123", expected_server="Demo"),
        )
        self.assertFalse(_optional_bool(False, default=True))

        mt5 = FakeMT5()
        mt5.initialize_result = False
        with self.assertRaisesRegex(RuntimeError, "Open and log in"):
            initialize_mt5_session(
                mt5,
                DryRunLocalConfig(expected_login="123", expected_server="Demo"),
            )

        mt5 = FakeMT5()
        mt5.initialize_result = False
        with self.assertRaisesRegex(RuntimeError, "MT5 initialize failed"):
            initialize_mt5_session(
                mt5,
                DryRunLocalConfig(
                    use_existing_terminal_session=False,
                    mt5_login="123",
                    mt5_password="secret",
                    mt5_server="Demo",
                ),
            )
        with self.assertRaisesRegex(LocalConfigError, "MT5_LOGIN must be numeric"):
            initialize_mt5_session(
                FakeMT5(),
                DryRunLocalConfig(
                    use_existing_terminal_session=False,
                    mt5_login="abc",
                    mt5_password="secret",
                    mt5_server="Demo",
                ),
            )

    def test_telegram_notifier_is_optional_and_best_effort(self) -> None:
        disabled, disabled_warning = telegram_notifier_from_settings(
            DryRunSettings(local=DryRunLocalConfig(), executor=DryRunExecutorConfig())
        )
        self.assertIsNone(disabled)
        self.assertEqual(disabled_warning, "telegram_disabled")

        missing, missing_warning = telegram_notifier_from_settings(
            DryRunSettings(local=DryRunLocalConfig(telegram_enabled=True), executor=DryRunExecutorConfig())
        )
        self.assertIsNone(missing)
        self.assertEqual(missing_warning, "telegram_disabled_missing_credentials")

        notifier, warning = telegram_notifier_from_settings(
            DryRunSettings(
                local=DryRunLocalConfig(telegram_enabled=True, telegram_bot_token="token", telegram_chat_id="chat"),
                executor=DryRunExecutorConfig(),
            )
        )
        self.assertIsInstance(notifier, TelegramNotifier)
        self.assertIsNone(warning)

        event = NotificationEvent(kind="signal_detected", mode="DRY_RUN", title="Signal")
        self.assertIsNone(deliver_notification_best_effort(None, event))
        dry = deliver_notification_best_effort(notifier, event)
        assert dry is not None
        self.assertEqual(dry.status, "dry_run")

        failing = TelegramNotifier(
            TelegramConfig("token", "chat", dry_run=False),
            FakeNotifierClient(error=RuntimeError("network down")),
        )
        failed = deliver_notification_best_effort(failing, event)
        assert failed is not None
        self.assertEqual(failed.status, "failed")
        self.assertIn("network down", failed.error or "")

    def test_journal_state_and_sanitizing_are_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            state_path = Path(tmpdir) / "state.json"

            self.assertEqual(load_dry_run_state(state_path), DryRunExecutorState())
            state = DryRunExecutorState(processed_signal_keys=("a",), order_checked_signal_keys=("b",))
            save_dry_run_state(state_path, state)
            self.assertEqual(load_dry_run_state(state_path), state)

            row = append_audit_event(
                journal_path,
                "setup",
                occurred_at_utc="2026-01-01 00:00:00",
                mt5_password="secret",
                nested={"telegram_bot_token": "token", "signal_key": "lpfs:ok"},
                items=[{"server": "fixture-server"}],
                tuple_value=("x",),
            )

            self.assertEqual(row["mt5_password"], "<redacted>")
            self.assertEqual(row["nested"]["telegram_bot_token"], "<redacted>")
            self.assertEqual(row["nested"]["signal_key"], "lpfs:ok")
            self.assertEqual(row["items"][0]["server"], "<redacted>")
            self.assertEqual(row["tuple_value"], ("x",))
            self.assertEqual(_journal_rows(journal_path)[0]["mt5_password"], "<redacted>")
            self.assertEqual(sanitize_for_logging({"chat_id": "", "api_key": "k"})["chat_id"], "")

            timed = append_audit_event(journal_path, "auto_time")
            self.assertIn("occurred_at_utc", timed)
            aware = append_audit_event(
                journal_path,
                "aware_time",
                occurred_at_utc=pd.Timestamp("2026-01-01 01:00:00+01:00"),
            )
            self.assertEqual(aware["occurred_at_utc"], "2026-01-01T00:00:00+00:00")

    def test_broker_time_closed_candles_and_mt5_snapshots_are_explicit(self) -> None:
        raw_time = int(pd.Timestamp("2026-04-21 15:14:00+00:00").timestamp())
        self.assertEqual(
            broker_time_epoch_to_utc(raw_time, "Europe/Helsinki"),
            pd.Timestamp("2026-04-21 12:14:00+00:00"),
        )
        self.assertIsNone(broker_time_epoch_to_utc(None, "UTC"))
        self.assertIsNone(broker_time_epoch_to_utc(0, "UTC"))

        mt5 = FakeMT5()
        frame = fetch_closed_candles(mt5, symbol="EURUSD", timeframe="H4", bars=2, broker_timezone="UTC")
        self.assertEqual(mt5.last_rates_request, ("EURUSD", 240, 0, 3))
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["time_utc"].iloc[-1], pd.Timestamp("2026-01-01 04:00:00+00:00"))
        self.assertEqual(float(frame["spread_points"].iloc[0]), 2.0)

        mt5.rates = [{"time": raw_time, "open": 1, "high": 1, "low": 1, "close": 1}]
        self.assertTrue(fetch_closed_candles(mt5, symbol="EURUSD", timeframe="H4", bars=1, broker_timezone="UTC").empty)
        mt5.rates = [
            {"time": raw_time, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "real_volume": 7},
            {
                "time": raw_time + 1,
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "real_volume": 8,
            },
        ]
        missing_tick_volume = fetch_closed_candles(mt5, symbol="EURUSD", timeframe="H4", bars=1, broker_timezone="UTC")
        self.assertTrue(pd.isna(missing_tick_volume.loc[0, "tick_volume"]))
        self.assertEqual(int(missing_tick_volume.loc[0, "real_volume"]), 7)
        mt5.rates = None
        with self.assertRaisesRegex(RuntimeError, "copy_rates_from_pos failed"):
            fetch_closed_candles(mt5, symbol="EURUSD", timeframe="H4", bars=1, broker_timezone="UTC")
        with self.assertRaisesRegex(ValueError, "Unsupported MT5 dry-run timeframe"):
            mt5_timeframe_constant(mt5, "M30")

    def test_account_symbol_and_market_snapshot_builders_cover_error_paths(self) -> None:
        mt5 = FakeMT5()
        self.assertEqual(account_snapshot_from_mt5(mt5).equity, 100_000.0)
        mt5.account = None
        with self.assertRaisesRegex(RuntimeError, "account_info"):
            account_snapshot_from_mt5(mt5)
        mt5.account = SimpleNamespace(equity=100_000.0, currency="USD")

        spec = symbol_spec_from_mt5(mt5, "eurusd")
        self.assertEqual(spec.symbol, "EURUSD")
        self.assertTrue(spec.visible)
        mt5.info = None
        with self.assertRaisesRegex(RuntimeError, "symbol_info"):
            symbol_spec_from_mt5(mt5, "EURUSD")

        mt5.info = SimpleNamespace(
            digits=5,
            point=0.0001,
            trade_tick_value=10.0,
            trade_tick_size=0.0001,
            volume_min=0.01,
            volume_max=1.0,
            volume_step=0.01,
            visible=False,
            trade_allowed=True,
        )
        self.assertTrue(symbol_spec_from_mt5(mt5, "EURUSD").visible)
        mt5.info.visible = False
        mt5.select_result = False
        with self.assertRaisesRegex(RuntimeError, "symbol_select"):
            symbol_spec_from_mt5(mt5, "EURUSD")

        replaced = replace_namespace(SlotObject(), visible=True)
        self.assertTrue(replaced.visible)
        self.assertEqual(replaced.value, 1)

        mt5 = FakeMT5()
        market = market_snapshot_from_mt5(mt5, "EURUSD", broker_timezone="UTC")
        self.assertEqual(market.bid, 1.1018)
        self.assertAlmostEqual(float(market.spread_points or 0), 2.0)
        self.assertEqual(market.time_utc, pd.Timestamp("2026-01-01 03:00:00+00:00"))

        mt5.tick = SimpleNamespace(bid=1.0, ask=1.1, time_msc=0, time=int(pd.Timestamp("2026-01-01 04:00:00+00:00").timestamp()))
        mt5.info.point = 0.0
        market_without_point = market_snapshot_from_mt5(mt5, "EURUSD", broker_timezone="UTC")
        self.assertIsNone(market_without_point.spread_points)
        self.assertEqual(market_without_point.time_utc, pd.Timestamp("2026-01-01 04:00:00+00:00"))
        mt5.info = None
        with self.assertRaisesRegex(RuntimeError, "quote unavailable"):
            market_snapshot_from_mt5(mt5, "EURUSD", broker_timezone="UTC")

    def test_order_check_request_and_outcome_are_order_check_only(self) -> None:
        mt5 = FakeMT5()
        long_request = build_order_check_request(
            mt5,
            process_trade_setup_dry_run(
                mt5,
                _setup(),
                config=DryRunExecutorConfig(journal_path=str(Path(tempfile.gettempdir()) / "unused.jsonl")),
                state=DryRunExecutorState(),
            ).order_check.request if False else _intent_for_request("BUY_LIMIT"),
        )
        self.assertEqual(long_request["type"], mt5.ORDER_TYPE_BUY_LIMIT)
        self.assertEqual(long_request["action"], mt5.TRADE_ACTION_PENDING)
        self.assertEqual(long_request["type_time"], mt5.ORDER_TIME_SPECIFIED)
        self.assertEqual(long_request["expiration"], int(pd.Timestamp("2026-01-12T04:00:00Z").timestamp()))

        short_request = build_order_check_request(mt5, _intent_for_request("SELL_LIMIT"))
        self.assertEqual(short_request["type"], mt5.ORDER_TYPE_SELL_LIMIT)

        mt5.info.expiration_mode = mt5.SYMBOL_EXPIRATION_SPECIFIED_DAY
        specified_day = build_order_check_request(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertEqual(specified_day["type_time"], mt5.ORDER_TIME_SPECIFIED_DAY)
        self.assertEqual(specified_day["expiration"], int(pd.Timestamp("2026-01-12T04:00:00Z").timestamp()))

        mt5.info.expiration_mode = mt5.SYMBOL_EXPIRATION_DAY
        gtc_backstop = build_order_check_request(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertEqual(gtc_backstop["type_time"], mt5.ORDER_TIME_GTC)
        self.assertEqual(gtc_backstop["expiration"], 0)

        no_fallback_mt5 = SimpleNamespace(
            TRADE_ACTION_PENDING=5,
            ORDER_TYPE_BUY_LIMIT=2,
            ORDER_TYPE_SELL_LIMIT=3,
            ORDER_TIME_SPECIFIED=2,
            ORDER_FILLING_RETURN=2,
            SYMBOL_EXPIRATION_DAY=2,
            symbol_info=lambda symbol: SimpleNamespace(expiration_mode=2),
        )
        specified_fallback = build_order_check_request(no_fallback_mt5, _intent_for_request("BUY_LIMIT"))
        self.assertEqual(specified_fallback["type_time"], no_fallback_mt5.ORDER_TIME_SPECIFIED)

        passed = run_order_check(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertTrue(passed.passed)
        self.assertEqual(passed.retcode, mt5.TRADE_RETCODE_DONE)
        self.assertEqual(mt5.order_check_requests[0]["symbol"], "EURUSD")

        mt5.order_check_result = SimpleNamespace(retcode=0, comment="Done")
        zero_retcode = run_order_check(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertTrue(zero_retcode.passed)

        mt5.order_check_result = SimpleNamespace(retcode=123, comment="bad")
        failed = run_order_check(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertFalse(failed.passed)
        self.assertEqual(failed.comment, "bad")

        mt5.order_check_result = SimpleNamespace(retcode=None, comment="missing retcode")
        missing_retcode = run_order_check(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertFalse(missing_retcode.passed)

        mt5.order_check_result = None
        none_result = run_order_check(mt5, _intent_for_request("BUY_LIMIT"))
        self.assertFalse(none_result.passed)
        self.assertEqual(none_result.comment, "order_check returned None")

        no_expected_mt5 = FakeMT5WithoutExpectedRetcode()
        no_expected_mt5.order_check_result = SimpleNamespace(retcode=0, comment="no expected constant")
        no_expected = run_order_check(no_expected_mt5, _intent_for_request("BUY_LIMIT"))
        self.assertTrue(no_expected.passed)

    def test_candidate_provider_builds_pending_setup_from_latest_closed_signal(self) -> None:
        candidate = build_current_v15_candidate()
        self.assertEqual(candidate.candidate_id, "signal_zone_0p5_pullback__fs_structure__1r")
        self.assertEqual(candidate.entry_model, "signal_zone_pullback")

        empty = pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])
        self.assertEqual(default_setup_provider(empty, "EURUSD", "H4", DryRunExecutorConfig()), [])

        frame = _pending_frame()
        old_signal = SimpleNamespace(fs_signal_index=0)
        latest_signal = _signal(signal_index=1)
        with mock.patch.object(
            dry_run_module,
            "detect_lp_force_strike_signals",
            return_value=[old_signal, latest_signal],
        ) as detector:
            setups = default_setup_provider(
                frame,
                "EURUSD",
                "H4",
                DryRunExecutorConfig(require_lp_pivot_before_fs_mother=False),
            )
        self.assertEqual(detector.call_args.kwargs["require_lp_pivot_before_fs_mother"], False)
        self.assertEqual(len(setups), 1)
        setup = setups[0]
        self.assertIsInstance(setup, TradeSetup)
        assert isinstance(setup, TradeSetup)
        self.assertEqual(setup.entry_index, 2)
        self.assertAlmostEqual(setup.entry_price, 1.15)
        self.assertAlmostEqual(setup.stop_price, 0.9)
        self.assertAlmostEqual(setup.target_price, 1.4)
        self.assertTrue(setup.metadata["pending_from_latest_closed_signal"])

    def test_pending_setup_builder_handles_supported_variants_and_skips_invalid_inputs(self) -> None:
        frame = _pending_frame(rows=15, signal_high=1.3, signal_low=1.0)
        candidate = build_current_v15_candidate()
        long_setup = build_pending_trade_setup(
            frame,
            _signal(signal_index=14, mother_index=13),
            candidate,
            symbol="EURUSD",
            timeframe="H4",
        )
        self.assertIsInstance(long_setup, TradeSetup)
        assert isinstance(long_setup, TradeSetup)
        self.assertGreater(long_setup.metadata["risk_atr"], 0)

        midpoint_candidate = TradeModelCandidate(
            candidate_id="midpoint",
            entry_model="signal_midpoint_pullback",
            stop_model="fs_structure",
            target_r=1.0,
        )
        short_setup = build_pending_trade_setup(
            frame,
            _signal(side="bearish", signal_index=14, mother_index=13),
            midpoint_candidate,
            symbol="EURUSD",
            timeframe="H4",
        )
        self.assertIsInstance(short_setup, TradeSetup)
        assert isinstance(short_setup, TradeSetup)
        self.assertEqual(short_setup.side, "short")
        self.assertAlmostEqual(short_setup.entry_price, 1.15)
        self.assertAlmostEqual(short_setup.stop_price, 1.3)
        self.assertAlmostEqual(short_setup.target_price, 1.0)

        skip_cases = [
            (
                "signal_index_out_of_range",
                frame,
                _signal(signal_index=99),
                candidate,
            ),
            (
                "unsupported_entry_model",
                frame,
                _signal(signal_index=14),
                TradeModelCandidate(
                    candidate_id="next_open",
                    entry_model="next_open",
                    stop_model="fs_structure",
                    target_r=1.0,
                ),
            ),
            (
                "unsupported_stop_model",
                frame,
                _signal(signal_index=14),
                TradeModelCandidate(
                    candidate_id="atr_stop",
                    entry_model="signal_zone_pullback",
                    entry_zone=0.5,
                    stop_model="fs_structure_max_atr",
                    target_r=1.0,
                ),
            ),
            (
                "invalid_entry_range",
                _pending_frame(rows=15, signal_high=1.0, signal_low=1.0),
                _signal(signal_index=14),
                candidate,
            ),
        ]
        for reason, case_frame, signal, case_candidate in skip_cases:
            with self.subTest(reason=reason):
                skipped = build_pending_trade_setup(
                    case_frame,
                    signal,
                    case_candidate,
                    symbol="EURUSD",
                    timeframe="H4",
                )
                self.assertIsInstance(skipped, SkippedTrade)
                assert isinstance(skipped, SkippedTrade)
                self.assertEqual(skipped.reason, reason)

    def test_config_helpers_are_deterministic(self) -> None:
        candidate = build_current_v15_candidate()
        self.assertEqual(candidate.candidate_id, "signal_zone_0p5_pullback__fs_structure__1r")
        self.assertEqual(candidate.entry_model, "signal_zone_pullback")

        safety = execution_safety_from_config(
            DryRunExecutorConfig(
                max_spread_points=12,
                max_lots_per_order=0.5,
                risk_bucket_scale=0.1,
                max_open_risk_pct=5,
                max_same_symbol_stack=2,
                max_concurrent_strategy_trades=3,
                strategy_magic=42,
            )
        )
        self.assertEqual(safety.max_spread_points, 12)
        self.assertEqual(safety.max_lots_per_order, 0.5)
        self.assertEqual(safety.max_open_risk_pct, 5)
        self.assertEqual(safety.max_same_symbol_stack, 2)
        self.assertEqual(safety.max_concurrent_strategy_trades, 3)
        self.assertEqual(safety.strategy_magic, 42)
        scaled_buckets = risk_buckets_from_config(DryRunExecutorConfig(risk_bucket_scale=0.1))
        self.assertAlmostEqual(scaled_buckets["H4"], 0.02)
        self.assertAlmostEqual(scaled_buckets["H8"], 0.02)
        self.assertAlmostEqual(scaled_buckets["H12"], 0.03)
        self.assertAlmostEqual(scaled_buckets["D1"], 0.03)
        self.assertAlmostEqual(scaled_buckets["W1"], 0.075)
        with self.assertRaisesRegex(ValueError, "risk_bucket_scale"):
            risk_buckets_from_config(DryRunExecutorConfig(risk_bucket_scale=0.0))

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.local.json"
            absolute_state = Path(tmpdir) / "absolute_state.json"
            config_path.write_text(
                json.dumps({"dry_run": {"symbols": ["EURUSD", "GBPUSD"], "state_path": str(absolute_state)}}),
                encoding="utf-8",
            )
            settings = load_dry_run_settings(config_path, env={})
            self.assertEqual(settings.executor.symbols, ("EURUSD", "GBPUSD"))
            self.assertEqual(settings.executor.state_path, str(absolute_state))

    def test_process_trade_setup_dry_run_logs_ready_rejected_failed_and_idempotent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DryRunExecutorConfig(
                journal_path=str(Path(tmpdir) / "journal.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                broker_timezone="UTC",
            )
            mt5 = FakeMT5()
            ready_client = FakeNotifierClient()
            ready_notifier = TelegramNotifier(
                TelegramConfig("token", "chat", dry_run=False),
                ready_client,
            )
            ready = process_trade_setup_dry_run(
                mt5,
                _setup(),
                config=config,
                state=DryRunExecutorState(),
                notifier=ready_notifier,
            )
            self.assertEqual(ready.status, "order_check_passed")
            self.assertIsNotNone(ready.order_check)
            self.assertIn(ready.signal_key, ready.state.order_checked_signal_keys)
            self.assertEqual(ready_client.calls, 1)
            self.assertIn("LPFS DRY RUN - BROKER CHECK", ready_client.payloads[0]["text"])
            rows = _journal_rows(Path(config.journal_path))
            self.assertEqual(rows[0]["event"], "signal_detected")
            self.assertIn("market_snapshot", [row["event"] for row in rows])
            self.assertIn("order_intent_created", [row["event"] for row in rows])
            self.assertIn("order_check_passed", [row["event"] for row in rows])

            scaled_config = replace_config_path(config, Path(tmpdir) / "journal_scaled.jsonl", risk_bucket_scale=0.1)
            scaled = process_trade_setup_dry_run(
                mt5,
                _setup(),
                config=scaled_config,
                state=DryRunExecutorState(),
            )
            self.assertEqual(scaled.status, "order_check_passed")
            scaled_rows = _journal_rows(Path(scaled_config.journal_path))
            intent_row = next(row for row in scaled_rows if row["event"] == "order_intent_created")
            intent = intent_row["decision"]["intent"]
            self.assertAlmostEqual(intent["target_risk_pct"], 0.02)
            self.assertAlmostEqual(intent["actual_risk_pct"], 0.02)
            self.assertAlmostEqual(intent["volume"], 0.04)

            duplicate = process_trade_setup_dry_run(mt5, _setup(), config=config, state=ready.state)
            self.assertEqual(duplicate.status, "already_checked")

            rejected_client = FakeNotifierClient()
            rejected_notifier = TelegramNotifier(
                TelegramConfig("token", "chat", dry_run=False),
                rejected_client,
            )
            rejected = process_trade_setup_dry_run(
                mt5,
                _setup(entry=1.1030, stop=1.0950, target=1.1100),
                config=config,
                state=DryRunExecutorState(),
                notifier=rejected_notifier,
            )
            self.assertEqual(rejected.status, "rejected")
            self.assertEqual(rejected_client.calls, 1)
            self.assertIn("LPFS DRY RUN - SETUP SKIPPED", rejected_client.payloads[0]["text"])

            mt5.order_check_result = SimpleNamespace(retcode=123, comment="check failed")
            failed = process_trade_setup_dry_run(
                mt5,
                _setup(),
                config=replace_config_path(config, Path(tmpdir) / "journal_failed.jsonl"),
                state=DryRunExecutorState(),
            )
            self.assertEqual(failed.status, "order_check_failed")

            processed_key = signal_key_for_setup(_setup())
            processed_duplicate = process_trade_setup_dry_run(
                mt5,
                _setup(),
                config=replace_config_path(config, Path(tmpdir) / "journal_processed_duplicate.jsonl"),
                state=DryRunExecutorState(processed_signal_keys=(processed_key,)),
            )
            self.assertEqual(processed_duplicate.state.processed_signal_keys, (processed_key,))

    def test_run_dry_run_cycle_processes_closed_frames_skips_and_saves_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DryRunExecutorConfig(
                symbols=("EURUSD",),
                timeframes=("H4",),
                journal_path=str(Path(tmpdir) / "journal.jsonl"),
                state_path=str(Path(tmpdir) / "state.json"),
                broker_timezone="UTC",
            )
            skipped = SkippedTrade(
                candidate_id="c",
                symbol="EURUSD",
                timeframe="H4",
                side="bullish",
                signal_index=2,
                signal_time_utc=pd.Timestamp("2026-01-01T00:00:00Z"),
                reason="entry_not_reached",
            )

            def provider(frame, symbol, timeframe, run_config):
                self.assertEqual(len(frame), 2)
                self.assertEqual((symbol, timeframe, run_config.timeframes), ("EURUSD", "H4", ("H4",)))
                return [skipped, _setup()]

            result = run_dry_run_cycle(FakeMT5(), config=config, state=DryRunExecutorState(), setup_provider=provider)

            self.assertEqual(result.frames_processed, 1)
            self.assertEqual(result.setups_checked, 1)
            self.assertEqual(result.setups_rejected, 1)
            self.assertTrue(Path(config.state_path).exists())
            self.assertIn("setup_skipped", [row["event"] for row in _journal_rows(Path(config.journal_path))])

            rejected_config = DryRunExecutorConfig(
                symbols=("EURUSD",),
                timeframes=("H4",),
                journal_path=str(Path(tmpdir) / "journal_rejected.jsonl"),
                state_path=str(Path(tmpdir) / "state_rejected.json"),
                broker_timezone="UTC",
            )
            rejected_result = run_dry_run_cycle(
                FakeMT5(),
                config=rejected_config,
                state=DryRunExecutorState(),
                setup_provider=lambda frame, symbol, timeframe, run_config: [
                    _setup(entry=1.1030, stop=1.0950, target=1.1100)
                ],
            )
            self.assertEqual(rejected_result.setups_checked, 0)
            self.assertEqual(rejected_result.setups_rejected, 1)

    def test_example_config_has_no_real_secrets(self) -> None:
        example_path = WORKSPACE_ROOT / "config.local.example.json"
        payload = example_path.read_text(encoding="utf-8")

        self.assertIn("YOUR_DEMO_MT5_LOGIN", payload)
        self.assertIn('"require_lp_pivot_before_fs_mother": true', payload)
        self.assertNotRegex(payload, r"\d{6,}:[A-Za-z0-9_-]{20,}")
        self.assertNotIn("secret", payload.lower())

    def test_append_market_snapshot_uses_non_secret_market_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            row = append_market_snapshot(
                Path(tmpdir) / "journal.jsonl",
                "EURUSD",
                "H4",
                market_snapshot_from_mt5(FakeMT5(), "EURUSD", broker_timezone="UTC"),
            )
            self.assertEqual(row["event"], "market_snapshot")
            self.assertEqual(row["symbol"], "EURUSD")
            self.assertEqual(row["timeframe"], "H4")
            self.assertIn("spread_points", row)


def _intent_for_request(order_type: str):
    from lp_force_strike_strategy_lab import MT5OrderIntent

    return MT5OrderIntent(
        signal_key="lpfs:EURUSD:H4:10:long",
        symbol="EURUSD",
        timeframe="H4",
        side="long",
        order_type=order_type,
        volume=0.1,
        entry_price=1.1,
        stop_loss=1.095,
        take_profit=1.105,
        target_risk_pct=0.2,
        actual_risk_pct=0.2,
        expiration_time_utc=pd.Timestamp("2026-01-02T04:00:00Z"),
        magic=131500,
        comment="LPFS H4 L 10",
        setup_id="setup",
        signal_time_utc=pd.Timestamp("2026-01-01T00:00:00Z"),
        max_entry_wait_bars=6,
        strategy_expiry_mode="bar_count",
        broker_backstop_expiration_time_utc=pd.Timestamp("2026-01-12T04:00:00Z"),
    )


def replace_config_path(
    config: DryRunExecutorConfig,
    journal_path: Path,
    *,
    risk_bucket_scale: float | None = None,
) -> DryRunExecutorConfig:
    return DryRunExecutorConfig(
        symbols=config.symbols,
        timeframes=config.timeframes,
        broker_timezone=config.broker_timezone,
        history_bars=config.history_bars,
        journal_path=str(journal_path),
        state_path=config.state_path,
        max_spread_points=config.max_spread_points,
        max_lots_per_order=config.max_lots_per_order,
        risk_bucket_scale=config.risk_bucket_scale if risk_bucket_scale is None else risk_bucket_scale,
        max_open_risk_pct=config.max_open_risk_pct,
        max_same_symbol_stack=config.max_same_symbol_stack,
        max_concurrent_strategy_trades=config.max_concurrent_strategy_trades,
        strategy_magic=config.strategy_magic,
        pivot_strength=config.pivot_strength,
        max_bars_from_lp_break=config.max_bars_from_lp_break,
        max_entry_wait_bars=config.max_entry_wait_bars,
    )


if __name__ == "__main__":
    unittest.main()
