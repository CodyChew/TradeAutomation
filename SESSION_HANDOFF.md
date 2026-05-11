# TradeAutomation Session Handoff

Last updated: 2026-05-12 after verifying and patching raw-spread zero-quote
handling for FTMO and IC live runners.

This is the canonical context-transfer file for the next AI/Codex session.
Use it as a map, then verify live MT5 state from MT5, the ignored live state
file, and the JSONL journal before making operational decisions.

## Read First

1. `SESSION_HANDOFF.md` for this latest operational snapshot.
2. `strategies/lp_force_strike_strategy_lab/START_HERE.md` for the LPFS
   first-read path, source-of-truth map, environment boundaries, and resume
   prompts.
3. `PROJECT_STATE.md` for workspace context.
4. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for LPFS detail.
5. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before touching execution code.
6. `docs/live_ops.html` for dashboard-level live-run behavior and scenarios.
7. `docs/live_weekly_performance.html` for the read-only FTMO/IC weekly live
   performance monitor, live start timestamps, version context, and
   backtest-distribution comparison.
8. `docs/phase2_production_hardening.md` before operating the watchdog, kill
   switch, heartbeat, status command, or Task Scheduler setup.
9. `docs/lpfs_lightsail_vps_runbook.md` before VPS remote access,
   deployment, or maintenance.
10. `docs/lpfs_icmarkets_vps_runbook.md` before provisioning or deploying the
   IC Markets production runner.
11. `docs/lpfs_new_mt5_account_validation.md` before validating another MT5
   account or broker feed.
12. `docs/ftmo_challenge_profiles.html` before changing FTMO challenge risk
   buckets or income expectations. It is linked from the dashboard top
   navigation and the Home page FTMO Profiles section.
13. `docs/ea_migration.html` and `mql5/lpfs_ea/README.md` before continuing
   native EA or Strategy Tester work.

## AI Agent Continuity Rules

- 2026-05-12 live execution note: IC skipped a 01:00 SGT `EURUSD H4 SHORT`
  because the local execution contract rejected `bid == ask` (`1.17742` /
  `1.17742`) as `invalid_market`, while FTMO placed the matching order. This
  was a real concern: IC had two journal rows for the same processed signal and
  no later order, and the IC spread gate itself passed with zero spread. The
  corrected policy is that equal bid/ask is valid zero spread and must proceed
  to spread gates plus MT5 broker checks; only inverted quotes where bid is
  greater than ask are local `invalid_market` skips.
- External Codex memory may be read-only. Treat this repo handoff plus
  `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` as the durable
  continuity layer for future AI agents.
- For any LPFS live/runtime, Telegram, MT5 execution, scheduled-task, or VPS
  operations change, do not stop at a local patch. Carry the work to a clear
  completion state: focused tests, full relevant tests when practical, commit,
  push, and explicit VPS deploy/verification steps.
- By default, final answers for LPFS live/runtime work must include the VPS
  operator path: pause with kill switch, verify runner stopped, pull/deploy,
  run focused checks, resume `LPFS_Live`, and verify heartbeat, latest log,
  state, journal, MT5 orders/positions, and Telegram lifecycle cards.
- If the change is docs-only and does not need runtime activation, say that no
  VPS runner restart is required. Still give a minimal VPS pull step if the
  user wants the docs available on the VPS checkout.
- Never instruct future agents to edit VPS live state, journal, MT5 orders, or
  MT5 positions unless the user explicitly approves a separate operator plan.
- EA migration work is local/tester-only until separately approved. Do not
  attach the v1 EA to FTMO or IC live charts, and do not run it in the same
  MT5 terminal/account used by Python production without a fresh isolation
  plan.

## Remote VPS Access

Tailscale + OpenSSH is the preferred remote-maintenance path for read-only
LPFS VPS audits and approved cleanup. Tailscale RDP is the preferred interactive
path when MT5 or Windows desktop review is needed.

- Active local operations PC: `LAPTOP-BOHDIO8I`, Tailscale IP
  `100.118.29.124`.
- Local repo path: `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`.
- FTMO VPS: alias `lpfs-vps`, host `EC2AMAZ-ON6FOF2`, Tailscale IP
  `100.115.34.38`, repo `C:\TradeAutomation`, runtime
  `C:\TradeAutomationRuntime`, task `LPFS_Live`.
- IC VPS: alias `lpfs-ic-vps`, host `EC2AMAZ-DT73P0T`, Tailscale IP
  `100.98.12.113`, repo `C:\TradeAutomation`, runtime
  `C:\TradeAutomationRuntimeIC`, task `LPFS_IC_Live`.
