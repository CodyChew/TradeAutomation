# LPFS Start Here

Last updated: 2026-06-07 ICT after LPFS minimum-safety resumption.

This is the canonical first-read file for future AI agents taking over the
LP + Force Strike project. Use it to orient yourself, then verify current live
state from MT5, the ignored runtime files, and the JSONL journal before making
operational decisions.

## Current Status

- Stage 5 minimum-safety resumption completed on 2026-06-07 ICT. FTMO
  `LPFS_Live` was resumed first and IC `LPFS_IC_Live` was resumed only after
  FTMO post-start evidence was clean. Accepted final proof recorded both tasks
  running, kill switches clear, pending broker orders `0`, unchanged active
  positions, and recovery disabled. Use the dual VPS status packet for current
  process, heartbeat, config, and broker truth.
- Read `../../docs/lpfs_c01_live_safety_release.md` before any LPFS operation.
  C-01 fixed the historical MT5 epoch shift through `Europe/Helsinki` and
  remains relevant for normalization before strategy analysis. Do not rerun
  reconciliation, run a canary, start a duplicate runner, or manually mutate
  broker exposure.
- FTMO-only Stage 1 passed point-in-time after exact reviewed SHA
  `3dd1895ca5300d448e4d100095b294e78679a6b9` was pulled. One contained
  `--reconcile-only` invocation migrated FTMO state to schema v2 with one
  deterministic `clean_noop_migration` receipt, completion row, CLI completion
  row, and reconciliation heartbeat. Broker pending orders stayed `0`; the
  same `3` FTMO positions remained. The archived packet and SHA-256 are in
  `../../SESSION_HANDOFF.md`. At that historical checkpoint FTMO was
  contained and IC was not accessed; Stage 5 later resumed FTMO first and IC
  second.
- Historical IC-only Stage 3 passed at exact reviewed SHA
  `b02a3cb92a05e771782c7a9ca4e4339c9452969a`. Its archived packet and
  SHA-256 are in `../../SESSION_HANDOFF.md`. Stage 5 later resumed FTMO first
  and IC second.
- The local C-01 branch adds direct UTC parsing, code-enforced
  `market_recovery_mode="disabled"`, fail-closed broker reads, atomic v2 state
  with a legacy-loader tripwire, proof-backed isolated reconciliation, and
  immutable evidence normalization. The normalizer classifies every historical
  `*_utc` leaf and refuses strategy-analysis safety when any timestamp path is
  unresolved. It does not change LPFS heuristics.
- For C-01 only, deploy and review `FTMO` first, then `IC`. Older `IC`-first
  instructions apply to the historical watchdog rollout, not this release.
- Strategy baseline: V13 mechanics + V15 risk buckets + V22 LP/FS separation.
- FTMO live/default bucket: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- ICMarketsSC-MT5-2 analysis bucket: H4/H8 `0.25%`, H12/D1 `0.30%`,
  W1 `0.75%`.
- IC local validation status: scale-2 order-check passed for the current local
  signals; one local smoke live-send placed `AUDCHF H8` ticket `4419969921`,
  the user manually canceled it, and broker/local smoke state returned to `0`
  pending orders and `0` positions.
- Historical IC VPS promoted-state note: dedicated host `EC2AMAZ-DT73P0T` is
  reachable through `lpfs-ic-vps`; historical promotion evidence recorded MT5
  on `ICMarketsSC-MT5-2`, all `28` symbols available, one VPS live-send smoke
  cycle completed, and continuous task `LPFS_IC_Live` installed/running with
  its own runtime state, journal, heartbeat, logs, Telegram channel, magic
  `231500`, and broker comment prefix `LPFSIC`. Do not treat this as current IC
  truth. Current truth comes from accepted Stage 5 resumed evidence and the
  latest dual VPS status packet.
- Watchdog hardening deploy: documentation PR `#1` squash-merged as `9dcfafc`
  and watchdog PR `#2` squash-merged as `3657323`. Both VPSes pulled
  `3657323` with deliberate kill-switch-first restarts on 2026-05-31 ICT, IC
  first as the canary. Final packet:
  `reports/live_ops/lpfs_dual_vps_status_20260531_193551.md`. See
  `SESSION_HANDOFF.md` for continuity and reconciliation details.
