# TradeAutomation Project State

Last updated: 2026-07-04 ICT after context architecture hardening.

This is the concise workspace control file. It points to current owners for
live handoff, LPFS strategy context, evidence packets, and history. It does not
authorize live operations, broker actions, runtime-state edits, journal edits,
report regeneration, strategy changes, or deployment.

## Immediate LPFS Safety State

Read `AGENTS.md`, `SESSION_HANDOFF.md`,
`strategies/lp_force_strike_strategy_lab/START_HERE.md`, and
`docs/lpfs_c01_live_safety_release.md` before any LPFS operation.

LPFS live data collection is running on both VPS lanes. The latest accepted
operating boundary is the 2026-06-15 RA-002/RA-003 robustness deploy at runtime
SHA `6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`. It includes the RA-002 final
pre-send quote-unavailable block, RA-003 Stage 5 contract pin refresh, Phase 1
live quote telemetry separation at SHA
`027e0afe932081713067dc24b2bc457cddf1041e`, active-position state/broker repair
at SHA `45efa748423f20881507cda9d4f81e4afe617bde`, and transient market-data
frame-skip handling.

Latest recorded same-day dual status packet:
`reports/live_ops/lpfs_dual_vps_status_20260627_080624.md`, SHA-256
`b56f0ad7bf543ac157522522173620a01c2ce584b1c4925974738681e616728d`. It showed
both lanes `RUNNING`, runtime SHA `6c4ecb1`, kill switches clear, broker status
`OK`, recovery disabled, telemetry failures `0`, market-data fetch failures
`0`, and active state/broker mismatch count `0`. Broker exposure counts in
that packet are historical facts only; capture a fresh dual VPS status packet
before future live operations.

No reconciliation, canary, recovery enablement, manual broker mutation,
strategy/risk/sizing/SL/TP/broker-send/config change was performed during the
latest robustness deployment.

## Source-Of-Truth Route

- Standing rules and live-safety policy: `AGENTS.md`.
- Latest volatile handoff: `SESSION_HANDOFF.md`.
- Context ownership map: `docs/context_architecture.md`.
- Evidence packet paths/hashes: `docs/evidence_catalog.md`.
- Material decisions: `docs/decision_log.md` and `docs/reviews/`.
- Old operational history: `docs/history/lpfs_operations.md`.
- Repo/process maintenance policy: `docs/repo_maintenance_policy.md`.
- LPFS first-read path: `strategies/lp_force_strike_strategy_lab/START_HERE.md`.
- LPFS current strategy/live state:
  `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`.
- LPFS strategy queue and blockers: `docs/lpfs_strategy_iteration_context.md`.
- LPFS strategy workflow: `docs/lpfs_strategy_improvement_workflow.md`.
- Majority Flush research lane:
  `strategies/majority_flush_strategy_lab/START_HERE.md`.

## Purpose

TradeAutomation is a Python-first trading research workspace. TradingView is
used for visual inspection, while Python modules, MT5 broker data, broker
history, journals, and reviewed evidence packets are the sources for strategy
research and live-execution work.

## Current Structure

- `concepts/`: reusable LP, Force Strike, and Majority Flush concepts.
- `shared/`: reusable market data, backtest, and research infrastructure.
- `strategies/lp_force_strike_strategy_lab/`: active LPFS strategy research,
  MT5 execution contracts, dry-run/live-send adapters, Telegram notification
  contracts, diagnostics, and LPFS tests.
- `strategies/majority_flush_strategy_lab/`: research-only Majority Flush lane
  with no live runner or production runtime.
- `mql5/lpfs_ea/`: isolated native MQL5 EA migration workspace. Current state
  is Strategy Tester-only; do not attach it to FTMO or IC live charts without a
  separate approved deployment plan.
- `docs/`: versioned documentation, dashboards, review artifacts, history, and
  process docs.
- `data/` and `reports/`: generated local data/results, intentionally ignored.

Preserved local side labs outside this repo live beside it in
`../TradingResearchLabs/`.

## Current Operations Access