- Local SSH keys are under `C:\Users\Cody\.ssh\`:
  `lpfs_vps_ed25519` and `lpfs_ic_vps_ed25519`.
- VPS OpenSSH firewall rule: `OpenSSH-Tailscale-Only`, inbound TCP `22` from
  `100.64.0.0/10`.
- The public Lightsail RDP rule has been removed. Normal operations no longer
  depend on a whitelisted public home/office IP; RDP over Tailscale to
  `100.115.34.38` and `100.98.12.113` was verified from this PC after removal.
- The old local machine `cy-desktop` was removed from Tailscale, and its old
  VPS SSH key entries were removed from both VPSes.
- Authorized-key backups left on the VPSes:
  - FTMO: `C:\ProgramData\ssh\administrators_authorized_keys.bak_20260510_162359`.
  - IC: `C:\ProgramData\ssh\administrators_authorized_keys.bak_20260510_162409`.

Verified remote commands:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-ic-vps hostname
ssh lpfs-ic-vps whoami
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -StateFileName lpfs_ic_live_state.json -JournalFileName lpfs_ic_live_journal.jsonl -HeartbeatFileName lpfs_ic_live_heartbeat.json -LogFilter 'lpfs_ic_live_*.log' -JournalLines 40 -LogLines 80"
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

Latest verified packet from this PC:
`reports/live_ops/lpfs_dual_vps_status_20260511_005949.md`. Both VPS repos
were clean on `main...origin/main`, both scheduled tasks were running, MT5 was
connected and trade-allowed on both lanes, and both kill switches were clear.

Environment boundary rule: local OneDrive is development; VPS
`C:\TradeAutomation` plus each `C:\TradeAutomationRuntime*` root is production.
Future agents should start remote work with host/user checks, VPS `git status`,
and the LPFS status packet before drawing operational conclusions.

## 2026-05-10/11 New PC Onboarding And Cleanup

Current local machine for this session:

- Host/user: `LAPTOP-BOHDIO8I` / `Cody`.
- Local repo path: `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`.
- Branch state at initial onboarding: `main...origin/main` at `43aac99`.
  Current verified post-documentation-sync state is clean `main...origin/main`
  on this PC and both VPS checkouts.
- The Windows `python` on PATH resolves to Python 2.7, so project commands
  should explicitly use `.\venv\Scripts\python.exe`.
- Tailscale is installed and logged in. This laptop has Tailscale IP
  `100.118.29.124` and can see both production VPS devices:
  FTMO `100.115.34.38` and IC `100.98.12.113`.
- The repo venv now has the operational Python packages installed:
  `pandas`, `pyarrow`, `MetaTrader5`, `certifi`, `pytest`, and
  `coverage[toml]`.
- Local MT5 terminal discovered:
  `C:\Program Files\MetaTrader 5\terminal64.exe`. The ignored local configs
  use `mt5.use_existing_terminal_session=true` with no explicit terminal path,
  so local MT5 commands require the intended terminal/account to already be
  open and logged in before any dry-run or live-send cycle.
- A read-only local MT5 probe against `config.local.json` succeeded: account
  login/server matched expected config values, terminal was connected, and
  terminal/account trading flags were true. Do not treat this as permission to
  run local live-send while VPS production runners are active.
- Ignored local configs are present and live-capable:
  `config.local.json`,
  `config.lpfs_icmarkets_raw_spread.local.json`, and
  `config.lpfs_icmarkets_raw_spread.live_smoke.local.json`. Treat them as
  real-account capable.

New-PC verification completed:

- `.\venv\Scripts\python.exe -m pytest strategies\lp_force_strike_strategy_lab\tests\test_dashboard_pages.py strategies\lp_force_strike_strategy_lab\tests\test_live_weekly_performance.py -q`
  passed `35` tests.
- `.\venv\Scripts\python.exe -m pytest strategies\lp_force_strike_strategy_lab\tests\test_live_executor.py strategies\lp_force_strike_strategy_lab\tests\test_live_gate_attribution.py -q`
  passed `34` tests and `9` subtests after adding narrow coverage tests for
  malformed MT5 retcodes and weekly-open market-closed attribution.
- `.\venv\Scripts\python.exe scripts\run_core_coverage.py` passed with
  `100.00%` total line and branch coverage; LPFS discovery ran `322` tests.
- After clarifying the gate-attribution test branch, the strict gate was rerun
  and again passed at `100.00%` coverage with `322` LPFS tests.

Git/GitHub state:

- GitHub read access works from this PC.
- Git push auth works through Git Credential Manager:
  `git push --dry-run origin main` returned `Everything up-to-date`.
- GitHub CLI is installed but not logged in (`gh auth status` reports no
  GitHub hosts). Git CLI push/deploy sync does not depend on `gh` auth unless
  PR/issue workflows are needed.

Direct VPS management is ready from this PC:

- `~\.ssh\config` now defines `lpfs-vps` and `lpfs-ic-vps`.
- New local SSH keys were generated at `~\.ssh\lpfs_vps_ed25519` and
  `~\.ssh\lpfs_ic_vps_ed25519`.
- The user installed the new laptop public keys into each VPS
  `administrators_authorized_keys`.
- `ssh lpfs-vps hostname` returns `EC2AMAZ-ON6FOF2`.
- `ssh lpfs-ic-vps hostname` returns `EC2AMAZ-DT73P0T`.
- `whoami` returns each VPS `administrator` account.
- Both VPS checkouts were fast-forwarded with `git pull --ff-only origin main`;
  this was docs/tests/reporting only and did
  not require or perform a live-runner restart.
- `.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40`
  succeeded from this PC and wrote
  `reports/live_ops/lpfs_dual_vps_status_20260511_005949.md`.
- Latest dual-VPS snapshot from that packet: FTMO and IC tasks both `Running`,
  startup alert tasks `Ready`, kill switches clear, expected parent/child
  runner process shape, fresh running heartbeats, MT5 connected/trade allowed,
  and each lane had `1` pending order plus `1` active position. FTMO tracked
  EURJPY D1 pending ticket `258799969` and GBPUSD D1 active position
  `258801290`; IC tracked AUDNZD H4 pending ticket `4422248655` and EURCHF H12
  active position `4420525163`.
- On 2026-05-11, old-PC SSH public-key entries were removed from both VPS
  `C:\ProgramData\ssh\administrators_authorized_keys` files after verifying
  new-PC SSH access. Backups were left on the VPSes:
  FTMO `administrators_authorized_keys.bak_20260510_162359` and IC
  `administrators_authorized_keys.bak_20260510_162409`. Post-cleanup SSH
  checks from this PC still succeeded, and the remaining key comments are
  `lpfs_vps_ed25519@LAPTOP-BOHDIO8I` and
  `lpfs_ic_vps_ed25519@LAPTOP-BOHDIO8I`.
- The old PC `cy-desktop` was removed from the Tailscale tailnet. After that
  removal and after the public Lightsail RDP rule was deleted, this PC still
  reached both VPSes over Tailscale SSH and TCP `3389` RDP.

## 2026-05-09 Code Freshness / Runner Health Check

Scope: local status refresh, pull-only VPS checkout update, weekly dashboard
refresh, and read-only runner health verification. No live configs, VPS
runtime files, scheduled tasks, state files, journals, broker orders, broker
positions, or runner processes were edited or restarted.

- Local repo was clean and synced with `origin/main` at `18a76af` before the
  refresh.
- The code delta from the previous VPS checkout `a223daf` to `18a76af` was
  reporting/docs/tests only: dashboard builders, weekly performance reporting,
  FTMO challenge profile reporting, generated docs pages, and tests. It did
  not include live executor strategy/runtime logic.
- Both VPS checkouts were fast-forwarded with `git pull --ff-only origin main`
  to `18a76af`:
  - FTMO `C:\TradeAutomation`: `git_head=18a76af`, clean
    `main...origin/main`.
  - IC `C:\TradeAutomation`: `git_head=18a76af`, clean `main...origin/main`.
- No runner restart was performed. The currently running Python processes keep
  using their already-loaded runtime code until a separate approved restart.
- Weekly performance dashboard refreshed to
  `reports/live_ops/lpfs_weekly_performance/20260508_164325/` and
  `docs/live_weekly_performance.html`. Current status remains `watch` for both
  lanes because this is still a partial week and runtime changed inside the
  reporting window:
  - FTMO: `25` closed trades, `-5.3354R`, `-$63.64`, `40.0%` win rate,
    `27` retryable waits, `4` true rejects, `1` pending, `1` active.
  - IC: `9` closed trades, `-5.8779R`, `-$39.05`, `22.2%` win rate,
    `8` retryable waits, `1` true reject, `2` pending, `0` active.
- Latest dual-VPS status packet:
  `reports/live_ops/lpfs_dual_vps_status_20260509_004325.md`.
- FTMO health from that packet: `LPFS_Live` task `Running`, startup alert task
  `Ready`, kill switch clear, parent/child runner process pair alive,
  heartbeat `running` at `2026-05-08T16:43:05.686712Z`, MT5 connected and
  trade allowed. Broker/state snapshot shows EURJPY D1 pending ticket
  `258799969` and GBPUSD D1 active position `258801290`.
- IC health from that packet: `LPFS_IC_Live` task `Running`, startup alert task
  `Ready`, kill switch clear, parent/child runner process pair alive,
  heartbeat `running` at `2026-05-08T16:43:07.753079Z`, MT5 connected and
  trade allowed. Broker/state snapshot shows EURCHF H12 pending ticket
  `4420525163` and AUDNZD H4 pending ticket `4422248655`.
- Verification after this refresh:
  `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests/test_live_weekly_performance.py strategies/lp_force_strike_strategy_lab/tests/test_dashboard_pages.py -q`
  passed `35` tests;
  `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests -q`
  passed `321` tests and `172` subtests; `git diff --check` reported no
  whitespace errors, only line-ending normalization warnings.

## 2026-05-08 Live Weekly Performance Dashboard

This was a read-only reporting/docs change. No live configs, VPS runtime
files, scheduled tasks, state, journals, broker orders, or broker positions
were changed.

- Added `scripts/build_lpfs_live_weekly_performance.py`, a manual FTMO/IC
  weekly report builder. It reads live journals/state and repo HEADs over SSH,
  compares closed-trade weekly net R against each broker's current V22
  commission-adjusted historical weekly distribution, and writes local report
  artifacts plus `docs/live_weekly_performance.html`.
- Manual refresh command:

```powershell
.\venv\Scripts\python.exe scripts\build_lpfs_live_weekly_performance.py --latest
```

- If journals/state/benchmark files/git inputs are unchanged, the script exits
  cleanly with `already up to date` and does not rewrite reports. Use
  `--force` only when intentionally regenerating the same evidence.
- Latest generated packet:
  `reports/live_ops/lpfs_weekly_performance/20260508_164325/`.
- Latest stable page: `docs/live_weekly_performance.html`, linked from
  `docs/index.html` as "Live Weekly Performance".
- Verified live portfolio starts:
  - FTMO first journal event:
    `2026-04-30T19:48:13.743598+00:00`; first order:
    `2026-04-30T19:48:18.664456+00:00`.
  - IC first journal event:
    `2026-05-05T19:49:36.894185+00:00`; first order:
    `2026-05-05T19:49:45.204982+00:00`.
- Current week status from the latest run is `watch` for both lanes. Reasons:
  the week is still partial, runtime changed inside the week, and losses are
  concentrated. IC is also below the historical 10th-percentile weekly R so
  far. FTMO is just above its historical 10th percentile. This is monitoring
  evidence, not a strategy patch instruction by itself.
- Version context from the latest run:
  local, `origin/main`, and both VPS checkouts were `18a76af`;
  latest runtime commit was `94ffea1` (`Treat LPFS market-closed sends as
  retryable`). Runtime sync is true because `94ffea1` is contained in each VPS
  checkout.
- Latest live weekly closed-trade snapshot:
  - FTMO: `25` closed trades, `-5.3354R`, `-$63.64`, `40.0%` win rate,
    `27` retryable waits, `4` true rejects, `1` pending, `1` active.
  - IC: `9` closed trades, `-5.8779R`, `-$39.05`, `22.2%` win rate,
    `8` retryable waits, `1` true reject, `2` pending, `0` active.
- Tests added in
  `strategies/lp_force_strike_strategy_lab/tests/test_live_weekly_performance.py`
  cover lane-start detection, partial-week classification, mid-week runtime
  change warning, unchanged-input no-rewrite behavior, percentile/status
  rules, dashboard content, and shared navigation.

## Known Operational Lapses / Watch Items

- Weekly dashboard is currently a latest-week monitor, not a week-over-week
  trend chart. Use timestamped packets under
  `reports/live_ops/lpfs_weekly_performance/` for historical checkpoints until
  a trend view is built.
- Telegram is reporting only. MT5 broker orders, positions, order history, and
  deal history are the source of truth.
- `VPS STARTED` means Windows booted. It does not prove MT5 login, live runner
  health, or broker connectivity.
- Runtime sync should compare the latest runtime commit, not only local
  `HEAD`, because docs/reporting commits may be ahead of the VPS checkout.
- Retryable waits such as spread, AutoTrading disabled, market recovery, and
  broker market-closed must not be treated as final rejects while the setup
  remains valid.
- Manual deletion and true broker rejection remain final unless an explicit
  operator re-arm plan approves state surgery.
- Rollover spread divergence can create broker-specific outcomes and should
  not be patched from one incident.
- Bid-only chart touches are not broker fill proof. A live buy limit fills on
  Ask at or below entry, and a live sell limit fills on Bid at or above entry;
  verify MT5 ticks/history before treating delayed fills as defects.
- Full 10-year true tick Bid/Ask replay is not currently available from the
  local IC terminal. Use 10-year candle/spread approximation for broad
  research and recent/live tick audits for incident-level fill timing.
- Duplicate runner risk exists if a local live runner and VPS live runner run
  against the same account/state at the same time.
- EA v1 remains Strategy Tester-only. Do not attach it to FTMO or IC live
  charts.
- Weekly report SSH/fetch failures must be visible as incomplete evidence, not
  silently treated as clean performance.
- FTMO challenge-profile full recomputation is too slow for a simple docs
  navigation refresh. For this checkpoint the stable page was rebuilt from the
  accepted `20260508_112959` report packet; a future improvement could add a
  first-class docs-only rebuild mode.

## 2026-05-09 Operations / Documentation Verification Checkpoint

This was a read-only operations checkpoint plus docs/test refresh. No VPS
runtime files, live configs, scheduled tasks, state, journals, broker orders,
or broker positions were changed.

- Local repo started clean and synced at `29c5bc4` / `origin/main`.
- Stable dashboard navigation was regenerated so Home, Strategy, Live Ops,
  Account Validation, FTMO Challenge Profiles, EA Migration, and Weekly
  Performance all expose `live_weekly_performance.html`.
- Weekly monitor refreshed to
  `reports/live_ops/lpfs_weekly_performance/20260508_162326/`, then a second
  `--latest` run printed `already up to date`.
- Latest weekly status remains `watch` for both lanes:
  - FTMO: `25` closed trades, `-5.3354R`, `-$63.64`, `1` pending order,
    `1` active position.
  - IC: `9` closed trades, `-5.8779R`, `-$39.05`, `2` pending orders,
    `0` active positions.
- Dual VPS status packet:
  `reports/live_ops/lpfs_dual_vps_status_20260509_002745.md`.
- FTMO VPS evidence from the packet: `LPFS_Live` task `Running`,
  `task_last_result=267009` (running), startup alert task `Ready` with
  `startup_alert_last_result=0`, kill switch clear, parent/child runner shape,
  heartbeat `running` at `2026-05-08T16:25:46Z`, MT5 connected/trade allowed,
  broker/state snapshot shows EURJPY D1 pending ticket `258799969` and GBPUSD
  D1 active position `258801290`.
- IC VPS evidence from the packet: `LPFS_IC_Live` task `Running`,
  `task_last_result=267009` (running), startup alert task `Ready` with
  `startup_alert_last_result=0`, kill switch clear, parent/child runner shape,
  heartbeat `running` at `2026-05-08T16:28:43Z`, MT5 connected/trade allowed,
  broker/state snapshot shows EURCHF H12 pending ticket `4420525163` and
  AUDNZD H4 pending ticket `4422248655`.
- Cross-account open state had `0` shared signal keys, `2` FTMO-only and `2`
  IC-only. Current interpretation is expected broker/feed/start-date
  divergence; inspect journals before treating this as a defect.

## 2026-05-08 Rollover Spread / Broker Divergence Audit

This was a read-only QA/operator audit. No live configs, VPS runtime files,
scheduled tasks, state, journals, broker orders, or broker positions were
changed.

- IC live `AUDNZD H4` and `AUDNZD H8` long positions stopped out around
  `2026-05-08 05:02 SGT`; FTMO kept the comparable positions open in the same
  window. The IC journal snapshot around the close showed `bid=1.21071`,
  `ask=1.21456`, and `385` points of spread. FTMO bid stayed above its stop in
  the observed journal window.
- Current interpretation: this is broker quote/spread/feed divergence during
  daily rollover, not evidence of an LPFS signal bug. Do not patch strategy or
  executor logic from this single event.
- The 10-year candle-level realism model already includes spread as bid/ask
  movement. A read-only audit of current commission-adjusted V22 separated
  trades showed rollover-containing intraday exit bars were still net positive:
  IC `2,461` such exits for `+364.3R`; FTMO `2,487` such exits for `+308.8R`.
  Rollover stops exist, but were outweighed by rollover targets in the same
  study. Tick-level rollover spikes can still be understated when they are not
  preserved in candle OHLC/spread data.
- The 05:00-06:00 SGT order-placement lag on 2026-05-08 was caused by
  retryable `spread_too_wide` WAITING rows, not a runner outage or duplicate
  bug. Both VPS lanes were running with fresh heartbeats and 140-frame cycles.
  Several CAD-cross setups waited through rollover and placed when spread
  normalized near 06:00 SGT.
- Current operator decision: keep existing spread gate and retry behavior.
  No extra monitoring code is necessary yet. If rollover waits/stops repeat or
  materially hurt PnL, build a read-only rollover report that groups journal
  rows by signal key and broker lane, measuring first WAITING reason, spread
  ratio, later placement/expiry/invalidation, and FTMO-vs-IC outcome.

## 2026-05-09 EURCHF Bid/Ask Fill Realism Audit

This was a read-only IC live-order/backtest-realism investigation. No live
configs, VPS runtime files, scheduled tasks, state, journals, broker orders, or
broker positions were changed.

- Trigger question: IC `EURCHF H12` appeared to fill late even though the MT5
  chart showed earlier candle lows below the entry zone.
- Broker state: IC `EURCHF H12` `BUY_LIMIT` ticket `4420525163`, entry
  `0.91447`, SL `0.91203`, TP `0.91691`, volume `0.02`. The order was placed
  promptly after the signal, then filled at
  `2026-05-08 18:50:01 UTC` / `2026-05-09 02:50 SGT`.
- Finding: the screenshot is consistent with the queried data. MT5 candles are
  Bid-based; a buy limit fills only when Ask is at or below the limit. Earlier
  Bid lows crossed/approached the entry, but the executable Ask stayed above
  entry. The first queried tick with `ask <= 0.91447` matched the later live
  fill time (`bid` about `0.91442`, `ask` about `0.91447`).
- Operator conclusion: expected broker Bid/Ask fill mechanics, not a runner
  bug. Do not re-arm or patch this signal from the chart alone.
- Backtest implication: a raw OHLC fill model can mark a buy-limit entry
  earlier when Bid low crosses entry. V16-style candle-spread bid/ask realism
  approximates `Ask = Bid + spread`, but it is still not a true tick-by-tick
  Ask path and can differ around rollover/wide-spread periods.
- Feasibility check: local IC MT5 had 10-year M1/H4/D1 bars and non-zero M1
  spread fields for all 28 LPFS FX pairs, but true tick Bid/Ask history
  requested from `2016-05-09` returned first ticks only around `2025-01`
  for the 28-pair universe. Full 10-year true tick replay is therefore not
  currently feasible from this IC terminal. Recent/live tick-level audits are
  feasible and should be used for specific incidents.
- Evidence artifacts were written locally under ignored
  `reports/live_ops/tick_history_feasibility/`, including the IC tick probe,
  2016 bar probe, and M1 spread probe. These are local evidence packets, not
  committed source files.
- Next research step if this repeats or affects PnL: build a read-only
  tick-fill audit that compares journaled pending orders against available tick
  Bid/Ask, classifies early candle-touch versus executable-touch drift, and
  reports whether drift changes realized outcome. Do not replace the 10-year
  benchmark until the incident-level audit shows material impact.

## 2026-05-07 EA Migration Scaffold

- Added isolated native MQL5 EA workspace under `mql5/lpfs_ea/`.
- EA v1 is Strategy Tester-only by default: `InpTesterOnly=true` and
  `InpAllowLiveTrading=false`. It refuses to initialize outside tester with
  those defaults.
- EA identity is separate from production: `MagicNumber=331500` and
  `CommentPrefix=LPFSEA`; it does not collide with FTMO `131500/LPFS` or IC
  `231500/LPFSIC`.
- Added Python parity fixture exporter
  `scripts/export_lpfs_ea_fixtures.py` and tracked fixture
  `mql5/lpfs_ea/fixtures/canonical_lpfs_ea_fixture.json`.
- Added local MetaEditor compile helper
  `mql5/lpfs_ea/scripts/Compile-LpfsEa.ps1`; it only compiles the EA source
  and does not touch live terminals, VPS runtime, configs, state, journals, or
  broker orders.
- Local MetaEditor compile check passed with `0 errors, 0 warnings`; Strategy
  Tester load/config smoke also passed in MT5.
- The first EURUSD H4 tester run printed the LPFS configuration, risk schedule,
  basket/timeframes, and tester-only mode. It was intentionally stopped because
  the scaffold requests the full 28-symbol x 5-timeframe basket on every tick,
  causing an impractical first-smoke estimate.
- Next EA continuation task: add `InpSmokeTestSingleChartOnly=true` so the
  first smoke path scans only `_Symbol/_Period`, and add new-bar gating so
  full-basket mode does not rescan all frames on every tick.
- Added `docs/ea_migration.html` and linked it from `docs/index.html`.
- Production live runs were not changed: no VPS pull, no task restart, no
  config edits, no live state/journal edits, and no MT5 order/position changes.

## 2026-05-06 Wrap-Up / Git State

- Local tracked docs now include the LPFS handoff-first cleanup:
  `strategies/lp_force_strike_strategy_lab/START_HERE.md`, refreshed
  dashboard builders, and stale current-state notes removed.
- Future local work should branch from `main` unless the user explicitly asks
  for a different branch.
- The telemetry change is observability-only: Telegram `ORDER PLACED` cards and
  journal rows now expose signal-close time, placement time, and placement lag.
  It did not change LPFS signal selection, MT5 order-send semantics, sizing,
  spread gates, pending expiry, live state schema, or TradingView behavior.
- The preferred production baseline is `main`. Verify both local and VPS repo
  state with `git status --short --branch` before deploy or audit work.
- Local IC smoke test evidence now exists: ignored
  `config.lpfs_icmarkets_raw_spread.live_smoke.local.json` sent one local IC
  `AUDCHF H8` pending order (`4419969921`), the user manually canceled it, and
  both MT5 and the local smoke state returned to `0` pending orders and
  `0` positions.
- The VPS FTMO runner was checked after this smoke test and remained active:
  `LPFS_Live` parent/child process shape, fresh heartbeat, runtime root
  `C:\TradeAutomationRuntime`, `frames_processed=140`, and clean VPS repo
  `main...origin/main`.
- Docs-only changes do not require restarting `LPFS_Live`. If the user wants
  the docs available on the VPS checkout, use a pull-only update after proving
  identity and status:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git pull --ff-only origin main"
```

