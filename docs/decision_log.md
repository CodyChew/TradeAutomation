# TradeAutomation Decision Log

This is a concise index of durable material decisions. Detailed evidence,
role outputs, test results, packet hashes, and objections belong in the linked
`docs/reviews/` artifact, PR body, or deployment packet.

Do not use this file as live broker truth. Current live status still comes from
fresh status packets, MT5 broker facts, runtime state, and the first-read docs
listed in `AGENTS.md`.

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
