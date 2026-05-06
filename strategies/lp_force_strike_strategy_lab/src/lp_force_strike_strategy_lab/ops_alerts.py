"""Operational alerts that do not touch MT5 or trading state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import getpass
import json
import platform
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from .dry_run_executor import DryRunSettings, append_audit_event, telegram_notifier_from_settings
from .live_executor import LiveSendSettings, load_live_send_settings
from .notifications import NotificationDelivery, format_trader_timestamp


DEFAULT_RUNTIME_LIVE_DIR = Path("data/live")
DEFAULT_LIVE_JOURNAL_NAME = "lpfs_live_journal.jsonl"


@dataclass(frozen=True)
class VpsStartupSnapshot:
    """Small Windows/runtime snapshot for a VPS boot alert."""

    detected_at_utc: str
    hostname: str
    user: str
    boot_time_utc: str = ""
    restart_event_time_utc: str = ""
    restart_event_id: int | None = None
    restart_event_provider: str = ""
    restart_reason: str = ""
    restart_message_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_at_utc": self.detected_at_utc,
            "hostname": self.hostname,
            "user": self.user,
            "boot_time_utc": self.boot_time_utc,
            "restart_event_time_utc": self.restart_event_time_utc,
            "restart_event_id": self.restart_event_id,
            "restart_event_provider": self.restart_event_provider,
            "restart_reason": self.restart_reason,
            "restart_message_summary": self.restart_message_summary,
        }


def build_vps_startup_message(
    *,
    instance_label: str,
    runner_task_name: str,
    runtime_root: str,
    journal_path: str | Path,
    snapshot: VpsStartupSnapshot,
) -> str:
    """Render the boot alert sent before the MT5-dependent runner starts."""

    label = instance_label.strip() or "LPFS LIVE"
    lines = [
        f"{label} | VPS STARTED",
        f"Host: {snapshot.hostname or 'n/a'} | User: {snapshot.user or 'n/a'}",
        f"Detected: {_format_timestamp(snapshot.detected_at_utc)}",
    ]
    if snapshot.boot_time_utc:
        lines.append(f"Boot: {_format_timestamp(snapshot.boot_time_utc)}")
    if snapshot.restart_event_time_utc or snapshot.restart_event_id is not None:
        event_bits = []
        if snapshot.restart_event_time_utc:
            event_bits.append(_format_timestamp(snapshot.restart_event_time_utc))
        if snapshot.restart_event_id is not None:
            event_bits.append(f"Event {snapshot.restart_event_id}")
        lines.append(f"Last restart event: {' | '.join(event_bits)}")
    reason = snapshot.restart_reason or snapshot.restart_message_summary
    if reason:
        lines.append(f"Reason: {_trim(reason, 180)}")
    lines.extend(
        [
            f"Runner task: {runner_task_name or 'n/a'}",
            f"Runtime: {runtime_root or 'n/a'}",
            f"Journal: {_trim_path(journal_path, 72)}",
            "Action: confirm MT5 terminal and runner heartbeat after RDP/logon.",
        ]
    )
    return "\n".join(lines)


def send_vps_startup_alert(
    *,
    config_path: str | Path,
    runtime_root: str | Path | None = None,
    runtime_journal_file_name: str = DEFAULT_LIVE_JOURNAL_NAME,
    instance_label: str = "LPFS LIVE",
    runner_task_name: str = "LPFS_Live",
    max_attempts: int = 1,
    retry_seconds: float = 30.0,
    snapshot_provider: Callable[[], VpsStartupSnapshot] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Send a best-effort Telegram boot alert and journal the final outcome."""

    settings = load_live_send_settings(config_path)
    journal_path = _journal_path(settings, runtime_root, runtime_journal_file_name)
    snapshot = snapshot_provider() if snapshot_provider is not None else collect_vps_startup_snapshot()
    message = build_vps_startup_message(
        instance_label=instance_label,
        runner_task_name=runner_task_name,
        runtime_root="" if runtime_root is None else str(runtime_root),
        journal_path=journal_path,
        snapshot=snapshot,
    )
    notifier, warning = telegram_notifier_from_settings(
        DryRunSettings(local=settings.local, executor=settings.executor)  # type: ignore[arg-type]
    )

    attempts = 0
    delivery: NotificationDelivery | None = None
    if notifier is not None:
        max_attempts = max(1, int(max_attempts))
        for attempt_index in range(max_attempts):
            attempts = attempt_index + 1
            delivery = notifier.send_message(message)
            if delivery.sent or delivery.status == "dry_run":
                break
            if attempts < max_attempts:
                sleep(max(0.0, float(retry_seconds)))

    row = append_audit_event(
        journal_path,
        "vps_startup_alert",
        instance_label=instance_label,
        runner_task_name=runner_task_name,
        runtime_root="" if runtime_root is None else str(runtime_root),
        notification=message,
        notification_delivery=None if delivery is None else delivery.to_dict(),
        notification_warning=warning,
        delivery_attempts=attempts,
        startup_snapshot=snapshot.to_dict(),
    )
    return row