- IC Markets production is now a separate live VPS lane, not a change to the
  existing FTMO VPS: alias `lpfs-ic-vps`, host
  `EC2AMAZ-DT73P0T`, Tailscale IP `100.98.12.113`, runtime root
  `C:\TradeAutomationRuntimeIC`, ignored config
  `config.lpfs_icmarkets_raw_spread.local.json`, magic `231500`, broker comment
  prefix `LPFSIC`, and separate Telegram channel. `LPFS_IC_Live` is installed
  and running with `risk_bucket_scale=2.0`. `LPFS_IC_Startup_Alert` is the
  IC boot/restart Telegram task. Use
  `docs/lpfs_icmarkets_vps_runbook.md` before maintenance.

## 2026-05-06 Restart Alert Hardening

- Added ops-only startup alert sender
  `scripts/send_lpfs_vps_startup_alert.py`.
- Added installer `scripts/Install-LpfsStartupAlertTask.ps1`.
- Startup alert tasks run as `SYSTEM` at Windows startup, retry Telegram while
  networking comes up, and write `vps_startup_alert` rows to the relevant live
  journal.
- The alert path does not import MT5, does not call `order_check` or
  `order_send`, and does not read or mutate live state.
- Current task names:
  - FTMO: `LPFS_FTMO_Startup_Alert`.
  - IC: `LPFS_IC_Startup_Alert`.
