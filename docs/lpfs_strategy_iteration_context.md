# LPFS Strategy Iteration Context

Last updated: 2026-07-09 ICT after operator-approved LPFS flatten and project
hold.

This is the durable handoff for the current LPFS diagnostic reporting and
strategy-iteration work. A new Codex chat should be able to read this file,
`SESSION_HANDOFF.md`, `docs/lpfs_strategy_improvement_workflow.md`, and
`strategies/lp_force_strike_strategy_lab/START_HERE.md` without needing prior
conversation history.

## Current Objective

Improve LPFS as a whole, not just one weak bucket, through evidence-backed
weekly monitoring, offline diagnosis, candidate research, and explicit
strategy-change approval. Production-derived analysis must use trustworthy
journals, broker facts, status evidence, and normalized C-01 timestamp evidence
where historical timestamp paths are involved. Weekly automation is the routine
read-only trigger; deeper indicator-tagging and backtest research should start
only when eligible weekly evidence shows repeated weakness, account-outcome
divergence that needs attribution, or a clear evidence gap.

The current work is planning/research while LPFS is on hold. It is not a live
strategy change, not a live deployment, and not approval to resume entries,
exits, risk, timeframe selection, spread gates, recovery behavior, or broker
execution.

The current leading active research candidate is H8 compressed risk:
`timeframe=H8` and `risk_atr_bucket=lt_0p5`. This is a research candidate only,
not a live filter. The maintained 2026-07-05 candidate matrix keeps the bucket
active because current live, 3M backtest, 6M backtest, and all-history backtest
are weak, with acceptable removal breadth. It is still not proposal-ready
because the current live sample is small and the 12M backtest window is
positive. The 2026-06-27 research pass rejected the simple H8 low-spread-only
filter because low-spread H8 was live-weak but historically positive; it remains
diagnostic context, not a causal rule. No live strategy, risk, sizing, SL/TP,
spread, recovery, broker-send, or config change is approved.

LPFS live trading and live data collection are currently on hold. On
2026-07-09 ICT the operator approved flattening both LPFS lanes and pausing the
project for review and next-step planning. Both lane tasks are disabled, both
kill switches are active, and broker-authoritative LPFS pending orders and
active positions are `0` on both FTMO and IC. Before strategy analysis, use the
flatten/hold packet as current broker/ops context, then use normalized C-01
evidence for production-derived historical timestamps.

## Current Project State

- LPFS live operation has two production lanes: FTMO and IC. They ran the same
  strategy and should be reviewed together for confluence, but both lanes are
  now held flat pending planning.
- Live sizing policy epochs are tracked in `configs/live_policy_ledger.csv`.
  Use that ledger when reading live results across FTMO and IC so analysis does
  not mix strategy performance with risk-policy changes. The active IC
  scale-down is a future-order sizing policy change, not a strategy-rule
  change.
- Diagnostic lifecycle payloads already preserve
  `diagnostics.strategy.risk_bucket_scale`, and flattened trade reports expose
  `diagnostic_strategy_risk_bucket_scale`. The current offline report builder
  does not yet assign ledger `policy_id` or automatically group comparisons by
  sizing-policy epoch. Until that enhancement exists, segment IC rows
  explicitly using the ledger activation boundary `2026-05-30T17:14:27Z` and
  the flattened diagnostic scale field.
- The latest completed weekly checkpoint is
  `reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107`.
  Both lanes are `analysis_eligible=true` with complete weekly coverage. FTMO
  had 20 closed trades, `+1.99R`, broker PnL `+11.24`, 11 wins / 9 losses, PF
  `1.21`, historical band `p46.9`; IC had 22 closed trades, `-4.84R`, broker
  PnL `-11.79`, 9 wins / 13 losses, PF `0.65`, historical band `<=p10`;
  combined was 42 closed trades, `-2.85R`, broker PnL `-0.55`, PF `0.88`.
- Current flatten/hold packet:
  `reports/live_ops/lpfs_flatten_hold_20260709_050513`, manifest SHA-256
  `2e0cf51d45b705cef5a23f5126e330028cf69b3de006a874f6b29d698aef55c0`.
  Final dual-status report:
  `reports/live_ops/lpfs_flatten_hold_20260709_050513/final_dual_status/lpfs_dual_vps_status_20260709_051800.md`,
  SHA-256 `e8bba7a9dbdb5cdd37dc2332cff022becf29671a3dbdba644e7e96bc1939e7f1`.
  It shows both lanes contained, broker `OK`, LPFS pending orders `0`, and
  LPFS active positions `0`. State/broker mismatch is expected because runtime
  state and journals were intentionally not rewritten after manual flatten.
  Treat the mismatch as quarantined hold-state evidence, not active broker
  exposure.
