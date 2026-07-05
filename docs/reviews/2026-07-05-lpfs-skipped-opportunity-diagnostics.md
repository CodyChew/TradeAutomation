# LPFS Skipped Opportunity Diagnostics Gate

Date: 2026-07-05 ICT.

## Change Type

Material journal/report evidence change.

This change is offline-only. It does not authorize or implement any live
strategy, risk, sizing, SL/TP, broker-send, scheduler, VPS, MT5, config,
runtime-state, journal, reconciliation, canary, or broker action.

## Purpose

The July 2026 strategy workflow needs to distinguish three things:

1. executed closed trades;
2. execution-quality or retryable blocks such as spread/session conditions;
3. valid strategy signals that were not orderable because account/broker
   minimum volume exceeded the calculated risk size.

`volume_below_min` belongs in the third group. It affects FTMO/IC comparability
and account-size policy analysis, but it must not be counted as a closed trade
or used as approval for a sizing/config change.

## Lead Owner And Reviewers

- Lead owner: LPFS Strategy Improvement Agent.
- Documentation and Workflow Agent: classified this as a journal/report
  evidence change and required clear wording that it is diagnostic-only,
  separate from closed-trade performance, and not live sizing/config approval.
- Independent Issue Verifier / Data Integrity Reviewer: confirmed the gap is
  real and occurred in copied local evidence; required deduplication of direct
  decision rows and notification rows; required retryable spread/session blocks,
  `order_check_failed`, `order_rejected`, closed trades, partial closes, and
  final closes to remain out of the focused skipped-opportunity dataset.

## Inputs Preserved

- Filtered FTMO lifecycle copy:
  `reports/live_ops/lpfs_strategy_diagnostics_refresh/20260704_195931/filtered_lifecycle/ftmo_filtered_lifecycle.jsonl`.
- Filtered IC lifecycle copy:
  `reports/live_ops/lpfs_strategy_diagnostics_refresh/20260704_195931/filtered_lifecycle/ic_filtered_lifecycle.jsonl`.
- Output packet:
  `reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`,
  manifest SHA-256
  `ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.

The current packet found `4` IC `volume_below_min` skipped opportunities and
`0` FTMO broker-minimum skips in the safe July 4 filtered lifecycle copies.

## Stop Conditions Checked

- No live operation is in scope.
- No broker, MT5, VPS, scheduled task, runtime state, production journal, or
  config mutation is in scope.
- No strategy filter, risk haircut, minimum-volume override, or live policy
  epoch is approved by this change.
- `volume_below_min` rows must be deduplicated across direct decision and
  notification row forms.
- Retryable spread/session blocks and broker rejection rows must not enter the
  skipped-opportunity dataset.
- Skipped opportunities must record `closed_trade_count_impact=0`.

## Verification Plan

- Focused skipped-opportunity builder tests.
- Adjacent diagnostic/gate attribution tests.
- Dashboard page tests and process audit because first-read/workflow docs are
  updated.
- Full LPFS unittest suite and core coverage if the reporting surface changes
  beyond this isolated builder.
- `git diff --check`.
- Scope audit proving changes are limited to offline reporting tooling, tests,
  review docs, and first-read/workflow documentation.

## Verification Performed

- Focused skipped-opportunity diagnostics tests: `4 OK`.
- Adjacent diagnostic/gate attribution tests: `21 OK`.
- Dashboard page tests: `36 OK`.
- Repo process audit: `pass`.
- Full LPFS unittest suite: `575 OK`.
- Core coverage: `7185 statements`, `2424 branches`, `100.00%`.
- `git diff --check`: passed with line-ending warnings only.

Scope audit: offline reporting builder, focused tests, review docs,
first-read/workflow docs, decision log, and evidence catalog only. No live
executor behavior, strategy logic, risk sizing, SL/TP logic, broker-send,
config, scheduler, watchdog, VPS-local file, runtime state, production journal,
evidence packet tracking, broker artifact, reconciliation, canary, or recovery
behavior changed.