- Important limit: `VPS STARTED` means Windows booted. It does not prove MT5 or
  the trading loop is healthy; verify `LPFS_Live` / `LPFS_IC_Live` heartbeat,
  latest journal rows, and MT5 broker state after the alert.

## IC Markets VPS Live Status

The dedicated IC VPS was provisioned, smoke-tested, and promoted on
2026-05-06:

- SSH alias `lpfs-ic-vps` works from the local PC.
- Repo checkout `C:\TradeAutomation` is clean on `main...origin/main`.
- Python venv exists at `C:\TradeAutomation\venv`.
- Focused IC-lane test suite passed: `91 passed`.
- Runtime root `C:\TradeAutomationRuntimeIC` exists and the kill switch is
  clear.
- Telegram-only smoke from the IC VPS delivered to the separate IC channel.
- MT5 is logged into the expected IC account/server:
  `ICMarketsSC-MT5-2`, company `Raw Trading Ltd`, currency `USD`; expected
  login matched without printing the full account number.
- All `28` configured FX symbols are available/selected.
- Quick candle probe returned `20` rows for every H4/H8/H12/D1/W1 frame.
- One IC VPS dry-run cycle ran `order_check` only: `140` frames processed,
  `3` setups checked, `3` pending intents created, `3` broker checks passed,
  `0` broker checks failed.
- The checked current setups were `AUDCHF H8` long, `GBPCAD H12` long, and
  `NZDCHF W1` short using magic `231500` and comments beginning `LPFSIC`.
- Broker state after dry-run remained flat for IC: `0` orders and
  `0` positions.
- One IC VPS live-send smoke cycle completed from the VPS after the config was
  promoted to `LIVE_SEND`; it placed `1` tracked pending order and left
  `0` active positions.
- Continuous task `LPFS_IC_Live` is installed and running through
  `scripts\run_lpfs_live_forever.ps1` with runtime root
  `C:\TradeAutomationRuntimeIC`, files `lpfs_ic_live_*`, and log prefix
  `lpfs_ic_live`.
- `scripts/Get-LpfsDualVpsStatus.ps1` writes ignored
  `reports/live_ops/lpfs_dual_vps_status_*.md` packets for later inspection and
  compares open signal keys across FTMO and IC.
- `scripts/summarize_lpfs_live_gate_attribution.py` now streams FTMO/IC live
  journals over SSH and writes ignored
  `reports/live_ops/lpfs_gate_attribution_*.md` reports. Use it before changing
  spread or market-recovery rules.

Do not run a second IC live process manually while `LPFS_IC_Live` is active.
Pause with the IC kill switch and verify `processes=0` before IC maintenance.

## 2026-05-06 Live Gate Attribution Snapshot

Read-only dual VPS status at 2026-05-06 21:16 SGT showed both scheduled tasks
running on clean `main...origin/main` checkouts with expected parent/child
Python process shape, kill switches clear, fresh heartbeats, and `orders_sent=0`,
`setups_blocked=0`, `setups_rejected=0` in the latest completed cycles.