- Current research closeout:
  `reports/live_ops/lpfs_strategy_research_readiness/20260627_131500`, manifest
  SHA-256 `1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6`.
  The strategy decision is `NO` live change now. Keep H8 compressed risk active
  as the primary research candidate, reject the H8 low-spread-only filter, and
  require the next eligible weekly packet to test the explicit watch criteria
  before escalating any formal candidate proposal.
- Current maintained candidate matrix:
  `reports/live_ops/lpfs_candidate_backtest_matrix/20260705_064500`, manifest
  SHA-256 `23c3d3da7afff6fab030816bcfc30645c0a900da443a8490d6a257ded53f4b6a`.
  It was built from safe July 4 diagnostics and factor-attribution packets.
  H8 `risk_atr_bucket=lt_0p5` is the leading active research candidate, broad
  buckets such as `long_side`, `setup_age_bars_bucket=1`, and
  `fs_total_bars_bucket=3_to_4` are diagnostic only, and incomplete
  candle/spread factor coverage is a data gap rather than proposal-grade
  evidence.
- Current skipped-opportunity diagnostics:
  `reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`,
  manifest SHA-256
  `ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.
  It was built from safe July 4 filtered lifecycle copies and found `4` IC
  `volume_below_min` account/broker-minimum skips and `0` FTMO
  broker-minimum skips in that evidence window. These are non-executed setup
  diagnostics, not closed trades, broker PnL, or live sizing-change approval.
- Historical 2026-05-30 weekly checkpoint:
  `reports/live_ops/lpfs_weekly_performance/20260530_150637`. Its generated
  dashboard had an FTMO fetch-timeout caveat, so the authoritative FTMO
  checkpoint read was the supplemental local-snapshot review at
  `reports/live_ops/lpfs_weekly_performance/20260530_150637/local_snapshot_review.md`.
  That week was mixed rather than a clean cross-lane failure: FTMO was
  acceptable and IC was weak/watch but still above p10.
- FTMO previously had three completed weeks below p30, and IC had two
  completed weeks below p30. The 2026-05-30 weekly checkpoint alone does not
  justify a live strategy change, but the first-month monthly view escalates
  the next step from passive monitoring to offline investigation now.
- First-month monthly review: `docs/lpfs_monthly_evidence_20260530.md`.
  Against the accepted V22 separated commission-adjusted monthly backtest
  distribution, FTMO May 2026 live closed trades are `-15.09R` over 71 trades
  at monthly p1.67, and IC is `-13.47R` over 61 trades at monthly p0.83.
  The 10-year backtest did not have every month profitable: FTMO had 28 losing
  months out of 120, and IC had 20 losing months out of 121. The current live
  month is still near the historical lower tail and warrants cause attribution.
- Diagnostic lifecycle logging has already been deployed to production as a
  logging-only change. It adds sparse `diagnostics` payloads to signal/order/
  recovery/fill/close/block events.
- The local diagnostic report builder has been extended to make those logs
  useful for future strategy review. This reporting change has not been
  deployed to the VPS and does not need a runner restart unless the user later
  wants the report code available on the VPS checkout.
- Current enriched closed-trade sample is research-useful but still not enough
  for an informed live heuristic change. The 2026-06-27 diagnostic packet
  `reports/live_ops/lpfs_trade_diagnostics/20260627_121200` has 86 closed
  trades, 86 rows with diagnostic payloads, and 86 rows with offline candle
  enrichment. Manifest SHA-256:
  `d30a72bea2669ba87e547eacd2604b34c0aaa8772dbab03b7adf2d716a81bb13`.
- Weekly automation is part of the diagnostic workflow. It should collect or
  inspect read-only report/status packets, reject incomplete evidence using
  `analysis_eligible=false` or `coverage_status=incomplete`, and post a concise
  Telegram summary only when existing ignored local configs expose credentials.
  Telegram is informational only and is not broker truth.
- Offline indicator research should compute tags at signal time during
  analysis, not inside the live runner loop by default. Candidate tags include
  RSI, MACD or momentum, EMA relationship/slope, ATR percentile, candle
  body/range/wick structure, tick-volume percentile where available,
  spread-risk, session/hour, weekday, and broker lane. Store raw or large
  analysis evidence in ignored report packets with manifests; commit only
  scripts, tests, docs, schemas, and small sanitized summaries.
- Strategy-agent experience from the June 2026 iteration: the workflow improves
  when weekly monitoring, issue diagnosis, candidate research, and live
  strategy-change approval are separate stages. Do not let chat memory become
  the source of truth. Record the active research queue, rejected hypotheses,
  packet paths, manifest hashes, watch criteria, and explicit non-actions in
  this file and the first-read docs so another agent can continue from the repo.
  The agent should look portfolio-wide first, then candidate buckets; a narrow
  bucket such as H8 compressed risk is only one current hypothesis.
- Candidate matrices now have a maintained builder:
  `scripts/build_lpfs_candidate_backtest_matrix.py`, with definitions in
  `configs/strategy_research/lpfs_candidate_matrix_current.json`. Use this path
  instead of ad hoc spreadsheets or one-off scripts so factor coverage,
  guardrails, and non-actions are recorded in a manifest.
- Broker-minimum skipped opportunities now have a maintained builder:
  `scripts/build_lpfs_skipped_opportunity_diagnostics.py`. Use it to analyze
  `volume_below_min` from safe local lifecycle copies when IC/FTMO
  comparability or account-size policy effects matter. Do not mix these rows
  into closed-trade performance.
- The standing cadence, trigger/triage outcomes, data-gap escalation rules, and
  human-operator timeline are defined in
  `docs/lpfs_strategy_improvement_workflow.md`.

## Approved Scope

Approved now:

- Offline diagnostic reporting from safely collected local journal copies.
- Offline candle-derived enrichment from explicit provenanced candle datasets.
  FTMO/IC live-lane attribution requires lane-authoritative candle roots;
  unverified workstation candles are a `DATA_GAP`.
- FTMO/IC confluence views.
- Recent 3, 6, and 12 month analysis windows, with the full 10-year backtest
  as the robustness guardrail.
- Documentation and handoff updates that preserve this operating context.
- Tests for report generation, backward-compatible journal parsing, and
  unchanged executor behavior.

Not approved now:

- Live strategy heuristic changes.
- Per-timeframe rules beyond existing risk buckets.
- Entry, exit, stop, target, recovery, spread, risk, or exposure changes.
- Config default changes, except the separately executed IC future-order
  scale-down captured in `configs/live_policy_ledger.csv`.
- Live runner loop indicator calculations.
- VPS deployment or runner restarts for this reporting-only work.
- Manual edits to live state, journals, MT5 orders, MT5 positions, or history.

## Current Research Packets

The active strategy-research context is repo-backed by ignored local report
packets and tracked first-read docs. Do not commit raw ignored report packets;
preserve paths and hashes in handoff docs instead.

- Weekly strategy-review packet:
  `reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107`;
  `weekly_summary.csv` SHA-256
  `49eb0b436953fbfee74193acf59e874d4f54b7d36044494d24eb77405347dfe1`.
- Dual-status packet:
  `reports/live_ops/lpfs_dual_vps_status_20260627_080624.md`; SHA-256
  `b56f0ad7bf543ac157522522173620a01c2ce584b1c4925974738681e616728d`.
- Trade diagnostics packet:
  `reports/live_ops/lpfs_trade_diagnostics/20260627_121200`; manifest SHA-256
  `d30a72bea2669ba87e547eacd2604b34c0aaa8772dbab03b7adf2d716a81bb13`.
- Historical candidate backtest matrix:
  `reports/live_ops/lpfs_candidate_backtest_matrix/20260627_122800`; manifest
  SHA-256 `4e3191ef8075f7c2511d9ed419884fe1ea389b0696c50e119cf6315875621d60`.
- Current maintained candidate backtest matrix:
  `reports/live_ops/lpfs_candidate_backtest_matrix/20260705_064500`; manifest
  SHA-256 `23c3d3da7afff6fab030816bcfc30645c0a900da443a8490d6a257ded53f4b6a`.
- Current skipped-opportunity diagnostics:
  `reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`;
  manifest SHA-256
  `ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.