- Live sizing policy source: `configs/live_policy_ledger.csv`. It records FTMO
  scale `0.05`, historical IC scale `2.0`, and the active IC future-order
  scale `1.0` policy. Use the ledger when segmenting live performance; do not
  infer a strategy change from a sizing-policy epoch change.
- IC scale-down boundary: the IC policy change affects only future live-send
  order sizing after `2026-05-30T17:14:27Z` activation. It did not modify FTMO,
  `dry_run`, live state, journals, existing pending orders, or active
  positions.
- Diagnostic policy-epoch note: sparse lifecycle diagnostics already preserve
  `diagnostics.strategy.risk_bucket_scale`, and flattened report rows expose
  `diagnostic_strategy_risk_bucket_scale`. The current offline report builder
  does not yet assign ledger `policy_id` or automatically group comparisons by
  sizing epoch. Segment IC rows explicitly using the ledger activation time and
  diagnostic scale field until that reporting enhancement is implemented.
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
- Rollover spread state: a 2026-05-08 audit found IC/FTMO divergence on
  `AUDNZD H4/H8` around daily rollover and a separate 05:00-06:00 SGT
  spread-wait placement lag. The spread gate and retry behavior matched the
  intended design; no patch is recommended unless the pattern repeats or
  materially harms PnL.
- Zero-spread quote state: a 2026-05-12 audit found IC skipped a `EURUSD H4
  SHORT` at the 01:00 SGT run because the local execution contract treated
  `bid == ask` as invalid. FTMO placed the matching order. The corrected
  contract allows equal bid/ask as valid zero spread, keeps spread gates and
  MT5 `order_check` in place, and rejects only inverted quotes where bid is
  greater than ask.
- Bid/Ask fill-realism state: a 2026-05-09 IC `EURCHF H12` audit confirmed
  that a Bid-only candle low below a buy-limit entry does not prove MT5 should
  fill. Live `BUY_LIMIT` fills require Ask at or below entry. IC tick data
  supported the later live fill; 10-year true tick Bid/Ask was not available
  from the local IC terminal, while 10-year candles and M1 spread fields were.
- FTMO challenge-profile state: research-only frontier run
  `reports/strategies/lpfs_ftmo_challenge_frontier/20260508_112959` selected
  H4/H8 `0.20%`, H12/D1 `0.20%`, W1 `0.65%` as the fresh 100k Challenge
  profile and H4/H8 `0.20%`, H12/D1 `0.25%`, W1 `0.55%` as the
  aggressive/funded profile. This did not change live config or VPS runtime.
- Weekly performance state: latest packet
  `reports/live_ops/lpfs_weekly_performance/20260530_150637` covers the
  completed week from 2026-05-25 05:00 SGT to 2026-05-30 05:00 SGT, but the
  generated dashboard has an FTMO fetch-timeout caveat. Use
  `reports/live_ops/lpfs_weekly_performance/20260530_150637/local_snapshot_review.md`
  for the authoritative checkpoint read. FTMO was `-0.56R` at p32.4; IC was
  `-3.63R` at p12.5. H4 was the current cross-lane weak bucket, while H8 was
  not weak this week. This weekly view alone does not approve a live strategy
  change.
- First-month monthly evidence state: review
  `docs/lpfs_monthly_evidence_20260530.md`.
  Against the accepted V22 separated commission-adjusted monthly backtest
  distribution, FTMO May 2026 live closed trades are `-15.09R` over 71 trades
  at monthly p1.67, and IC is `-13.47R` over 61 trades at monthly p0.83. The
  10-year backtest had losing months, so one losing month is not impossible,
  but this live month is near the lower historical tail. Escalate to offline
  cause-attribution research now; do not change live strategy rules, sizing,
  execution, config defaults, state, journals, MT5 orders, or MT5 positions
  from this evidence alone.
- Reporting safety state: on 2026-05-23, a weekly-report scan of production
  journals using unsafe file-open semantics likely stopped both live runners.
  Both runners were restarted and verified healthy in
  `reports/live_ops/lpfs_dual_vps_status_20260523_140154.md`. Remote live
  journal/state reads must use bounded status scripts or `FileShare.ReadWrite`
  shared reads, followed by a fresh dual-VPS status packet.
