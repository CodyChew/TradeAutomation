# LPFS Start Here

Last updated: 2026-05-07 after adding the isolated native MQL5 EA migration
workspace, Python parity fixture, and tester-only operator docs.

This is the canonical first-read file for future AI agents taking over the
LP + Force Strike project. Use it to orient yourself, then verify current live
state from MT5, the ignored runtime files, and the JSONL journal before making
operational decisions.

## Current Status

- Strategy baseline: V13 mechanics + V15 risk buckets + V22 LP/FS separation.
- FTMO live/default bucket: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- ICMarketsSC-MT5-2 analysis bucket: H4/H8 `0.25%`, H12/D1 `0.30%`,
  W1 `0.75%`.
- IC local validation status: scale-2 order-check passed for the current local
  signals; one local smoke live-send placed `AUDCHF H8` ticket `4419969921`,
  the user manually canceled it, and broker/local smoke state returned to `0`
  pending orders and `0` positions.
- IC VPS live status: dedicated host `EC2AMAZ-DT73P0T` is reachable through
  `lpfs-ic-vps`, MT5 is logged into `ICMarketsSC-MT5-2`, all `28` symbols are
  available, the IC runtime kill switch is clear, one VPS live-send smoke cycle
  completed, and continuous task `LPFS_IC_Live` is installed/running with its
  own runtime state, journal, heartbeat, logs, Telegram channel, magic
  `231500`, and broker comment prefix `LPFSIC`.
- VPS boot alert status: FTMO uses startup task `LPFS_FTMO_Startup_Alert`; IC
  uses startup task `LPFS_IC_Startup_Alert`. These tasks send Telegram
  `VPS STARTED` cards and journal `vps_startup_alert` rows after Windows boot,
  without importing MT5 or touching orders/state.
- Required LP/FS rule: selected LP pivot must be before the Force Strike mother
  bar (`lp_pivot_index < fs_mother_index`).
- Execution state: guarded MT5 live-send path exists and can place real orders
  only when ignored local config explicitly enables live send.
- EA migration state: native MQL5 tester-only scaffold exists under
  `mql5/lpfs_ea/`. MetaEditor compile and MT5 tester load/config smoke passed;
  full-result smoke is pending until single-chart smoke mode and new-bar gating
  are added. Python remains canonical.
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
7. `docs/lpfs_icmarkets_vps_runbook.md` before provisioning or deploying the
   IC Markets production runner.
8. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before changing execution or notification code.
9. `docs/lpfs_new_mt5_account_validation.md` before validating another MT5
   account or broker feed.
10. `docs/ea_migration.html` and `mql5/lpfs_ea/README.md` before continuing
   native MQL5 EA or Strategy Tester work.

## Source-Of-Truth Matrix

| Topic | Source of truth | Notes |
| --- | --- | --- |
| Current strategy rules | `docs/strategy.html` and tested Python modules | TradingView is visual-only. |
| Research history | `docs/index.html`, version pages, and LPFS `PROJECT_STATE.md` | V1-V22 pages are audit history; V13/V15/V22 feed the current baseline. |
| Live broker state | MT5 on the VPS | Do not infer open exposure from Telegram alone. |
| Live runtime state | `C:\TradeAutomationRuntime\data\live` on the VPS | Contains state, journal, heartbeat, logs, and kill switch. |
| VPS restart awareness | Startup alert tasks plus Windows System event log | `VPS STARTED` Telegram means Windows booted; MT5/runner still need heartbeat confirmation. |
| Remote VPS access | `docs/lpfs_lightsail_vps_runbook.md` | Tailscale + OpenSSH is preferred over public SSH/RDP exposure. |
| Account and secrets | ignored `config.local.json` and local OS/user secrets | Never commit MT5 passwords, Telegram tokens, SSH private keys, or account credentials. |
| IC account validation | `docs/account_validation.html`, `docs/lpfs_new_mt5_account_validation.md`, and `config.lpfs_new_mt5_account.example.json` | Local-only validation and smoke testing; do not touch VPS live account. |
| IC production setup | `docs/lpfs_icmarkets_vps_runbook.md`, `config.lpfs_icmarkets_raw_spread.example.json`, and `scripts/Get-LpfsDualVpsStatus.ps1` | Separate VPS/runtime/task/Telegram lane for IC; FTMO remains untouched. |
| Native EA migration | `docs/ea_migration.html`, `mql5/lpfs_ea/README.md`, and `mql5/lpfs_ea/Experts/LPFS/LPFS_EA.mq5` | Tester-only v1; do not attach to production live charts. |
| Dashboard HTML | builder scripts in `scripts/` | Edit builders, then regenerate HTML; do not make HTML-only dashboard changes. |

