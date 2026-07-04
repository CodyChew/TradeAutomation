# LPFS Command Center Dashboard Review

Date: 2026-07-04 ICT

## Summary

Decision: approved for a narrow additive implementation after resolving role
review objections.

This review covers a new generated static dashboard,
`docs/lpfs_command_center.html`, backed by
`configs/dashboards/lpfs_command_center.json` and
`scripts/build_lpfs_command_center.py`. The page summarizes existing LPFS
evidence and links to drilldowns. It does not collect live data, access VPS/MT5,
read runtime journals, mutate broker state, change strategy logic, or approve
any live operation.

## DayTrading Lessons Learned

Reference inspected:

- `C:\Trading\DayTrading\src\daytrading\research_dashboard.py`
- `C:\Trading\DayTrading\src\daytrading\session_visuals.py`
- `C:\Trading\DayTrading\docs\reviews\*dashboard*`
- `C:\Trading\DayTrading\runs\_state\research_dashboard.html`

Useful patterns to adopt:

- Put current candidate/test labels before dense history.
- Show caveats and promotion boundaries as first-class UI, not footnotes.
- Separate current candidates, research-only variants, rejected ideas, and
  live/no-live status.
- Show evidence windows and sample-size/coverage caveats beside metrics.
- Put concise status and next action before historical drilldowns.

Patterns not copied:

- The large all-in-one research HTML with heavy per-trade visual drilldowns.
- Direct DayTrading visual styling or research model assumptions.
- Any automatic live refresh behavior.

## Role Feedback

### Main Orchestrator

1. Essential information: source mode, generated timestamp, packet paths/hashes,
   live-safety boundary, role ownership, and verification.
2. Hard to interpret: current LPFS state is split across first-read docs,
   weekly dashboard, live ops page, and ignored packets.
3. First screen: source/freshness, operating boundary, weekly eligibility,
   primary outcome, and next responsible action.
4. Drilldown: evidence catalog, live ops guide, weekly dashboard, strategy
   context, diagnostic logging, and decision/review artifacts.
5. Risk: treating a static dashboard as broker truth.
6. Resources: existing roles are enough if a Dashboard/UI owner checklist is
   documented for this surface.
7. Needed change: use the material change gate and keep integration in the main
   thread.
8. Decision: approve after role review and tests.

### LPFS Strategy Improvement Agent

1. Essential information: active strategy, current research candidates, rejected
   hypotheses, weekly outcome, account-outcome caveats, and next action.
2. Hard to interpret: weak performance can be hidden inside dense weekly rows.
3. First screen: primary outcome `WATCH`, current candidate queue, and no live
   strategy change approved.
4. Drilldown: cohort matrix, indicator-tagging plan, live-vs-backtest
   attribution, and policy-epoch notes.
5. Risk: presenting a research candidate as a live filter.
6. Resources: strategy workflow exists, but dashboard should make ownership
   visible.
7. Needed change: show the strategy agent's responsibility to notice weakness,
   diagnose, test, reject, and propose.
8. Decision: approve after explicit no-live-change wording.

### Documentation And Workflow Agent

1. Essential information: source-of-truth links, freshness labels, packet
   hashes, and current/historical boundaries.
2. Hard to interpret: stable `docs/live_weekly_performance.html` can lag latest
   ignored weekly packets.
3. First screen: generated time, latest packet path/hash, and fresh dual-VPS
   status requirement.
4. Drilldown: evidence catalog, decision log, strategy iteration context, and
   live ops guide.
5. Risk: stale generated HTML overriding indexed packet evidence.
6. Resources: sufficient, with dashboard freshness checklist required.
7. Needed change: create this dated review artifact before implementation.
8. Decision: request changes, resolved by source-first config/builder plus
   freshness labels.

### Repo Auditor

1. Essential information: no runtime/config/journal/evidence-packet mutation in
   tracked diff.
2. Hard to interpret: generated artifact changes are easy to hand-edit without
   source updates.
3. First screen: static/generated warning and evidence lineage.
4. Drilldown: builder/config/source path and verification commands.
5. Risk: broad docs churn, stale first-read claims, or accidental tracked
   report artifacts.
6. Resources: enough if process audit and scope audit are run.
7. Needed change: keep generated output source-backed and run repo process
   audit.
8. Decision: approve after scope audit.

### Reliability Reviewer

1. Essential information: lane separation, broker/status truth boundary,
   recovery disabled, mismatch counts, telemetry failures, and fresh-status
   stop condition.
2. Hard to interpret: static pages can be mistaken for live broker state.
3. First screen: "static generated, not broker truth" plus fresh status
   requirement.
4. Drilldown: `Get-LpfsDualVpsStatus.ps1`, live ops guide, packet path/hash.
5. Risk: dashboard language causing operator action from stale evidence.
6. Resources: enough if live-safety wording remains explicit.
7. Needed change: no auto-refreshing live-status panel without separate
   approval.
8. Decision: request changes, resolved by static-only builder and warning.

### Independent Issue Verifier

1. Essential information: evidence classification, packet completeness, and
   production-impact boundaries.
2. Hard to interpret: latest generated docs page versus latest ignored packet.
3. First screen: packet-only truth label and `analysis_eligible` /
   `coverage_status`.