- Live-vs-backtest divergence attribution:
  `reports/live_ops/lpfs_live_backtest_divergence/20260627_124500`; manifest
  SHA-256 `e76af5226a87a5c885f81f049a80234a558101fffb171f665f1dcabd04b7e9b7`.
- H8 compressed-risk candidate dashboard:
  `reports/live_ops/lpfs_h8_compressed_risk_candidate/20260627_125500`;
  manifest SHA-256
  `894581b8eeff1da94869b999a3c153da53b077eb099b4c084aea653c899ba801`.
- H8 compressed-risk interaction isolation:
  `reports/live_ops/lpfs_h8_compressed_risk_interactions/20260627_130500`;
  manifest SHA-256
  `1f66b98321f55ec5821bc39f08167c010475ba79570d7846529b16ad1193a89e`.
- Strategy research readiness closeout:
  `reports/live_ops/lpfs_strategy_research_readiness/20260627_131500`;
  manifest SHA-256
  `1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6`.

## Files To Inspect First

Start here in a fresh Codex chat:

1. `SESSION_HANDOFF.md`
2. `strategies/lp_force_strike_strategy_lab/START_HERE.md`
3. `docs/lpfs_strategy_iteration_context.md`
4. `docs/lpfs_strategy_improvement_workflow.md`
5. `docs/lpfs_diagnostic_logging.md`
6. `docs/evidence_catalog.md`
7. `docs/reviews/2026-07-04-lpfs-candle-provenance-guardrail.md`
8. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`
9. `docs/live_weekly_performance.html`
10. `docs/mt5_execution_contract.md`
11. `docs/lpfs_lightsail_vps_runbook.md`
12. `docs/lpfs_icmarkets_vps_runbook.md`

Before touching production-adjacent data, verify current repo status and live
status. Do not assume this handoff is live-state truth.

## How To Continue Safely

1. Run `git status --short` and separate intended LPFS diagnostic files from
   unrelated dirty files.
2. Read the files listed above before making changes.
3. Decide whether the task is docs-only, reporting-only, research-only, or
   production-adjacent.
4. For docs-only work, do not touch live runners or VPS state.
5. For reporting-only work, use safe local journal copies and explicit
   provenanced candle datasets. FTMO/IC live-lane candle-derived attribution
   requires lane-authoritative candle roots; unverified workstation candles are
   a `DATA_GAP`.
6. For production-adjacent reads, use safe bounded/shared-read tooling and
   verify both VPS lanes afterward.
7. For any live deploy or restart, create a separate kill-switch-first operator
   plan and get explicit approval.

## What Not To Touch

- Live entry, exit, stop, target, recovery, spread, risk, exposure, or
  timeframe-selection logic.
- Config defaults or ignored live configs.
- MT5 orders, positions, deal history, live state, live journals, or runtime
  files.
- Scheduled tasks or live runners unless the user explicitly approves an
  operator plan.
- High-volume `market_snapshot` logging.
- Unrelated dirty files in the current worktree.

## Analysis Workflow To Improve The Strategy

The workflow is evidence-gated manual adaptation:

1. Collect safe local copies of FTMO and IC journals.
2. Build the offline LPFS diagnostic trade report.
3. Review FTMO and IC together, not independently.
4. Identify whether weakness is broad or concentrated by timeframe, symbol,
   side, session, weekday, setup geometry, volatility regime, momentum regime,
   tick-volume regime, spread-risk, execution path, recovery path, hold time,
   or exit reason.
5. Treat one-lane weakness first as broker/feed/execution divergence.
6. Use recent 3, 6, and 12 month benchmark windows as the primary research
   lens.
7. Use the full 10-year FTMO and IC backtests as the overfitting guardrail.
8. Research both defensive and constructive candidates only after evidence
   supports the cause.
9. Deploy no live strategy change unless a separate approved strategy-change
   plan passes recent-window checks, full-history guardrails, and FTMO/IC
   confluence.

Defensive candidates include filters, gates, exposure reductions, session or
spread avoidance, setup-age/risk filters, and correlated exposure limits.

Constructive candidates include better entry timing, entry-zone changes,
stop/risk-distance changes, target/partial/exit changes, recovery behavior
changes, and regime-aware management.

## Evidence Thresholds

Use these as operating guidance, not automatic deploy rules:

| Timeframe class | Investigate after | Research candidate after |
| --- | ---: | ---: |
| Higher frequency, such as H4 | 20 combined enriched closed trades | 40 combined enriched closed trades |
| Mid frequency, such as H8/H12/D1 | 10 combined enriched closed trades | 20 combined enriched closed trades |
| Sparse, such as W1 | 5 combined enriched closed trades | 10 combined enriched closed trades |

Two weak weeks can justify monitoring or investigation when both FTMO and IC
show the same issue. Three to four weak weeks can justify candidate research if
the same timeframe/setup/regime repeatedly underperforms.

Sparse timeframes can trigger research with fewer live trades, but they require
stronger recent-window and full-history backtest confirmation before any live
deployment.

## Safety Rules

- Do not change live strategy behavior during diagnostic/reporting work.
- Do not add indicator or percentile calculations to the live runner loop.
- Do not expand high-volume `market_snapshot` rows.
- Do not scan active production journals with unsafe file-open semantics.
- Use bounded/tail reads and `FileShare.ReadWrite` for production-adjacent
  journal/state reads.
- Follow any production-adjacent remote journal/state read with a fresh
  dual-VPS status packet.
- Do not run a manual live process while scheduled live runners are active.
- Do not touch MT5 orders, positions, history, live state, or live journals
  unless the user approves a separate operator plan.
- Treat logging deploys as operational changes requiring explicit restart and
  verification.
- Treat reporting/docs-only changes as local-only unless the user explicitly
  asks to deploy docs to the VPS checkout.

## How To Run

Build a diagnostic report from local journal copies:

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl"
```