- Compact-summary snapshot state: use
  `scripts/collect_lpfs_live_journal_snapshots.py` for routine exact `64 MiB`
  shared-read suffix snapshots, then capture a fresh dual-VPS status packet.
  `scripts/summarize_lpfs_live_trades.py` requires the collector-produced
  manifest-backed `--journal-snapshot`. Diagnostics remain flexible offline
  tooling for operator-supplied local evidence; never pass active VPS runtime
  journal paths. Weekly calculations remain separate and unchanged.
- Diagnostic logging state: 2026-05-23 added additive `diagnostics` payloads
  to sparse signal/order/recovery/fill/close/block journal rows and a local
  report builder at `scripts/build_lpfs_trade_diagnostics.py`. This is
  logging/reporting only; it does not change entries, exits, sizing, timeframe
  mix, spread gates, or market recovery behavior. It was deployed to production
  as commit `09fbb10` with deliberate kill-switch-first restarts on FTMO and
  IC. Final packet:
  `reports/live_ops/lpfs_dual_vps_status_20260523_153510.md`; both lanes were
  running, kill switches clear, MT5 trade allowed, and first post-deploy
  diagnostic signal rows were observed with `diagnostic_schema_version=1` plus
  `diagnostics`.
- Diagnostic reporting state: 2026-05-26 extends the local-only diagnostic
  report workflow to enrich closed live trades and benchmark backtest trades
  with offline time/session, setup bucket, recent-window, candle-indicator, and
  FTMO/IC confluence views. This work must remain outside the live runner loop;
  RSI, momentum, volume, and percentile features are computed from copied
  journals and local candle datasets only.
- Production host: Amazon Lightsail Windows VPS.
- Preferred remote access: Tailscale + OpenSSH using local aliases `lpfs-vps`
  and `lpfs-ic-vps`; use Tailscale RDP to the `100.x` VPS addresses when MT5
  desktop review is needed.
- Broker truth: MT5 orders, positions, order history, and deal history.
- Runtime truth: `C:\TradeAutomationRuntime\data\live` on the VPS.
- Local repo truth: tracked code and docs in
  `C:\Users\Cody\OneDrive\Desktop\TradeAutomation` on `LAPTOP-BOHDIO8I`.

## Read Order

1. `SESSION_HANDOFF.md` for the latest operational snapshot.
2. This file for the LPFS recovery map and environment boundaries.
3. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for detailed
   strategy history and current live/research assumptions.
4. `docs/strategy.html` for the current strategy contract.
5. `docs/live_ops.html` for live-run behavior, gates, reconciliation, status,
   and operator commands.
6. `docs/live_weekly_performance.html` for the latest FTMO/IC live weekly
   performance checkpoint and backtest-distribution comparison.
7. `configs/live_policy_ledger.csv` before interpreting live performance across
   FTMO/IC sizing-policy epochs or changing live risk settings.
8. `docs/lpfs_diagnostic_logging.md` before changing LPFS journal diagnostic
   fields, trade diagnostic reports, or live-vs-backtest comparison logic.
9. `docs/lpfs_strategy_iteration_context.md` before continuing the current
   evidence-gated strategy-iteration workflow or handing the task to a fresh
   Codex chat.
10. `docs/lpfs_lightsail_vps_runbook.md` before any VPS maintenance or remote
   access work.
11. `docs/lpfs_icmarkets_vps_runbook.md` before provisioning or deploying the
   IC Markets production runner.
12. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before changing execution or notification code.
13. `docs/lpfs_new_mt5_account_validation.md` before validating another MT5
   account or broker feed.
14. `docs/ftmo_challenge_profiles.html` before changing FTMO challenge risk
   buckets or income expectations.
15. `docs/ea_migration.html` and `mql5/lpfs_ea/README.md` before continuing
   native MQL5 EA or Strategy Tester work.

## Source-Of-Truth Matrix