4. Drilldown: packet manifests, hashes, and source rows.
5. Risk: derived R/PnL labels treated as broker-authoritative facts.
6. Resources: enough if data classification fields remain visible.
7. Needed change: preserve evidence fields and avoid unverified claims.
8. Decision: approve after validity fields are visible.

### QA / Test Engineer

1. Essential information: shared header/nav, no script, no live-read behavior,
   source/freshness warning, eligibility fields, packet links, and no-live
   strategy approval.
2. Hard to interpret: the page did not exist and had no contract tests.
3. First screen: static/read-only warning, FTMO/IC status, weekly eligibility,
   and next action.
4. Drilldown: source paths, dashboard links, packet references.
5. Risk: untested generated page or broken navigation.
6. Resources: existing dashboard tests are good but command-center-specific
   tests are required.
7. Needed change: add tests for index link, command center contract, evidence
   fields, drilldowns, and no `<script>`.
8. Decision: request changes, resolved by test additions.

### Risk Manager

1. Essential information: no approved risk/sizing change, current pending and
   active exposure counts, recovery disabled, and risk caveats.
2. Hard to interpret: positive R/PF or broker PnL can be read without account
   outcome caveats.
3. First screen: explicit no risk/sizing change and fresh status requirement.
4. Drilldown: policy ledger, account-outcome attribution, and risk epoch notes.
5. Risk: dashboard creates pressure to change risk from a single weak week.
6. Resources: sufficient with explicit risk checklist.
7. Needed change: include "not approved" list and account outcome caveats.
8. Decision: approve after no-risk-change boundary is present.

### Strategy Trader

1. Essential information: what is working, what is weak, current test, and next
   responsible action.
2. Hard to interpret: dense weekly rows do not say what a trader should watch.
3. First screen: FTMO, IC, combined performance plus current watch items.
4. Drilldown: symbol/timeframe/side/session breakdowns and rejected ideas.
5. Risk: overfitting from one-lane or one-week weakness.
6. Resources: enough if the dashboard pushes research before live changes.
7. Needed change: add candidate and rejected-hypothesis cards.
8. Decision: approve after candidate status is clearly research-only.

### Data Engineer

1. Essential information: source paths, hashes, schema/field names,
   completeness, and coverage status.
2. Hard to interpret: evidence can exist in ignored packets without tracked
   generated pages being refreshed.
3. First screen: source mode, packet path/hash, weekly summary hash.
4. Drilldown: evidence catalog and report packet paths.
5. Risk: dashboard inventing facts not backed by packet/config.
6. Resources: enough for static config; future live-refresh would need a
   separate data pipeline review.
7. Needed change: config-driven page and deterministic builder.
8. Decision: approve after source config and generated output are reviewed
   together.

### Dashboard/UI Owner

Status: proposed lightweight ownership responsibility for this dashboard
surface, not a new live-approval authority.

1. Essential information: current status, current candidate, weak/working
   readout, next action, evidence quality, and no-live boundary.
2. Hard to interpret: existing pages require the user to assemble meaning from
   multiple long documents and dense tables.
3. First screen: source/freshness, live/ops boundary, weekly eligibility, lane
   snapshots, primary outcome.
4. Drilldown: history, benchmarks, packet links, and detailed guides.
5. Risk: visual simplification hiding caveats.
6. Resources: enough if the checklist is kept in the config/review artifact.
7. Needed change: keep command center additive and concise.
8. Decision: approve after tests verify caveats and links.

## Objections And Resolutions

- Objection: Proposed files do not exist yet.
  Resolution: Add config, builder, generated page, index link, and tests.
- Objection: Static dashboard may be mistaken for broker truth.
  Resolution: First-screen warning says fresh dual-VPS/MT5 proof is required
  before live operations.
- Objection: Stable generated weekly page may lag ignored packets.
  Resolution: Show source packet path/hash and label stable weekly page as a
  drilldown that may lag.
- Objection: Incomplete evidence could be consumed as valid performance.
  Resolution: Render `analysis_eligible`, `coverage_status`, and
  `performance_confidence` in first weekly section.
- Objection: H8 candidate could be read as an approved live filter.
  Resolution: Candidate cards say research-only, and "not approved" list blocks
  live strategy/risk changes.
- Objection: Generated HTML could drift from source.
  Resolution: Source config plus builder; generated HTML must not be hand
  edited.
- Objection: Page lacks test coverage.
  Resolution: Add dashboard tests for link, static contract, evidence fields,
  drilldowns, and no `<script>`.

## Final Agreed Structure

1. Source And Freshness.
2. Current Operating Boundary.
3. Can This Packet Be Analyzed.
4. Triage Outcome And Next Action.
5. Strategy Research Queue.
6. Evidence Packets And Drilldowns.
7. Ownership And Refresh Workflow.

## Safety Statement

This is a non-operational generated-dashboard change. It does not access VPS,
MT5, Task Scheduler, kill switches, runtime state, production journals, broker
orders, broker positions, local configs, or report packets. It does not change
strategy behavior, risk sizing, entry/exit rules, spread gates, market
recovery, broker-send logic, scheduler/watchdog behavior, or deployment state.

## Verification Commands

```powershell
.\venv\Scripts\python scripts\build_lpfs_command_center.py
.\venv\Scripts\python scripts\build_lp_force_strike_index.py
.\venv\Scripts\python scripts\audit_repo_process.py
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Core coverage is not required unless implementation expands into reusable
parser/reporting logic or strategy package behavior.