## Environment Boundaries

- Local development environment:
  `C:\Users\chewc\OneDrive\Desktop\TradeAutomation`.
- VPS production checkout: `C:\TradeAutomation`.
- VPS production runtime root: `C:\TradeAutomationRuntime`.
- VPS startup alert task: `LPFS_FTMO_Startup_Alert`.
- Local SSH alias: `lpfs-vps`.
- VPS host: `EC2AMAZ-ON6FOF2`.
- VPS Tailscale IP: `100.115.34.38`.
- Local PC Tailscale IP: `100.105.200.52`.
- VPS SSH user: `Administrator`.
- Local SSH key: `~\.ssh\lpfs_vps_ed25519`.

Local edits do not affect the VPS until they are committed, pushed, pulled on
the VPS, and the production task is intentionally restarted. VPS runtime files
do not belong in git.

IC production uses a separate environment boundary: SSH alias `lpfs-ic-vps`,
host `EC2AMAZ-DT73P0T`, Tailscale IP `100.98.12.113`, scheduled task
`LPFS_IC_Live`, startup alert task `LPFS_IC_Startup_Alert`, runtime root
`C:\TradeAutomationRuntimeIC`, ignored config
`config.lpfs_icmarkets_raw_spread.local.json`, magic `231500`, broker comment
prefix `LPFSIC`, and a separate Telegram channel. It is a live production lane,
not a staging-only host.

## First Commands Before Touching The VPS

Run these from the local repo before drawing any VPS conclusion:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -StateFileName lpfs_ic_live_state.json -JournalFileName lpfs_ic_live_journal.jsonl -HeartbeatFileName lpfs_ic_live_heartbeat.json -LogFilter 'lpfs_ic_live_*.log' -JournalLines 40 -LogLines 80"
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

If the command target is `C:\TradeAutomation` or
`C:\TradeAutomationRuntime` / `C:\TradeAutomationRuntimeIC`, treat it as
production-adjacent.

## Live-Run Safety Rules

- Do not run a local LPFS live runner while `LPFS_Live` is active on the VPS
  unless the user explicitly approves a separate local-account smoke test with
  its own ignored config, state, journal, and reconciliation plan.
- Do not run a manual IC live runner while `LPFS_IC_Live` is active on the IC
  VPS; use the kill switch/status packet first.
- Do not attach the native MQL5 EA to FTMO or IC live charts during v1. It is
  Strategy Tester-only until a separate demo/live EA deployment plan is
  approved.
- Do not edit live state, journal rows, MT5 orders, MT5 positions, or deal
  history unless the user explicitly approves a separate operator plan.
- Use the kill switch before approved deploy, restart, or emergency pause work.
- Verify MT5 broker state before assuming a pending order, position, fill,
  close, cancellation, or missed trade.
- Telegram is an alert channel only; the JSONL journal and MT5 are the audit
  sources.
- For docs-only changes, no VPS runner restart is required.
- A `VPS STARTED` Telegram card is an operating-system alert, not proof the
  trading loop is healthy. Always follow it with heartbeat, journal, and MT5
  broker-state checks.

## Resume Prompts

Use one of these prompts to restart cleanly:

- Local docs/research: `Read SESSION_HANDOFF.md and strategies/lp_force_strike_strategy_lab/START_HERE.md, then continue the LPFS docs/research task from the current git state.`
- VPS read-only audit: `Read SESSION_HANDOFF.md and START_HERE.md, then run the lpfs-vps identity, git status, and Get-LpfsLiveStatus checks before making any operational conclusion.`
- Live deployment planning: `Read START_HERE.md, docs/live_ops.html, and docs/lpfs_lightsail_vps_runbook.md, then produce a kill-switch-first VPS deploy plan before changing production.`
- Second MT5 account planning: `Read START_HERE.md and docs/mt5_execution_contract.md, then plan a separate config/runtime/account boundary for another MT5 account without touching current VPS state.`
- Second MT5 account validation: `Read START_HERE.md and docs/lpfs_new_mt5_account_validation.md, then audit the locally logged-in MT5 account before pulling data or running dry-run.`
- IC VPS audit: `Read START_HERE.md and docs/lpfs_icmarkets_vps_runbook.md, then run Get-LpfsDualVpsStatus.ps1 and verify LPFS_Live and LPFS_IC_Live from MT5/runtime state before making operational changes.`
- EA migration: `Read START_HERE.md, docs/ea_migration.html, and mql5/lpfs_ea/README.md, then continue native MQL5 tester-only work without touching VPS runtime, live configs, live journals, or broker orders.`
