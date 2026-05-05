# LPFS Start Here

Last updated: 2026-05-05 after the handoff-first documentation cleanup.

This is the canonical first-read file for future AI agents taking over the
LP + Force Strike project. Use it to orient yourself, then verify current live
state from MT5, the ignored runtime files, and the JSONL journal before making
operational decisions.

## Current Status

- Strategy baseline: V13 mechanics + V15 risk buckets + V22 LP/FS separation.
- Required LP/FS rule: selected LP pivot must be before the Force Strike mother
  bar (`lp_pivot_index < fs_mother_index`).
- Execution state: guarded MT5 live-send path exists and can place real orders
  only when ignored local config explicitly enables live send.
- Production host: Amazon Lightsail Windows VPS.
- Preferred remote access: Tailscale + OpenSSH using local alias `lpfs-vps`.
- Broker truth: MT5 orders, positions, order history, and deal history.
- Runtime truth: `C:\TradeAutomationRuntime\data\live` on the VPS.
- Local repo truth: tracked code and docs in
  `C:\Users\chewc\OneDrive\Desktop\TradeAutomation`.

## Read Order

1. `SESSION_HANDOFF.md` for the latest operational snapshot.
2. This file for the LPFS recovery map and environment boundaries.
3. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for detailed
   strategy history and current live/research assumptions.
4. `docs/strategy.html` for the current strategy contract.
5. `docs/live_ops.html` for live-run behavior, gates, reconciliation, status,
   and operator commands.
6. `docs/lpfs_lightsail_vps_runbook.md` before any VPS maintenance or remote
   access work.
7. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before changing execution or notification code.

## Source-Of-Truth Matrix

| Topic | Source of truth | Notes |
| --- | --- | --- |
| Current strategy rules | `docs/strategy.html` and tested Python modules | TradingView is visual-only. |
| Research history | `docs/index.html`, version pages, and LPFS `PROJECT_STATE.md` | V1-V22 pages are audit history; V13/V15/V22 feed the current baseline. |
| Live broker state | MT5 on the VPS | Do not infer open exposure from Telegram alone. |
| Live runtime state | `C:\TradeAutomationRuntime\data\live` on the VPS | Contains state, journal, heartbeat, logs, and kill switch. |
| Remote VPS access | `docs/lpfs_lightsail_vps_runbook.md` | Tailscale + OpenSSH is preferred over public SSH/RDP exposure. |
| Account and secrets | ignored `config.local.json` and local OS/user secrets | Never commit MT5 passwords, Telegram tokens, SSH private keys, or account credentials. |
| Dashboard HTML | builder scripts in `scripts/` | Edit builders, then regenerate HTML; do not make HTML-only dashboard changes. |

## Environment Boundaries

- Local development environment:
  `C:\Users\chewc\OneDrive\Desktop\TradeAutomation`.
- VPS production checkout: `C:\TradeAutomation`.
- VPS production runtime root: `C:\TradeAutomationRuntime`.
- Local SSH alias: `lpfs-vps`.
- VPS host: `EC2AMAZ-ON6FOF2`.
- VPS Tailscale IP: `100.115.34.38`.
- Local PC Tailscale IP: `100.105.200.52`.
- VPS SSH user: `Administrator`.
- Local SSH key: `~\.ssh\lpfs_vps_ed25519`.

Local edits do not affect the VPS until they are committed, pushed, pulled on
the VPS, and the production task is intentionally restarted. VPS runtime files
do not belong in git.

## First Commands Before Touching The VPS

Run these from the local repo before drawing any VPS conclusion:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
```

If the command target is `C:\TradeAutomation` or
`C:\TradeAutomationRuntime`, treat it as production-adjacent.

## Live-Run Safety Rules

- Do not run a local LPFS live runner while `LPFS_Live` is active on the VPS.
- Do not edit live state, journal rows, MT5 orders, MT5 positions, or deal
  history unless the user explicitly approves a separate operator plan.
- Use the kill switch before approved deploy, restart, or emergency pause work.
- Verify MT5 broker state before assuming a pending order, position, fill,
  close, cancellation, or missed trade.
- Telegram is an alert channel only; the JSONL journal and MT5 are the audit
  sources.
- For docs-only changes, no VPS runner restart is required.

## Resume Prompts

Use one of these prompts to restart cleanly:

- Local docs/research: `Read SESSION_HANDOFF.md and strategies/lp_force_strike_strategy_lab/START_HERE.md, then continue the LPFS docs/research task from the current git state.`
- VPS read-only audit: `Read SESSION_HANDOFF.md and START_HERE.md, then run the lpfs-vps identity, git status, and Get-LpfsLiveStatus checks before making any operational conclusion.`
- Live deployment planning: `Read START_HERE.md, docs/live_ops.html, and docs/lpfs_lightsail_vps_runbook.md, then produce a kill-switch-first VPS deploy plan before changing production.`
- Second MT5 account planning: `Read START_HERE.md and docs/mt5_execution_contract.md, then plan a separate config/runtime/account boundary for another MT5 account without touching current VPS state.`