- Active local operations PC: `LAPTOP-BOHDIO8I`, Tailscale IP
  `100.118.29.124`, repo
  `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`.
- FTMO VPS: `lpfs-vps` / `EC2AMAZ-ON6FOF2` / `100.115.34.38`, runtime
  `C:\TradeAutomationRuntime`, task `LPFS_Live`, magic/comment family
  `131500` / `LPFS`.
- IC VPS: `lpfs-ic-vps` / `EC2AMAZ-DT73P0T` / `100.98.12.113`, runtime
  `C:\TradeAutomationRuntimeIC`, task `LPFS_IC_Live`, magic/comment family
  `231500` / `LPFSIC`.
- Use Tailscale SSH/RDP. Public Lightsail RDP has been removed.
- Tailscale unattended mode is enabled on both VPSes.
- Do not access VPS, MT5, Task Scheduler, live runtime state, production
  journals, broker orders, broker positions, or kill switches without explicit
  user approval.

## Current LPFS Strategy State

Latest eligible weekly strategy-review packet:
`reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107`.
Both lanes were `analysis_eligible=true` with `coverage_status=complete`.
FTMO: `20` closed trades, `+1.99R`, broker PnL `+11.24`, PF `1.21`,
historical band `p46.9`. IC: `22` closed trades, `-4.84R`, broker PnL
`-11.79`, PF `0.65`, historical band `<=p10`. Combined: `42` closes,
`-2.85R`, broker PnL `-0.55`, PF `0.88`.

Latest strategy research readiness packet:
`reports/live_ops/lpfs_strategy_research_readiness/20260627_131500`, manifest
SHA-256 `1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6`.

Current decision: no live strategy change now. The simple H8 low-spread-only
filter is rejected. H8 compressed risk (`timeframe=H8`,
`risk_atr_bucket=lt_0p5`) remains a research-only candidate and must be tested
against the next eligible weekly packet plus recent-window and long-history
guardrails before any formal proposal.

Live sizing policy epochs are tracked in `configs/live_policy_ledger.csv`.
Segment IC rows explicitly around `2026-05-30T17:14:27Z` until reporting
automatically assigns ledger `policy_id`.

## Current Baselines

LPFS baseline: V13 mechanics plus V15 risk buckets plus V22 LP/FS separation.
The selected LP pivot must be before the Force Strike mother bar. Current
baseline mechanics are LP3 take-all across H4/H8/H12/D1/W1, `0.5`
signal-candle pullback entry, full Force Strike structure stop, single `1R`
target, and fixed 6-bar pullback wait.

Research-only FTMO challenge sizing remains separate from live validation
config. Use `docs/ftmo_challenge_profiles.html` before changing FTMO challenge
risk assumptions.

## Evidence And Reporting Safety

Use broker facts as authoritative where available. Journals, dashboards,
Telegram alerts, inferred timestamps, and R values are local or derived
evidence.

Primary lifecycle journals are append-only. Do not migrate, compact, truncate,
rewrite, hash, or unsafe-scan active production journals. Use bounded or
shared-read collection and fresh dual-VPS status proof for production-adjacent
journal/state reads.

Generated dashboards can lag behind the latest ignored report packets. Use
`docs/evidence_catalog.md` and `docs/lpfs_strategy_iteration_context.md` for
the latest indexed packet pointers.

## Testing And Verification

Core strategy, concept, market-data, and backtest logic is protected by:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

For first-read, workflow, context, repo-process, or decision-history changes:

```powershell
.\venv\Scripts\python -B scripts\audit_repo_process.py
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Broaden tests when source behavior, live behavior, reporting builders,
generated dashboards, strategy/risk logic, or shared contracts change.

## Current Non-Actions

The 2026-07-04 context hardening is docs/process-only. It does not change live
strategy behavior, entry/exit logic, risk sizing, SL/TP logic, spread gates,
broker-send behavior, configs, scheduler/watchdog state, runtime state,
journals, reports, generated dashboards, VPS state, broker orders, broker
positions, account state, or market recovery.