| Topic | Source of truth | Notes |
| --- | --- | --- |
| Current strategy rules | `docs/strategy.html` and tested Python modules | TradingView is visual-only. |
| Research history | `docs/index.html`, version pages, and LPFS `PROJECT_STATE.md` | V1-V22 pages are audit history; V13/V15/V22 feed the current baseline. |
| Live broker state | MT5 on the VPS | Do not infer open exposure from Telegram alone. |
| Live runtime state | `C:\TradeAutomationRuntime\data\live` on the VPS | Contains state, journal, heartbeat, logs, and kill switch. |
| Live sizing policy epochs | `configs/live_policy_ledger.csv` | Segment live analysis by policy epoch; do not scatter sizing-history notes across docs. |
| VPS restart awareness | Startup alert tasks plus Windows System event log | `VPS STARTED` Telegram means Windows booted; MT5/runner still need heartbeat confirmation. |
| Remote VPS access | `docs/lpfs_lightsail_vps_runbook.md` | Tailscale SSH is preferred for commands; use Tailscale RDP for MT5 desktop review. |
| Account and secrets | ignored `config.local.json` and local OS/user secrets | Never commit MT5 passwords, Telegram tokens, SSH private keys, or account credentials. |
| IC account validation | `docs/account_validation.html`, `docs/lpfs_new_mt5_account_validation.md`, and `config.lpfs_new_mt5_account.example.json` | Local-only validation and smoke testing; do not touch VPS live account. |
| IC production setup | `docs/lpfs_icmarkets_vps_runbook.md`, `config.lpfs_icmarkets_raw_spread.example.json`, and `scripts/Get-LpfsDualVpsStatus.ps1` | Separate VPS/runtime/task/Telegram lane for IC; FTMO remains untouched. |
| FTMO challenge sizing | `docs/ftmo_challenge_profiles.html` and `reports/strategies/lpfs_ftmo_challenge_frontier/20260508_112959` | Research-only frontier; do not change FTMO live validation config without a separate deployment decision. |
| Weekly live performance | `docs/live_weekly_performance.html` and `reports/live_ops/lpfs_weekly_performance/` | Latest-week monitor only; use report packets for historical checkpoints until a trend view is built. |
| Per-trade live diagnostics and strategy-iteration workflow | `docs/lpfs_diagnostic_logging.md`, `docs/lpfs_strategy_iteration_context.md`, LPFS journal `diagnostics` payloads, and `reports/live_ops/lpfs_trade_diagnostics/` | Additive/offline reporting only; use for live-vs-backtest analysis before proposing heuristic changes. |
| Rollover/spread-wait and Bid/Ask fills | `docs/live_ops.html`, `docs/mt5_execution_contract.md`, `SESSION_HANDOFF.md`, and live JSONL journals | Treat Telegram/chart visuals as alerts only; verify MT5 Bid/Ask ticks, order history, journal rows, spread snapshots, and both VPS lanes before concluding a bug. |
| Native EA migration | `docs/ea_migration.html`, `mql5/lpfs_ea/README.md`, and `mql5/lpfs_ea/Experts/LPFS/LPFS_EA.mq5` | Tester-only v1; do not attach to production live charts. |
| Dashboard HTML | builder scripts in `scripts/` | Edit builders, then regenerate HTML; do not make HTML-only dashboard changes. |

## Environment Boundaries

- Active local development environment:
  `C:\Users\Cody\OneDrive\Desktop\TradeAutomation` on `LAPTOP-BOHDIO8I`.
  This checkout has the Python dependency layer installed and core coverage
  passing. Tailscale is installed/logged in at `100.118.29.124`, Git push auth
  works, and local MT5 read-only attach against the default config succeeded.
- FTMO production checkout/runtime/task:
  `lpfs-vps` / `EC2AMAZ-ON6FOF2` / `100.115.34.38`,
  `C:\TradeAutomation`, `C:\TradeAutomationRuntime`, `LPFS_Live`.
- IC production checkout/runtime/task:
  `lpfs-ic-vps` / `EC2AMAZ-DT73P0T` / `100.98.12.113`,
  `C:\TradeAutomation`, `C:\TradeAutomationRuntimeIC`, `LPFS_IC_Live`.
- Direct SSH access to both VPS aliases is verified. After this documentation
  refresh, both VPS checkouts were clean on `main...origin/main`, and
  `Get-LpfsDualVpsStatus.ps1` wrote
  `reports/live_ops/lpfs_dual_vps_status_20260511_005949.md` from this PC on
  2026-05-11.