Current broker/state snapshot from that packet:

- FTMO: pending `AUDCHF H8 LONG` and `GBPCAD H8 LONG`; active
  `EURCHF H12 LONG`; MT5 server `FTMO-Server`.
- IC: pending `AUDCHF H8 LONG`, `EURCHF H4 LONG`, `EURCHF H8 LONG`, and
  `EURCHF H12 LONG`; no active IC LPFS positions; MT5 server
  `ICMarketsSC-MT5-2`.

Initial gate-attribution report:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_gate_attribution.py --ssh-journal "FTMO=lpfs-vps:C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl" --ssh-journal "IC=lpfs-ic-vps:C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_journal.jsonl" --tail-lines 200000 --detail-limit 60 --output reports\live_ops\lpfs_gate_attribution_latest.md
```

Latest generated local artifact:
`reports/live_ops/lpfs_gate_attribution_20260506_2138.md` (ignored). It showed
FTMO window `2026-05-05T08:42:28Z` to `2026-05-06T13:25:56Z`: `18` unique
decision signals, `10` placements, `0` spread waits, `1` market-recovery price
wait, `5` expiries, and `0` retryable waits inside the weekly-open window. IC
window `2026-05-05T19:49:36Z` to `2026-05-06T13:38:19Z`: `7` unique decision
signals, `4` placements, `0` spread waits, `3` market-recovery price waits,
`1` entry-touch/path skip, `0` expiries, and `0` weekly-open-window waits. This
is evidence-gathering only; no live rule, risk, state, MT5 order, or Telegram
behavior changed.

## Current Project Focus

The active work is the LP + Force Strike strategy lab. The strategy baseline is
V13 mechanics with V15 risk buckets and V22 LP/FS separation:

- LP3, `take_all`, H4/H8/H12/D1/W1.
- Selected LP pivot must be before the Force Strike mother bar
  (`lp_pivot_index < fs_mother_index`).
- 0.5 signal-candle pullback entry.
- Force Strike structure stop.
- 1R target.
- Fixed 6-bar pullback wait.
- Live pending expiry is bar-counted from actual MT5 candles after the signal
  candle. Weekend time does not count; Friday bars after the signal do count.
  The MT5 order also carries a conservative broker backstop in case the runner
  stops.
- V15 unscaled risk buckets: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

The legacy override `require_lp_pivot_before_fs_mother=false` exists only for
reproducible comparison such as V22 control. Do not edit live state or rearm
historical processed/skipped signals for this baseline change.

Live broker testing scales that ladder with `live_send.risk_bucket_scale=0.05`,
so H4/H8 are `0.01%`, H12/D1 are `0.015%`, and W1 is `0.0375%`.

FTMO challenge profile research is now separate from the live validation
config. Latest run:
`reports/strategies/lpfs_ftmo_challenge_frontier/20260508_112959`, with
docs page `docs/ftmo_challenge_profiles.html`, linked from
`docs/index.html` top navigation and the Home page FTMO Profiles section.

- Source: current FTMO V22 separated, commission-adjusted trade set; initial
  signal-candle spread gate overlaid from FTMO candle `spread_points` at the
  live threshold `max_spread_risk_fraction=0.10`.
- Fresh FTMO 100k Challenge profile: H4/H8 `0.20%`, H12/D1 `0.20%`, W1
  `0.65%`. Results: `248.70%` 10-year return, `9.46%` risk-reserved DD,
  `4.45%` estimated max daily-loss stress, `4.45%` max open risk, worst week
  `-4.43%`, worst month `-4.68%`. Median month on 100k is about `$2,000`;
  middle monthly range is about `$325` to `$3,783`. Rolling weekly-start
  Challenge windows hit `+10%` in `463/522` windows with median `136.7` days,
  and no modeled FTMO daily/max-loss failures.
- Aggressive/funded profile: H4/H8 `0.20%`, H12/D1 `0.25%`, W1 `0.55%`.
  Results: `270.12%` 10-year return, `9.14%` risk-reserved DD, `4.95%`
  estimated max daily-loss stress, `4.95%` max open risk, worst week `-4.63%`,
  worst month `-3.92%`. Median month on 100k is about `$2,143`; middle monthly
  range is about `$464` to `$3,919`. This is warning-band risk because daily
  stress is close to FTMO's `5%` daily-loss limit.
- Spread overlay did not contradict the recommendation: initial spread-gated
  return ratios were above `1.15` for the selected profiles. This does not mean
  spread is always beneficial; it means the rows initially blocked by the
  10%-of-risk spread gate were net negative in this historical candle-spread
  approximation. Live retry/market recovery remains tick-dependent.
- Do not change `config.local.json` or the FTMO VPS runner to these profile
  values without a separate deployment decision. The current FTMO live runner
  remains low-scale validation, not a challenge account profile.

New MT5 account validation is now documented as a local-only path. Use
`docs/lpfs_new_mt5_account_validation.md`,
`scripts/audit_lpfs_new_mt5_account.py`, and the new-account example configs
before any dry-run/order-check work on a different account. The local IC smoke
test does not authorize continuous IC live-send. Do not change the VPS MT5
login or restart `LPFS_Live` for this validation.

## Architecture Map

- Signal concepts:
  `concepts/lp_levels_lab/src/lp_levels_lab/levels.py` and
  `concepts/force_strike_pattern_lab/src/force_strike_pattern_lab/patterns.py`.
- Strategy signal selector:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/signals.py`.
- Research/backtest model:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/experiment.py`
  plus `shared/backtest_engine_lab`.
- Bid/ask execution realism:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/execution_realism.py`
  and `scripts/run_lp_force_strike_v16_execution_realism.py`.
- LP-FS proximity research:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/proximity.py`
  and `scripts/run_lp_force_strike_v17_lp_fs_proximity.py`.
- Portfolio and sizing research:
  `portfolio.py`, `stability.py`, V13-V15 scripts, and generated `docs/v13.html`
  through `docs/v17.html`.
- Broker boundary:
  `execution_contract.py` is pure Python and must not import MetaTrader5.
- Live MT5 behavior:
  `live_executor.py` owns live-send checks, order_send, reconciliation, state,
  duplicate/adoption recovery, fill/close handling, and lifecycle events.
- Runner CLI:
  `scripts/run_lp_force_strike_live_executor.py` owns cycle count, sleep,
  single-runner locking, runtime-root override, kill-switch checks, heartbeat,
  process start/stop notifications, final state save, and MT5 shutdown.
- Telegram UX:
  `notifications.py`, `docs/telegram_notifications.md`, and
  `scripts/summarize_lpfs_live_trades.py`.
- Runtime files:
  `data/live/lpfs_live_state.json` and `data/live/lpfs_live_journal.jsonl` are
  ignored local truth for continuity and audit; do not commit them.
- Phase 2 operations plan:
  `docs/phase2_production_hardening.md` captures the local launcher, kill
  switch, watchdog, runtime-folder, heartbeat, Task Scheduler path, and VPS
  readiness checks. `docs/lpfs_lightsail_vps_runbook.md` captures the Amazon
  Lightsail setup.

## Safety Status

The user confirmed the connected MT5 account is real. Treat live-send as a
real-order path.

Do not run this casually:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 1
```

The runner is a finite-cycle CLI, not an OS service. For a manual long run, use
a very large cycle count and stop with Ctrl+C:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 100000000 --sleep-seconds 30
```

Do not clear `data/live/lpfs_live_state.json` unless the user explicitly wants
to re-arm already processed latest-candle signals. Clearing live state can
place duplicate pending orders if the same setup still passes all checks.

The runner now holds `data/live/lpfs_live_state.json.lock` while active. A
second runner against the same state exits fail-closed before MT5
initialization.

Phase 2 production wrapper commands:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "staging"
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 20 -LogLines 40
.\scripts\run_lpfs_live_forever.ps1 -ConfigPath config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30
```

With `--runtime-root C:\TradeAutomationRuntime`, live state, journal,
heartbeat, kill switch, and logs live outside OneDrive. The kill switch stops
new live cycles before MT5 initialization, before each cycle, and during sleeps;
it does not close open positions or delete pending broker orders by itself.
Before switching runtime roots, copy existing live state/journal when they
exist. The runner now fails closed if the old configured state exists but the
new runtime-root state is missing, unless `--allow-empty-runtime-state` is
passed intentionally after broker-state verification.