def collect_vps_startup_snapshot() -> VpsStartupSnapshot:
    """Collect boot/restart evidence from Windows if available."""

    detected_at = datetime.now(timezone.utc).isoformat()
    boot_time = _windows_last_boot_time_utc()
    event = _windows_last_restart_event()
    return VpsStartupSnapshot(
        detected_at_utc=detected_at,
        hostname=platform.node(),
        user=_current_user(),
        boot_time_utc=boot_time,
        restart_event_time_utc=str(event.get("time_created_utc") or ""),
        restart_event_id=_optional_int(event.get("id")),
        restart_event_provider=str(event.get("provider") or ""),
        restart_reason=_restart_reason_from_message(str(event.get("message") or "")),
        restart_message_summary=_message_summary(str(event.get("message") or "")),
    )


def _journal_path(settings: LiveSendSettings, runtime_root: str | Path | None, journal_file_name: str) -> Path:
    if runtime_root in (None, ""):
        return Path(settings.executor.journal_path)
    return Path(runtime_root) / DEFAULT_RUNTIME_LIVE_DIR / (journal_file_name or DEFAULT_LIVE_JOURNAL_NAME)


def _current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _windows_last_boot_time_utc() -> str:
    payload = _run_powershell_json(
        """
        $os = Get-CimInstance Win32_OperatingSystem
        [pscustomobject]@{
            last_boot_up_time_utc = $os.LastBootUpTime.ToUniversalTime().ToString("o")
        } | ConvertTo-Json -Compress
        """
    )
    if isinstance(payload, dict):
        return str(payload.get("last_boot_up_time_utc") or "")
    return ""


def _windows_last_restart_event() -> dict[str, Any]:
    payload = _run_powershell_json(
        """
        $event = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1074,6005,6006,6008,41} -MaxEvents 1
        if ($null -ne $event) {
            [pscustomobject]@{
                time_created_utc = $event.TimeCreated.ToUniversalTime().ToString("o")
                id = $event.Id
                provider = $event.ProviderName
                message = $event.Message
            } | ConvertTo-Json -Compress
        }
        """
    )
    return payload if isinstance(payload, dict) else {}


def _run_powershell_json(script: str) -> Any:
    if platform.system().lower() != "windows":
        return {}
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    text = completed.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _restart_reason_from_message(message: str) -> str:
    interesting = []
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if "reason" in lower or "operating system:" in lower or "shutdown type" in lower:
            interesting.append(stripped)
    return " | ".join(interesting[:3])


def _message_summary(message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return " | ".join(lines[:2])


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_timestamp(value: str) -> str:
    formatted = format_trader_timestamp(value)
    return value if formatted == "n/a" and value else formatted


def _trim(value: object, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."


def _trim_path(value: str | Path, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    parts = text.replace("\\", "/").split("/")
    if len(parts) >= 2:
        suffix = "/".join(parts[-2:])
        if len(suffix) + 4 <= max_length:
            return "..." + "/" + suffix
    return _trim(text, max_length)
