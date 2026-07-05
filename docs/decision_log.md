# TradeAutomation Decision Log

This is a concise index of durable material decisions. Detailed evidence,
role outputs, test results, packet hashes, and objections belong in the linked
`docs/reviews/` artifact, PR body, or deployment packet.

Do not use this file as live broker truth. Current live status still comes from
fresh status packets, MT5 broker facts, runtime state, and the first-read docs
listed in `AGENTS.md`.

## 2026-07-05 - Add LPFS Skipped Opportunity Diagnostics

Decision:

- Add `scripts/build_lpfs_skipped_opportunity_diagnostics.py` as the maintained
  offline builder for broker-minimum skipped-opportunity diagnostics.
- Treat `volume_below_min` as a strategy-relevant non-executed setup class,
  deduplicated by lane, signal key, and rejection reason.
- Keep retryable spread/session blocks, `order_check_failed`,
  `order_rejected`, closed trades, partial closes, and final closes out of the
  skipped-opportunity dataset; those remain covered by gate attribution,
  lifecycle summaries, and broker/close reports.
- Write ignored packets under
  `reports/live_ops/lpfs_skipped_opportunity_diagnostics/` with source journal
  hashes, event rows, reason summaries, manifest, and explicit non-actions.

Reason:

- IC can miss valid LPFS forward-test setups because the account/broker minimum
  lot size blocks order intent. Strategy analysis needs to separate that
  account-size comparability issue from executed closed-trade performance and
  from spread or market-session execution rejects.

Evidence:

- Review: `docs/reviews/2026-07-05-lpfs-skipped-opportunity-diagnostics.md`.
- Current packet:
  `reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`,
  manifest SHA-256
  `ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.

Follow-up:

- Use the maintained skipped-opportunity packet alongside closed-trade
  diagnostics and candidate matrices when evaluating IC/FTMO comparability or
  account-size policy effects. Do not treat skipped opportunities as closed
  trades or as live sizing-change approval.

## 2026-07-05 - Add Offline LPFS Candidate Matrix Builder

Decision:

- Add `scripts/build_lpfs_candidate_backtest_matrix.py` as the maintained
  offline builder for LPFS candidate backtest matrices.
- Keep current candidate definitions in research-only config
  `configs/strategy_research/lpfs_candidate_matrix_current.json`.
- Require source diagnostics and optional factor-attribution manifests to
  validate file hashes before reading inputs.
- Write ignored packets under
  `reports/live_ops/lpfs_candidate_backtest_matrix/` with candidate
  definitions, live context, 3/6/12 month and long-history windows, guardrails,
  overlap/confound rows, summary, manifest, and explicit non-actions.
- Mark incomplete factor coverage as a data gap so candle-derived or
  spread-risk candidates cannot become proposal-grade evidence by accident.

Reason:

- The 2026-07-05 candidate matrix identified useful research candidates, but it
  was generated ad hoc. Strategy improvement needs a reproducible path before
  any filter or risk-haircut proposal can be trusted.

Evidence:

- Review: `docs/reviews/2026-07-05-lpfs-candidate-matrix-builder.md`.

Follow-up:

- Use the maintained builder for future candidate matrices.
- Pair candidate matrices with skipped-opportunity diagnostics when a candidate
  may be distorted by account-size or broker-minimum skips.

## 2026-07-04 - Add LPFS Lane Candle Snapshot Workflow

Decision:

- Add a read-only LPFS lane candle snapshot workflow for FTMO/IC
  broker-feed market-context enrichment.
- Keep workstation-local MT5 candle roots blocked for live-lane
  RSI/MACD/EMA/volume/structure conclusions.
- Default lane snapshots to a recent one-year window; require an intentional
  argument for larger lane-feed pulls.
- Run the generic MT5 dataset puller with `allow_symbol_select=false` from the
  lane collector, so hidden symbols become `DATA_GAP` instead of mutating
  terminal symbol visibility.
- Align IC lane broker-feed validation with the current preserved live status
  evidence: `ICMarketsSC-MT5-2` / `Raw Trading`.

Reason:

- The candle-provenance guardrail created a safe consumer, but there was no
  maintained producer for lane-authoritative candle roots. Strategy attribution
  needs a reproducible source before using candle-derived indicators or
  structure/momentum/volume buckets.

Evidence:

- Review: `docs/reviews/2026-07-04-lpfs-lane-candle-snapshot-workflow.md`.

Follow-up:

- Run the collector only as an approved read-only, production-adjacent data
  collection step. If the packet fails validation, classify the research pass
  as `DATA_GAP` and do not use local workstation candles as a substitute.

## 2026-07-04 - Tighten LPFS Research Data Provenance Ownership

Decision:

- Keep the existing TradeAutomation role roster.
- Do not add a new standing team role for data provenance.
- Make research-data provenance a required preflight owned by the LPFS Strategy
  Improvement Agent for every diagnostics, factor-attribution,
  live-vs-backtest, or indicator-tagged strategy-analysis run.
- Assign Documentation and Workflow Agent ownership of the standing provenance
  rules and source maps.
- Require Independent Issue Verifier review for provenance failures, repair
  claims, or production-impact claims.
- Require Repo Auditor checks that research packets and builders expose enough
  source metadata.

Reason:

- The candle-provenance incident showed a responsibility gap, not a manpower
  gap. The right fix is a hard pre-analysis checkpoint and explicit ownership,
  not a broader process ceremony.

Evidence:

- Review: `docs/reviews/2026-07-04-lpfs-research-data-provenance-ownership.md`.

Follow-up:

- Future strategy-analysis runs should stop as `DATA_GAP` when required input
  provenance is missing, unverified, cross-lane, stale, or quarantined.

## 2026-07-04 - Add LPFS Candle Provenance Guardrail

Decision:

- Remove implicit workstation-local candle roots from LPFS trade diagnostics.
- Require every candle enrichment source to be passed as `LANE=path` with an
  explicit provenance label.
- Treat workstation-local or unverified candle sources as blocked for
  RSI/MACD/EMA/volume/structure enrichment.
- Validate `vps_lane_broker_feed` candle manifests against the expected lane
  broker server/company metadata before allowing strategy-analysis enrichment.
- Make downstream factor attribution drop candle-derived factor dimensions
  unless the source diagnostics manifest proves safe candle provenance.
- Quarantine candle-derived conclusions from the 2026-06-27 and 2026-07-04
  diagnostics packets that were generated before this guardrail.

Reason:

- A diagnostics refresh used local workstation MT5 candle data for lane
  attribution. That source is not FTMO/IC lane-authoritative and can mix broker
  feeds, which weakens strategy-analysis correctness even though broker/live
  execution was not mutated.
- Strategy research needs reproducible, lane-provenanced market context before
  it can justify filters or heuristic candidates.

Evidence:

- Review: `docs/reviews/2026-07-04-lpfs-candle-provenance-guardrail.md`.

Follow-up:

- Regenerate candle-derived diagnostics only from validated FTMO/IC
  lane-authoritative candle sources or from explicitly labeled backtest
  reference fixtures.
- Do not use quarantined candle factors from old packets for strategy
  conclusions.

## 2026-07-04 - Add Offline LPFS Factor Attribution Builder

Decision:

- Add `scripts/build_lpfs_factor_attribution.py` as the maintained offline
  builder for price-structure, momentum, volume, time/session, core cohort, and
  cross-lane factor matrices from existing LPFS trade-diagnostics packets.
- Keep outputs under ignored `reports/live_ops/lpfs_factor_attribution/` with
  manifests, input fingerprints, row counts, freshness metadata, caveats, and
  explicit non-actions.
- Preserve the boundary that factor rows are research-only and do not approve
  live strategy filters or production changes.

Reason:

- The strategy-improvement workflow needs repeatable factor attribution, not
  ad hoc summaries, when FTMO or IC forward evidence is weak.
- The builder lets future agents compare lane-first live cohorts against 3/6/12
  month and long-history backtest diagnostics while preserving data-quality
  caveats.

Evidence:

- Review: `docs/reviews/2026-07-04-lpfs-offline-factor-attribution-builder.md`.

Follow-up:

- Refresh safe local journal snapshots and candle roots before using this
  builder to attribute later weekly packets such as the 2026-07-04 packet.

## 2026-07-04 - Add Context Architecture And Evidence Catalog

Decision:

- Add `docs/context_architecture.md` as the source-of-truth routing map for
  first-read docs, history, review artifacts, and role ownership.
- Add `docs/evidence_catalog.md` as the durable packet/hash index for important
  operational, strategy, deployment, and process evidence.
- Move old LPFS operational narratives into `docs/history/lpfs_operations.md`
  and LPFS experiment chronology into
  `strategies/lp_force_strike_strategy_lab/docs/experiment_history.md`.
- Compress `PROJECT_STATE.md`, `SESSION_HANDOFF.md`, and LPFS
  `PROJECT_STATE.md` into current-state control files that link to the new
  owners.
- Harden `scripts/audit_repo_process.py` to check required context anchors,
  evidence-index fields, and stale current-state phrases.

Reason:

- The oversized current-state files mixed current handoff, live-safety facts,
  deployment history, experiment history, packet inventories, and old prompts.
  That made stale-current drift more likely as LPFS evidence grew.
- A separate evidence catalog preserves packet paths, hashes, status labels,
  questions answered, and non-actions without committing ignored raw evidence.

Evidence:

- Review: `docs/reviews/2026-07-04-context-architecture-hardening.md`.

Follow-up:

- Keep first-read files short and current. Add packet details to
  `docs/evidence_catalog.md` and historical narratives to focused history or
  review artifacts.

## 2026-07-04 - Add Repo Maintenance Policy And Process Audit

Decision:

- Add `docs/repo_maintenance_policy.md` as the source-of-truth boundary and
  current-state maintenance policy for TradeAutomation.
- Add `scripts/audit_repo_process.py` as a lightweight repo/process audit for
  required handoff files, current-state size warnings, obvious secret patterns,
  tracked runtime/evidence artifacts, and key doc references.
- Keep current-state size excesses as warnings for now because safety-critical
  context should be archived progressively, not deleted in a broad sweep.
- Keep the existing TradeAutomation role model instead of adding DayTrading's
  separate Documentation Steward or Workflow Auditor roles.

Reason:

- TradeAutomation already has strong LPFS-specific live-safety gates, but its
  onboarding and process docs need a clearer maintenance boundary and a
  runnable repo-health check.
- DayTrading's concise current-state and docs-audit pattern is useful, while
  its larger role roster would add unnecessary bureaucracy here.

Evidence:

- Review: `docs/reviews/2026-07-04-repo-structure-workflow-hardening.md`.

Follow-up:

- Use `scripts/audit_repo_process.py` before future material onboarding,
  workflow, first-read, or process changes.
- Archive duplicated historical detail out of oversized current-state files
  opportunistically during future maintenance work.