- The old local PC `cy-desktop` has been removed from Tailscale, old-PC SSH
  key entries were removed from both VPSes, and the public Lightsail RDP rule
  has been removed. Tailscale SSH and RDP remain verified from this PC.

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
- Require `task_multiple_instances=IgnoreNew` for both live scheduled tasks. The
  watchdog stops on child exit code `2`, and the Python runner lock remains the
  final pre-MT5 duplicate-runner boundary.
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
- Retryable waits are not final rejects. Spread waits, AutoTrading-disabled
  waits, market-recovery waits, and broker market-closed waits should remain
  retryable while the setup remains valid.
- Runtime sync should compare the latest runtime commit, not only local
  `HEAD`, because docs/reporting commits may be ahead of the VPS checkout.
- Weekly report SSH/fetch failures must be visible as incomplete evidence, not
  silently treated as clean performance.
- Remote live journal/state reads are production-adjacent. Avoid unbounded
  `Select-String`, `Get-Content -Raw`, or `[System.IO.File]::OpenText()` scans
  against production JSONL/state files. Approved full scans must use
  `FileShare.ReadWrite` and be followed by a fresh dual-VPS status packet.
- For compact summaries, collect a bounded local manifest-backed snapshot
  first. The collector defaults to an exact `64 MiB` suffix, excludes
  `market_snapshot` rows unless explicitly requested for forensics, records
  source byte offsets, and requires `--allow-full-scan` for unbounded reads.
- Diagnostic logging is not a strategy iteration. Do not deploy heuristic
  changes from the current weekly underperformance until enriched live rows are
  compared with the 10-year backtest and a separate change plan is approved.
- For docs-only changes, no VPS runner restart is required.
- A `VPS STARTED` Telegram card is an operating-system alert, not proof the
  trading loop is healthy. Always follow it with heartbeat, journal, and MT5
  broker-state checks.
- Do not patch strategy or executor behavior from one rollover stopout,
  single-broker quote divergence, or Bid-only chart touch. First run a
  read-only dual-VPS/journal/MT5 audit, inspect executable Bid/Ask where
  available, and compare against the 10-year spread-inclusive evidence.

## Resume Prompts

Use one of these prompts to restart cleanly:

- Local docs/research: `Read SESSION_HANDOFF.md and strategies/lp_force_strike_strategy_lab/START_HERE.md, then continue the LPFS docs/research task from the current git state.`
- VPS read-only audit: `Read SESSION_HANDOFF.md and START_HERE.md, then run the lpfs-vps identity, git status, and Get-LpfsLiveStatus checks before making any operational conclusion.`
- Live deployment planning: `Read START_HERE.md, docs/live_ops.html, and docs/lpfs_lightsail_vps_runbook.md, then produce a kill-switch-first VPS deploy plan before changing production.`
- Second MT5 account planning: `Read START_HERE.md and docs/mt5_execution_contract.md, then plan a separate config/runtime/account boundary for another MT5 account without touching current VPS state.`
- Second MT5 account validation: `Read START_HERE.md and docs/lpfs_new_mt5_account_validation.md, then audit the locally logged-in MT5 account before pulling data or running dry-run.`
- IC VPS audit: `Read START_HERE.md and docs/lpfs_icmarkets_vps_runbook.md, then run Get-LpfsDualVpsStatus.ps1 and verify LPFS_Live and LPFS_IC_Live from MT5/runtime state before making operational changes.`
- EA migration: `Read START_HERE.md, docs/ea_migration.html, and mql5/lpfs_ea/README.md, then continue native MQL5 tester-only work without touching VPS runtime, live configs, live journals, or broker orders.`
- Rollover/spread/Bid-Ask audit: `Read START_HERE.md, SESSION_HANDOFF.md, docs/live_ops.html, and docs/mt5_execution_contract.md, then use MT5 history/ticks, both VPS journals, and gate-attribution reports before deciding whether a rollover spread or fill-timing event needs code or ops changes.`
- Diagnostic performance analysis: `Read START_HERE.md, docs/lpfs_strategy_iteration_context.md, docs/lpfs_diagnostic_logging.md, and docs/live_weekly_performance.html, then build or inspect lpfs_trade_diagnostics reports before proposing any LPFS heuristic change.`
- FTMO challenge sizing: `Read START_HERE.md, SESSION_HANDOFF.md, and docs/ftmo_challenge_profiles.html, then inspect the latest lpfs_ftmo_challenge_frontier report before proposing any FTMO risk bucket or max-open-risk change.`