`save_live_state()` normally uses atomic temp-file replace. On Windows/OneDrive,
the state file can be a reparse-point placeholder and deny `os.replace()`.
The save path now retries and falls back to direct state-file writing on
`PermissionError` so the live runner does not crash during state persistence.

## Last Verified Live-Test Snapshot

This is a historical snapshot from the fresh 2026-05-01 live test, not a
guarantee of the broker's current state. Always inspect MT5, state, and journal
before acting.

Before the fresh test cycle, old local live files were archived:

```text
data/live/lpfs_live_state.json.bak_20260501_034805
data/live/lpfs_live_journal.jsonl.bak_20260501_034805
```

Fresh live-send cycle result:

- Frames processed: `140`.
- Orders sent: `2`.
- Setups rejected: `2`.
- Tracked strategy positions at that time: none.

Last verified strategy pending orders in MT5 and local state:

```text
EURNZD H8 SHORT | SELL_LIMIT #257048012
Entry 1.99622 | SL 2.00515 | TP 1.98728
Size 0.01 | Expires 2026-05-02 21:00 SGT
Telegram order card message_id 127
```

```text
GBPJPY H12 SHORT | SELL_LIMIT #257048014
Entry 215.802 | SL 216.591 | TP 215.013
Size 0.02 | Expires 2026-05-03 17:00 SGT
Telegram order card message_id 128
```

Skipped in that fresh cycle:

- `AUDJPY D1 SHORT`: entry was already touched before placement.
- `NZDCHF H4 LONG`: spread was too wide, about `11.5%` of risk versus the
  `10.0%` gate.

## Execution Behavior To Preserve

- The live runner processes closed candles only.
- It only acts when the LPFS signal candle is the latest closed candle.
- LPFS selector rule: if multiple LP-break windows match one FS signal,
  bullish uses the lowest valid support LP and bearish uses the highest valid
  resistance LP. Equal-price ties use the latest valid break.
- Signal idempotency key:
  `lpfs:{SYMBOL}:{TIMEFRAME}:{SIGNAL_INDEX}:{SIDE}:{CANDIDATE_ID}:{FS_SIGNAL_TIME}`.
- A new signal candle creates a new key.
- Manual deletion of a pending MT5 order does not re-arm the signal. If local
  state still tracks the order, the next reconciliation should emit a
  cancelled/missing lifecycle alert and remove it from pending tracking.
- MT5 broker state is the source of truth for orders, positions, and deals.
- Local live state is persisted immediately after broker-affecting safety
  mutations. It uses atomic replace when Windows allows it, with a OneDrive-safe
  fallback for replace-denied state files.
- Before live `order_send`, the runner checks for an exact matching strategy
  pending order or matching open position and adopts it instead of sending a
  duplicate.
- Pending-to-position fill matching requires broker comment or historical
  order/deal linkage; same volume alone is not enough.
- Manual or unknown broker exits are shown as `LPFS LIVE | TRADE CLOSED`, not
  as stop losses, while still using MT5 PnL/R.
- Telegram is best-effort UX only and must never decide trade validity.

## Notification UX

Telegram now sends compact plain-text trader cards:

- `LPFS LIVE | ORDER PLACED`
- `LPFS LIVE | ORDER ADOPTED`
- `LPFS LIVE | ENTERED`
- `LPFS LIVE | TAKE PROFIT`
- `LPFS LIVE | STOP LOSS`
- `LPFS LIVE | TRADE CLOSED`
- `LPFS LIVE | WAITING`
- `LPFS LIVE | SKIPPED`
- `LPFS LIVE | REJECTED`
- `LPFS LIVE | CANCELLED`
- `LPFS LIVE | RUNNER STARTED`
- `LPFS LIVE | RUNNER STOPPED`

Fill, close, expiry, and cancellation alerts reply to the original order-card
message when Telegram returns a `message_id`. Raw broker comments, retcodes,
exact floats, and diagnostics stay in JSONL.

Runner start/stop alerts are process heartbeat cards. They show the
sleep-after-cycle setting, requested/completed cycles, runtime, state-save
status, and SGT start/stop time. The `30s` setting is a sleep after each
completed scan, not a fixed wall-clock launch interval. They are best-effort
Telegram UX and are also journaled.

Manual performance summary, metric-only by default:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --days 7
```

Post compact summary:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --weeks 4 --post-telegram
```

On the VPS, production journal/state live under `C:\TradeAutomationRuntime`, so
the summary commands must include `--runtime-root`:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --days 7
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --weeks 4 --post-telegram
```

Do not add `--include-trades` for routine Telegram summaries. That flag is the
explicit long-form override and appends the trade-by-trade list.

Latest weekly summary posts on 2026-05-06:

- FTMO compact 1-week summary: `16` closed trades, `43.8%` win rate, net PnL
  `-37.85`, total `-1.88R`, latest close `2026-05-06 18:53 SGT`.
- IC raw-spread compact 1-week summary: no closed trades found in the IC VPS
  live journal.

## Spread Gate

Current live setting: `max_spread_risk_fraction=0.1`.

A spread-too-wide setup is now a retryable WAITING event, not a permanent
rejection. The live runner does not mark the signal processed for spread-only
blocks, so a future cycle can place the order if spread improves before the
entry touches or the pending window expires. The one old NZDCHF spread skip was
cleaned from local live state explicitly instead of keeping compatibility code.

Broker `Market closed` placement blocks are retryable too. If MT5 returns
retcode `10018` or a `Market closed` comment before any pending order or market
recovery order exists, the runner emits `LPFS LIVE | WAITING`, removes the
processed signal key, and retries on future cycles while the setup is still
valid. This does not re-arm true broker rejections or manually deleted orders.

Default-on market recovery is now the live path after a missed pending touch.
If spread was too wide first and the original entry later traded before the
pending order existed, the runner attempts `MARKET RECOVERY` before final skip.
It sends a `TRADE_ACTION_DEAL` only when current executable price is at least as
good as the original entry (`ask <= entry` for longs, `bid >= entry` for
shorts), spread is still no more than `10%` of actual fill-to-stop risk, the
setup is still inside the 6 actual-bar window, and the original stop/target
path after the first entry touch is clean. Worse-than-entry executable prices
are now retryable `WAITING` events, not permanent skips; the signal key is not
marked processed and no MT5 order is sent while waiting. It keeps the original
structure stop, recalculates TP to 1R from actual fill, and sizes volume from
actual fill-to-stop risk. Rollback is `live_send.market_recovery_mode="disabled"`.

Continuity note for VPS handoff: this change does not rearm historical skipped
signals already present in `lpfs_live_state.json`. Do not edit live state to
recover old skips unless a separate operator plan explicitly approves it.

Implementation verification:

- 2026-05-05 market-recovery retry focused tests:
  `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_notifications -v`
  passed: 38 tests.
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  passed: 215 tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed with 100.00%
  total coverage.
- 2026-05-04 market-recovery initial verification:
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_notifications -v`
  passed: 38 tests.
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  passed: 186 tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed with 100.00%
  total coverage.

Deployment note: the VPS live runner will not use this recovery behavior until
the VPS repo is updated and `LPFS_Live` is intentionally restarted after config
review. Existing running processes keep the code they started with.

After an order is pending, spread widening does not auto-cancel it and does not
currently trigger a dedicated Telegram alert. Reconciliation keeps the order
until fill, expiry, or broker/user removal.

First Lightsail weekly-open observation: the runner reconciled the two old
LPFS pending orders out of local state because MT5 no longer showed them, then
sent multiple spread-too-wide WAITING cards and one entry-already-touched
SKIPPED card. Treat this as expected conservative live behavior at poor
liquidity, but measure it before tuning because persistent spread blocks during
normal hours would make forward execution diverge from V15.

Next evidence task before changing the spread rule: build a live gate
attribution report from `lpfs_live_journal.jsonl` showing detected setups,
placed orders, spread waits, later placements after spread improves,
entry-touch skips, expiries, affected symbols/timeframes, and whether blocks
cluster around weekly open.

V16 execution-realism result:

