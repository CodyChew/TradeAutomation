# TradeAutomation Decision Log

This is a concise index of durable material decisions. Detailed evidence,
role outputs, test results, packet hashes, and objections belong in the linked
`docs/reviews/` artifact, PR body, or deployment packet.

Do not use this file as live broker truth. Current live status still comes from
fresh status packets, MT5 broker facts, runtime state, and the first-read docs
listed in `AGENTS.md`.

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
