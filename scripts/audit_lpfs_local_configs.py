"""Audit ignored LPFS local config shape without printing secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = (
    ROOT / "concepts" / "lp_levels_lab" / "src",
    ROOT / "concepts" / "force_strike_pattern_lab" / "src",
    ROOT / "shared" / "backtest_engine_lab" / "src",
    ROOT / "strategies" / "lp_force_strike_strategy_lab" / "src",
)
for src_root in SRC_ROOTS:
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

from lp_force_strike_strategy_lab import load_live_send_settings, live_risk_buckets_from_config  # noqa: E402


DEFAULT_CONFIG_PATHS = (
    "config.local.json",
    "config.lpfs_icmarkets_raw_spread.local.json",
    "config.lpfs_icmarkets_raw_spread.live_smoke.local.json",
)


def audit_config(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "sha256": "",
        "status": "missing",
        "findings": ["config_missing"],
    }
    if not path.exists():
        return row

    row["sha256"] = _sha256_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        row.update(
            {
                "status": "invalid",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "findings": ["config_json_parse_error"],
            }
        )
        return row

    if not isinstance(payload, dict):
        row.update({"status": "invalid", "findings": ["config_root_not_object"]})
        return row

    mt5 = _object(payload.get("mt5"))
    telegram = _object(payload.get("telegram"))
    live_send = _object(payload.get("live_send"))
    live_enabled = _optional_bool(live_send.get("live_send_enabled"))
    recovery_mode = str(live_send.get("market_recovery_mode") or "")
    findings: list[str] = []

    if live_enabled:
        findings.append("live_send_enabled_true_review_required")
    if recovery_mode and recovery_mode != "disabled":
        findings.append("market_recovery_not_disabled")
    if live_send.get("execution_mode") == "LIVE_SEND" and not live_enabled:
        findings.append("live_send_mode_but_disabled")
    if live_enabled and not str(live_send.get("real_money_ack") or "").strip():
        findings.append("live_send_enabled_without_ack")
    if live_enabled and not str(mt5.get("expected_login") or "").strip():
        findings.append("missing_expected_login")
    if live_enabled and not str(mt5.get("expected_server") or "").strip():
        findings.append("missing_expected_server")
    if _optional_bool(telegram.get("enabled")) and not str(telegram.get("bot_token") or "").strip():
        findings.append("telegram_enabled_without_token")
    if _optional_bool(telegram.get("enabled")) and not str(telegram.get("chat_id") or "").strip():
        findings.append("telegram_enabled_without_chat_id")

    settings_fields = _load_effective_settings(path)
    if settings_fields.get("settings_load_status") != "ok":
        findings.append("settings_load_error")

    row.update(
        {
            "status": "review" if findings else "ok",
            "findings": findings,
            "execution_mode": str(live_send.get("execution_mode") or ""),
            "live_send_enabled": live_enabled,
            "market_recovery_mode": recovery_mode,
            "expected_login_set": bool(str(mt5.get("expected_login") or "").strip()),
            "expected_server_set": bool(str(mt5.get("expected_server") or "").strip()),
            "mt5_login_set": bool(str(mt5.get("login") or "").strip()),
            "mt5_password_set": bool(str(mt5.get("password") or "").strip()),
            "telegram_enabled": _optional_bool(telegram.get("enabled")),
            "telegram_token_set": bool(str(telegram.get("bot_token") or "").strip()),
            "telegram_chat_id_set": bool(str(telegram.get("chat_id") or "").strip()),
            "symbols_count": _sequence_count(live_send.get("symbols")),
            "timeframes_count": _sequence_count(live_send.get("timeframes")),
            "strategy_magic": _optional_int(live_send.get("strategy_magic")),
            "order_comment_prefix_set": bool(str(live_send.get("order_comment_prefix") or "").strip()),
            "risk_bucket_scale_set": live_send.get("risk_bucket_scale") is not None,
            "risk_bucket_scale": _optional_float(live_send.get("risk_bucket_scale")),
            "max_risk_pct_per_trade_set": live_send.get("max_risk_pct_per_trade") is not None,
            "max_risk_pct_per_trade": _optional_float(live_send.get("max_risk_pct_per_trade")),
            "max_open_risk_pct_set": live_send.get("max_open_risk_pct") is not None,
            "max_open_risk_pct": _optional_float(live_send.get("max_open_risk_pct")),
            **settings_fields,
        }
    )
    return row


def render_text(rows: list[dict[str, Any]]) -> str:
    lines = [
        "LPFS local config audit (redacted)",
        "No passwords, MT5 account numbers, server names, Telegram tokens, or chat IDs are printed.",
        "",
    ]
    for row in rows:
        lines.append(f"path={row['path']}")
        lines.append(f"  exists={str(row.get('exists')).lower()} status={row.get('status')} sha256={row.get('sha256', '')}")
        if row.get("error_type"):
            lines.append(f"  error={row.get('error_type')}: {row.get('error')}")
        for key in (
            "execution_mode",
            "live_send_enabled",
            "market_recovery_mode",
            "expected_login_set",
            "expected_server_set",
            "mt5_login_set",
            "mt5_password_set",
            "telegram_enabled",
            "telegram_token_set",
            "telegram_chat_id_set",
            "symbols_count",
            "timeframes_count",
            "strategy_magic",
            "order_comment_prefix_set",
            "risk_bucket_scale_set",
            "risk_bucket_scale",
            "max_risk_pct_per_trade_set",
            "max_risk_pct_per_trade",
            "max_open_risk_pct_set",
            "max_open_risk_pct",
            "settings_load_status",
            "effective_risk_buckets_pct",
        ):
            if key in row:
                lines.append(f"  {key}={row.get(key)}")
        findings = row.get("findings") or []
        lines.append(f"  findings={','.join(findings) if findings else 'none'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="Local config path to audit. Defaults to known ignored LPFS local config names.",
    )
    parser.add_argument("--json", action="store_true", help="Emit redacted JSON instead of text.")
    parser.add_argument("--fail-on-review", action="store_true", help="Return 1 when any config has review findings.")
    args = parser.parse_args(argv)

    config_paths = args.config or list(DEFAULT_CONFIG_PATHS)
    rows = [audit_config(Path(raw)) for raw in config_paths]
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print(render_text(rows), end="")
    if args.fail_on_review and any((row.get("findings") or []) for row in rows):
        return 1
    return 0


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off", ""}:
            return False
    return None


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _load_effective_settings(path: Path) -> dict[str, Any]:
    try:
        settings = load_live_send_settings(path, env={})
        return {
            "settings_load_status": "ok",
            "effective_risk_buckets_pct": live_risk_buckets_from_config(settings.executor),
        }
    except Exception as exc:
        return {
            "settings_load_status": "error",
            "settings_load_error_type": type(exc).__name__,
        }


def _sequence_count(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.strip() else 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