- Report: `docs/v16.html`.
- Run folder:
  `reports/strategies/lp_force_strike_experiment_v16_execution_realism/20260501_060205`.
- No-buffer bid/ask model: `12,917` trades versus `13,012` V15 OHLC baseline
  trades, total `1,535.2R` versus `1,512.3R`, PF `1.270` versus `1.265`.
- No-buffer missed only `95` baseline trades, changed `284` exit reasons, and
  still passed V15 practical bucket filters.
- Best raw buffer was `1.5x` signal-candle spread: `1,587.1R`, but it changed
  `722` exit reasons and `493` win/loss signs.
- Decision: bid/ask realism is not a material regression. Keep current live FS
  structure stops unchanged for now. Treat spread buffers as promising follow-up
  research, not an immediate live-rule change.

V17 LP-FS proximity result:

- Report: `docs/v17.html`.
- Run folder:
  `reports/strategies/lp_force_strike_experiment_v17_lp_fs_proximity/20260501_122711`.
- Baseline V15 OHLC: `13,012` trades, `1,512.3R`, PF `1.265`.
- Strict touch only: `12,358` trades, `1,471.3R`, PF `1.272`.
  Quality improved slightly, but it cut `654` trades and gave up about `41R`.
- Farther-than-1ATR setups were a small but positive bucket:
  `110` trades, `17.6R`, PF `1.391`.
- V15 bucket sensitivity still favored current V15: return/DD `48.56`
  versus strict-touch `46.64`.
- Decision: keep current V15 unchanged. Do not require the Force Strike
  structure to touch the selected LP. A future dashboard/live label can show
  LP-FS proximity as setup quality, but it is not a trade filter.
- Staleness note after V22: V17 studied the old signal universe. Rerun it on
  the separated signal baseline before using it for any new live-design
  decision.

V18/V19/V20 TP-near research result:

- V18 report: `docs/v18.html`.
- V19 report: `docs/v19.html`.
- V20 report: `docs/v20.html`.
- V19 run folder:
  `reports/strategies/lp_force_strike_experiment_v19_tp_near_robustness/20260504_194519`.
- V19 keeps the old V15 LPFS strategy baseline and uses the V16 no-buffer
  bid/ask simulator as the control environment.
- V19 close variants now use hard reduced-TP semantics: `close_pct_90` exits at
  `0.9R` once touched and does not get upgraded to full `1R` later.
- V19 full-universe scope: all `H4/H8/H12/D1/W1` LPFS datasets from
  `configs/datasets/forex_major_crosses_10y.json`.
- V19 wrote `16,061` signals, `12,917` control trades, and `245,423` variant
  trade rows.
- V16 no-buffer control: `12,917` trades, `1,535.2R`, PF about `1.270`.
- Hard `close_pct_90`: `12,917` trades, `1,594.0R`, PF about `1.302`, only
  `+58.8R` versus control. It is not a live candidate.
- V19 best live-design candidate: `lock_0p50r_pct_90`, with `12,917` trades,
  `1,878.7R`, PF about `1.356`, and `+343.5R` versus the V16 control.
- `lock_0p50r_pct_90` saved `390` trades from later stops for about `+585.0R`,
  sacrificed `259` later full TPs for about `-129.5R`, and had `308`
  same-bar-conflict rows for about `-112.0R`.
- The V19 decision matrix marks `lock_0p50r_pct_90` as passing raw R, PF,
  return/DD, practical bucket, saved/sacrificed, concentration,
  year-stability, and same-bar gates.
- V19 is still research-only. It did not change live executor behavior, VPS
  runtime, MT5 orders/state, Telegram lifecycle behavior, or TradingView
  indicators.
- V20 run folder:
  `reports/strategies/lp_force_strike_experiment_v20_protection_realism/20260505_043723`.
- V20 keeps the same H4/H8/H12/D1/W1 LPFS signal baseline but replays entry,
  exit, and stop-protection behavior on M30 bid/ask candles.
- V20 intentionally brackets live stop-modification timing. Default stress
  variants do not assume instant stop modification: a `0.9R` touch only locks
  the stop on a later M30 candle, and fast snapbacks are counted as missed. It
  also includes `lock_0p50r_pct_90_m30_same_assumed` as an optimistic same-M30
  upper bound for the live 30-second loop.
- V20 M30 replay control: `12,022` trades, `336.9R`, PF about `1.058`.
- Same-M30 upper bound: `lock_0p50r_pct_90_m30_same_assumed` produced
  `512.9R`, PF about `1.095`, `+176.0R` versus control, `2,561` trigger
  touches, `2,561` assumed activations, `427` saved-from-stop trades,
  `747` sacrificed full-TP trades, and `206` same-bar conflicts. This is not
  direct live evidence because intra-M30 ordering is unknown.
- Conservative later-M30 variants were flat to negative. `m30_next` was
  `-53.0R` versus control. `m30_delay1` was `331.4R`, PF about `1.058`,
  `-5.5R` versus control, `1,043` activations, and `540` too-late rejections.
- V20 is still research-only. It did not change live executor behavior, VPS
  runtime, MT5 orders/state, Telegram lifecycle behavior, or TradingView
  indicators.
- Current TP-near conclusion: do not implement live stop protection from V19
  alone. Real 30-second live behavior is likely between V20's pessimistic
  later-M30 stress and its optimistic same-M30 upper bound. The next valid
  evidence step is M1/tick replay or forward live attribution of `0.9R` touches,
  modification success, and later outcome.
- Staleness note after V22: V18/V19/V20 used the old signal universe. Rerun
  TP-near/protection research on the separated baseline before using those
  dashboards for a live TP/SL design.

A read-only sanity check over 720 recent detected setups showed:

- `5%` gate: 607/720 pass (`84.3%`).
- `10%` gate: 714/720 pass (`99.2%`).
- `15%` gate: 720/720 pass (`100.0%`).

Current recommendation: keep `10%`. Consider an H4-only relaxation to `15%`
only if live evidence shows too many good H4 setups are skipped.

## Phase 2 Readiness

Current stage: controlled live validation on a real MT5 account with low-risk
scaled V15 sizing. The Lightsail VPS production wrapper is installed and
observable, and the operator has started the long-running VPS task. Current
state must be verified from the VPS status packet, MT5, heartbeat, latest log,
and journal rather than from this static handoff.

Phase 2 local production hardening is now implemented without changing strategy
rules:

- `scripts/run_lpfs_live_forever.ps1`: watchdog launcher and timestamped logs.
- `scripts/Set-LpfsKillSwitch.ps1`: creates/clears the emergency stop file.
- `scripts/Get-LpfsLiveStatus.ps1`: pasteable status packet for operator/Codex
  review.
- `scripts/run_lp_force_strike_live_executor.py --runtime-root`: moves
  production state/journal away from OneDrive.
- Runtime-root migration guard: refuses to start from an empty production state
  when the old configured live state exists, unless explicitly bypassed.
- `scripts/run_lp_force_strike_live_executor.py --heartbeat-path`: writes
  process/cycle heartbeat JSON.
- `scripts/run_lp_force_strike_live_executor.py --kill-switch-path`: stops
  before MT5 init, before live cycles, and during sleeps when `KILL_SWITCH`
  exists.

Local rehearsal passed on 2026-05-03:

- `C:\TradeAutomationRuntime\data\live` was staged with copied live state and
  journal.
- `KILL_SWITCH` is active at `C:\TradeAutomationRuntime\data\live\KILL_SWITCH`.
- Read-only MT5 preflight matched the expected account/server in local config.
- MT5 showed two LPFS pending orders and zero LPFS positions, matching staged
  runtime state.
- Direct one-cycle production-runtime run completed with `frames_processed=140`,
  `orders_sent=0`, `setups_rejected=0`, and `setups_blocked=0`.
- Watchdog one-cycle run completed and wrote a timestamped log under
  `C:\TradeAutomationRuntime\data\live\logs`.
- Temporary Task Scheduler smoke run with kill switch active returned result
  `3`, the expected kill-switch exit.
- Temporary Task Scheduler one-cycle live rehearsal returned result `0`.
- Temporary scheduled tasks were removed after rehearsal; no persistent
  auto-start task is installed locally.

