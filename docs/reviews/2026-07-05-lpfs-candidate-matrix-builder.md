# LPFS Candidate Matrix Builder Gate

Date: 2026-07-05 ICT.

## Change Type

Material reporting and strategy-research tooling change.

This change is offline-only. It does not authorize or implement any live
strategy, risk, sizing, SL/TP, broker-send, scheduler, VPS, MT5, config,
runtime-state, journal, reconciliation, canary, or broker action.

## Purpose

The July 2026 strategy review produced a valid lane-authoritative candle packet,
trade diagnostics packet, factor-attribution packet, and an ad hoc candidate
matrix. The ad hoc matrix was useful but not maintainable enough for repeated
strategy decisions.

The purpose of this change is to make the candidate matrix reproducible:

- candidate definitions live in a research-only config;
- the builder validates source manifests and hashes before reading inputs;
- outputs include candidate definitions, live context, backtest windows,
  guardrails, overlap/confound rows, summary, and manifest hashes;
- incomplete backtest factor coverage is explicit and cannot become proposal
  evidence by accident.

## Lead Owner And Reviewers

- Lead owner: LPFS Strategy Improvement Agent.
- Reviewers used before implementation:
  - Independent Issue Verifier / Data Integrity Reviewer: approved July 4
    inputs for offline candidate research with guardrails and required the new
    matrix to avoid quarantined workstation-candle packets.
  - Strategy Improvement side reviewer: prioritized H8 compressed risk and
    rejected broad H8, long-only, time-only, and standalone candle-factor
    filters as deployable rules.
  - Data Engineer / QA reviewer: identified the missing maintained candidate
    matrix builder and recommended packet columns, guardrails, and manifest
    contents.

## Inputs To Preserve

- Lane candle snapshot:
  `reports/live_ops/lpfs_lane_candle_snapshots/20260704_182810`
  with manifest SHA-256
  `e7ae1ecf3a0957fea3493ab5afba8799b302f70f7574e0691ca26b9f9faad730`.
- Trade diagnostics:
  `reports/live_ops/lpfs_trade_diagnostics/20260704_190500`
  with manifest SHA-256
  `253017ef4b796fbd114e4b38f9f6f9078a4add81902db698979eff25fc269e31`.
- Factor attribution:
  `reports/live_ops/lpfs_factor_attribution/20260704_191500`
  with manifest SHA-256
  `b7b0e444b819fb28174c6540294c58d4c2a7da9e38751c3c8acc4deb5b4e0434`.

Older local-workstation candle packets remain quarantined for candle-derived
strategy conclusions.

## Stop Conditions Checked

- No live operation is in scope.
- No broker, MT5, VPS, scheduled task, runtime state, production journal, or
  config mutation is in scope.
- No strategy filter, risk haircut, or live policy epoch is approved by this
  change.
- Candle-derived rows must not claim long-history guardrails when the required
  factor fields are missing or incomplete.
- The builder must fail closed on missing or mismatched source manifest hashes.

## Verification Plan

- Focused candidate matrix builder tests.
- Adjacent factor-attribution tests.
- `git diff --check`.
- Scope audit proving changes are limited to offline research tooling, tests,
  research config, and documentation.

If shared reporting behavior changes unexpectedly, run the full LPFS unittest
suite and core coverage.