Diagnostics accept archived, historical, synthetic, or safely collected local
evidence. Prefer `scripts/collect_lpfs_live_journal_snapshots.py` for
production journal evidence, capture a fresh dual-VPS status packet after the
collection, and never pass an active VPS runtime journal path to the diagnostic
builder. Compact summaries are stricter: they require a collector-produced,
manifest-backed `--journal-snapshot`.

Optional explicit candle roots require provenance. For FTMO/IC live attribution,
only use lane-authoritative VPS/broker-feed candle snapshots. Do not use local
workstation MT5 candles as FTMO or IC indicator/structure/momentum/volume truth.

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl" `
  --candle-root "FTMO=path\to\ftmo_vps_broker_feed_candles" `
  --candle-source-provenance "FTMO=vps_lane_broker_feed" `
  --candle-root "IC=path\to\ic_vps_broker_feed_candles" `
  --candle-source-provenance "IC=vps_lane_broker_feed"
```

Focused verification for this work:

```powershell
.\venv\Scripts\python -m unittest `
  strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging `
  strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary `
  strategies.lp_force_strike_strategy_lab.tests.test_live_weekly_performance `
  strategies.lp_force_strike_strategy_lab.tests.test_live_gate_attribution `
  strategies.lp_force_strike_strategy_lab.tests.test_dry_run_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_executor