The same wrapper has now been moved to Amazon Lightsail using
`docs/lpfs_lightsail_vps_runbook.md`. Keep risk unchanged; the VPS runner was
started only after explicit operator go-live checks.
Treat the Lightsail VPS as the production environment for future live
iteration: repo `C:\TradeAutomation`, runtime `C:\TradeAutomationRuntime`, task
`LPFS_Live`. Local OneDrive remains the development workspace until changes are
explicitly pushed/pulled to the VPS and the task is intentionally restarted.

Lightsail VPS deployment checkpoint passed on 2026-05-04 SGT:

- Instance path: Amazon Lightsail Windows Server 2022 in `ap-southeast-1`,
  2 GB plan, host `EC2AMAZ-ON6FOF2`.
- VPS repo path: `C:\TradeAutomation`.
- VPS runtime root: `C:\TradeAutomationRuntime`.
- MT5 path: `C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe`.
- MT5 Python attach succeeds against `FTMO-Server` and the expected account.
- MT5 API sees the two LPFS strategy pending orders, both with magic `131500`:
  `EURNZD H8 SHORT #257048012` and `GBPJPY H12 SHORT #257048014`.
- MT5 API also showed two non-LPFS open positions with `magic=0`; those are
  outside LPFS management but still consume account margin/risk.
- `config.local.json`, `lpfs_live_state.json`, and `lpfs_live_journal.jsonl`
  were copied to the VPS production paths.
- VPS direct one-cycle run completed with exit code `0`.
- VPS watchdog one-cycle run completed with exit code `0`, wrote a timestamped
  log, and delivered Telegram runner start/stop cards.
- Temporary VPS Task Scheduler smoke test with kill switch active returned
  result `3`, the expected kill-switch exit.
- Temporary VPS Task Scheduler one-cycle live test returned result `0`.
- Telegram initially failed on the VPS with an SSL certificate verification
  error. Commit `3a9cb0a` added `certifi` for Telegram HTTPS; after `git pull`
  and `pip install certifi`, explicit Telegram test delivery and runner
  lifecycle cards succeeded.
- Final at-logon scheduled task `LPFS_Live` is installed and `Ready`. It runs
  `scripts\run_lpfs_live_forever.ps1` with `Cycles 100000000` and
  `SleepSeconds 30`.
- The user cleared the VPS kill switch and started `LPFS_Live`. The latest
  pasted status showed `kill_switch_active=False`, heartbeat `running`,
  `pending_orders=2`, `active_positions=0`, and `processes=2`.
- `processes=2` is expected for one logical Windows venv-launched runner when
  one entry is `C:\TradeAutomation\venv\Scripts\python.exe` and the other is
  its child `C:\Program Files\Python312\python.exe` for the same LPFS command.
  Confirm with `parent_pid`, `exe`, heartbeat freshness, matching config/runtime
  root, and one advancing latest log. Treat it as duplicate only if that
  parent/child shape is absent, configs/runtime roots differ, heartbeat is
  stale, or there are more than two runner entries.

Next VPS decision: keep the VPS runner under observation with status packets,
MT5 open orders/positions, Telegram alerts, and the latest log. Do not run the
local PC runner at the same time.

Operator quick checks live in `docs/lpfs_lightsail_vps_runbook.md` under
`Operator Quick Reference`. The main packet to paste into Codex is:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Also inspect MT5 open orders/positions on the VPS and compare against the state
file whenever Telegram reports a placement, cancellation, fill, stop, target,
or runner error. Telegram is useful for signal/runner monitoring, but MT5 is
the broker source of truth.

Do not change stops, targets, spread threshold, risk buckets, or pending
expiration as part of Phase 2. The one accepted signal-rule change is V22 hard
LP/FS separation. Corrected V19 marks `lock_0p50r_pct_90` as a research-only
live-design candidate, but no TP-near live behavior has been implemented or
deployed, and that branch is stale until rerun on the V22 signal universe.

## Verification Commands

Targeted tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_notifications strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary -v
```

Runner/process notification tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_runner -v
```

PowerShell syntax check:

```powershell
powershell -NoProfile -Command "$files = 'scripts\run_lpfs_live_forever.ps1','scripts\Get-LpfsLiveStatus.ps1','scripts\Set-LpfsKillSwitch.ps1'; foreach ($file in $files) { [scriptblock]::Create((Get-Content -Raw $file)) | Out-Null; Write-Host ""syntax ok $file"" }"
```

Full strict gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Latest full strict result on 2026-05-06 after the live gate-attribution and
documentation refresh:

- `300` LPFS unittest discovery cases inside `scripts/run_core_coverage.py`.
- Core coverage ran all scoped concept/shared/LPFS tests and reported
  `100.00%` line and branch coverage across the measured modules.

Latest docs/handoff verification on 2026-05-08 after the live weekly
performance dashboard refresh:

- `.\venv\Scripts\python.exe scripts\build_lpfs_live_weekly_performance.py --latest`
  generated `reports/live_ops/lpfs_weekly_performance/20260508_155536/`
  and `docs/live_weekly_performance.html`.
- A second `--latest` run printed `already up to date`, proving unchanged
  inputs do not rewrite the report.
- `.\venv\Scripts\python.exe scripts\build_lp_force_strike_index.py`
  regenerated `docs/index.html` with the Weekly Performance card/link.
- `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests/test_live_trade_summary.py strategies/lp_force_strike_strategy_lab/tests/test_dashboard_pages.py strategies/lp_force_strike_strategy_lab/tests/test_live_weekly_performance.py -q`
  passed `39` tests.
- `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests -q`
  passed `320` tests and `172` subtests.
- `git diff --check` reported no whitespace errors. Git printed line-ending
  normalization warnings only.

Latest operations/docs verification on 2026-05-09:

- `.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 40 -LogLines 80`
  wrote `reports/live_ops/lpfs_dual_vps_status_20260509_004325.md`.
- `.\venv\Scripts\python.exe scripts\build_lpfs_live_weekly_performance.py --latest`
  generated `reports/live_ops/lpfs_weekly_performance/20260508_164325/`
  and refreshed `docs/live_weekly_performance.html`.
- Regenerated stable pages: Home, Strategy, Live Ops, Account Validation,
  FTMO Challenge Profiles, EA Migration, and Weekly Performance. The FTMO
  page was rebuilt from the accepted `20260508_112959` report packet rather
  than re-running the full frontier study.
- `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests/test_live_trade_summary.py strategies/lp_force_strike_strategy_lab/tests/test_dashboard_pages.py strategies/lp_force_strike_strategy_lab/tests/test_live_weekly_performance.py strategies/lp_force_strike_strategy_lab/tests/test_ea_migration.py -q`
  passed `44` tests.
- `.\venv\Scripts\python.exe -m pytest strategies/lp_force_strike_strategy_lab/tests -q`
  passed `321` tests and `172` subtests.
- `git diff --check` reported no whitespace errors. Git printed line-ending
  normalization warnings only.

Latest selector revalidation on 2026-05-01:

- Patched LPFS from latest matching LP break to most-extreme valid LP across the
  active trap window.
- Regenerated V9 into
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260501_032404`.
- Old/new V9 `signals.csv` and `trades.csv` were byte-identical, so V10-V15
  metrics stayed unchanged.
- V15 efficient row remains H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

## Current Code Additions

- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_trade_summary.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/notifications.py`
- `scripts/run_lp_force_strike_live_executor.py`
- `scripts/run_lpfs_live_forever.ps1`
- `scripts/Get-LpfsLiveStatus.ps1`
- `scripts/Set-LpfsKillSwitch.ps1`
- `scripts/summarize_lpfs_live_trades.py`
- `scripts/build_lp_force_strike_live_ops_page.py`
- `scripts/run_lp_force_strike_v17_lp_fs_proximity.py`
- `scripts/run_lp_force_strike_v19_tp_near_robustness.py`
- `docs/phase2_production_hardening.md`
- `docs/lpfs_lightsail_vps_runbook.md`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/proximity.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/tp_near_exit.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_executor.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_runner.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_trade_summary.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_proximity.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_v17_lp_fs_proximity_report.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_v19_tp_near_robustness_report.py`

The tracked code also includes the execution contract, dry-run executor,
dashboard docs, and notification UX changes. Do not revert unrelated user/local
changes or ignored runtime files.