```

Full core verification:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Read-only live status, when needed:

```powershell
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

## Output Expectations

`scripts/build_lpfs_trade_diagnostics.py` writes to:

```text
reports/live_ops/lpfs_trade_diagnostics/<timestamp>/
```

Expected files:

- `closed_trade_diagnostics.csv`: closed live trades with result fields,
  flattened diagnostics, offline time/session/setup buckets, execution buckets,
  recent-window flags, and candle-derived regimes only when the candle source is
  explicitly proven for the lane.
- `backtest_diagnostics.csv`: benchmark backtest trades enriched with matching
  offline fields where available.
- `backtest_comparison.csv`: live-versus-backtest grouped comparisons across
  lane, timeframe, symbol, side, session, weekday, setup buckets, execution
  buckets, and candle regimes.
- `timeframe_confluence.csv`: FTMO/IC timeframe confluence rows, live/backtest
  deltas, sample thresholds, and current research action.
- `summary.md`: compact human-readable report summary.

The report is not expected to recommend automatic live changes. It should
surface hypotheses and evidence quality.

## Current Blockers

- Current enriched live closed-trade sample is strong enough for offline
  candidate research, but still too small and too mixed for a live strategy
  change.
- Production diagnostic rows are only useful after enough real lifecycle and
  close events accumulate.
- The 2026-05-30 generated weekly dashboard hit an FTMO fetch timeout, so that
  historical FTMO weekly result must be read from the local lifecycle-snapshot
  review. The current weekly strategy-review path has since been hardened with
  bounded fetches and explicit `analysis_eligible` / `coverage_status` fields;
  use the latest eligible packet for current weekly evidence.
- True 10-year tick-level Bid/Ask/order-book data is not available from the
  current IC terminal; candle data and M1 spread fields are available.
- The current diagnostic report supports offline indicator/regime analysis, but
  any actual heuristic candidate still needs separate research/backtest work.
- The current diagnostic report preserves sizing scale per enriched trade but
  does not yet derive `policy_id` from `configs/live_policy_ledger.csv` or
  automatically produce policy-epoch comparison groups.
- Raw ignored report packets are local evidence, not commit material. Commit
  only reviewed scripts, tests, docs, schemas, and small sanitized summaries.

## Open Questions

- How many enriched closed live trades will accumulate per timeframe over the
  next several weeks?
- Are the first-month FTMO and IC losses driven by the same weak buckets or by
  broker/feed/execution divergence?
- Are weak weeks explained by sample variance, setup quality, execution,
  broker/feed divergence, timeframe/session concentration, or market regime?
- Which constructive improvements, if any, can improve recent performance
  without damaging full-history robustness?
- Whether future reports need safer automated journal-copy tooling or whether
  manual safe collection is enough.

## Testing Status

For this 2026-06-27 docs/research handoff update, run the docs/status
verification required by `AGENTS.md`:

- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages`
- `git diff --check`
- first-read drift audit over `SESSION_HANDOFF.md`, root `PROJECT_STATE.md`,
  LPFS `START_HERE.md`, LPFS `PROJECT_STATE.md`, and this file.

Documentation-only edits here do not change runtime behavior. If any
implementation file changes again, rerun focused tests and core coverage before
handoff.

## Recommended Next Implementation Steps

1. Keep the live runners unchanged.
2. Use the maintained 2026-07-05 candidate matrix as the current research
   queue and keep the 2026-06-27 readiness packet as historical context for
   how the H8 compressed-risk watch item was promoted.
3. Track H8 compressed risk (`timeframe=H8`, `risk_atr_bucket=lt_0p5`) and its
   low-spread intersection, but keep the analysis portfolio-wide by also
   reviewing symbol, side, session/hour, weekday, spread-risk, risk/ATR, and
   account-outcome divergence.
4. Do not resurrect the simple H8 low-spread-only filter unless new evidence
   overturns the 2026-06-27 rejection.
5. Segment IC analysis by the historical scale-2 and active scale-1 policy
   epochs from `configs/live_policy_ledger.csv`; do not attribute PnL-size
   changes to strategy quality.
6. Preserve and extend the hardened weekly strategy-review path: use eligible
   packets where `analysis_eligible=true` and `coverage_status=complete`, and
   use bounded/local lifecycle evidence when remote fetch coverage is
   incomplete.
7. Use skipped-opportunity diagnostics when judging IC/FTMO comparability:
   current safe evidence shows four IC `volume_below_min` skips and no FTMO
   broker-minimum skips in the July 4 filtered lifecycle window. Treat these
   as account-size comparability evidence, not closed-trade performance.
8. If the H8 compressed-risk candidate repeats, narrow it until the 12M
   guardrail no longer contradicts the rule and long-history removal breadth is
   within the preferred 15% or maximum 20% boundary.
9. If evidence thresholds are met, create a separate formal strategy-change
   proposal for one small reversible heuristic candidate, with recent 3/6/12
   month support, FTMO/IC confluence or explained divergence, and full-history
   guardrails.
10. Request explicit user approval before any live strategy-change deployment.

## Next Codex Handoff

Fresh-chat prompt:

```text
Read SESSION_HANDOFF.md, strategies/lp_force_strike_strategy_lab/START_HERE.md,
docs/lpfs_strategy_improvement_workflow.md,
docs/lpfs_strategy_iteration_context.md, and docs/lpfs_diagnostic_logging.md.
Continue the LPFS diagnostic reporting and evidence-gated strategy-improvement
workflow from the current git state. Treat the maintained 2026-07-05 candidate
matrix packet as the current research queue: H8 compressed risk remains the
leading active research candidate, broad long/setup-age/structure buckets are
diagnostic only, incomplete candle/spread factor coverage is a data gap, and no
live strategy change is approved. Keep the 2026-06-27 readiness packet as
historical context for the H8 compressed-risk watch item and the rejected H8
low-spread-only filter. Use the workflow doc for cadence, trigger/triage
outcomes, candidate-register rules, data-gap escalation, and human-operator
responsibilities. Do not change live strategy behavior, entry/exit logic, risk
settings, broker/execution logic, config defaults, live state, journals, MT5
orders, or MT5 positions.
```

Before making any change, the new chat should run `git status --short`, inspect
the intended files, and state whether the task is docs-only, reporting-only, or
production-adjacent.
