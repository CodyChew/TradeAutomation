# TradeAutomation Evidence Catalog

Last updated: 2026-07-05 ICT.

This catalog indexes important ignored report packets, deployment proofs,
research packets, and reviewed artifacts. It preserves paths and hashes without
tracking raw runtime evidence. Packet facts are historical unless a fresh
status packet or broker-authoritative read verifies them for the current
operation.

This file does not authorize live operations, broker actions, runtime-state
edits, journal edits, report regeneration, or strategy changes.

## Schema

Each evidence row should preserve:

| Field | Meaning |
| --- | --- |
| `id` | Stable short identifier for cross-reference. |
| `date` | Packet or review date in local project context. |
| `domain` | Operations, strategy research, reporting, deployment, or process. |
| `lane` | FTMO, IC, dual, local, or repo. |
| `status` | Pass, warning, rejected, active candidate, historical, or review. |
| `current_label` | `current`, `historical`, `superseded`, or `reference`. |
| `path` | Ignored packet path or tracked review/doc path. |
| `hash_or_manifest` | SHA-256, manifest hash, or review link. |
| `question_answered` | What the packet proves or preserves. |
| `non_actions` | Explicitly skipped live/config/strategy/broker actions. |
| `canonical_reference` | Current tracked doc that owns the interpretation. |

Rules:

- Use `current_label=current` sparingly for the latest first-read context
  pointer.
- Broker exposure counts in catalog rows are historical packet facts.
- Keep rejected hypotheses and blocked candidates discoverable.
- Raw packets remain in ignored `reports/`, runtime evidence folders, or
  operator evidence roots.

## Current LPFS Context Packets

| id | date | domain | lane | status | current_label | path | hash_or_manifest | question_answered | non_actions | canonical_reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lpfs-weekly-20260627 | 2026-06-27 | Strategy review | dual | Eligible, complete | current | `reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107` | `weekly_summary.csv` SHA-256 `49eb0b436953fbfee74193acf59e874d4f54b7d36044494d24eb77405347dfe1` | Latest complete weekly evidence: FTMO `+1.99R`, IC `-4.84R`, combined `-2.85R`; supports offline research, not a live rule change. | No live strategy, risk, sizing, execution, broker, config, journal, or runtime change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-status-20260627 | 2026-06-27 | Live status | dual | Pass | current | `reports/live_ops/lpfs_dual_vps_status_20260627_080624.md` | SHA-256 `b56f0ad7bf543ac157522522173620a01c2ce584b1c4925974738681e616728d` | Latest recorded same-day status: both lanes running, runtime SHA `6c4ecb1`, kill switches clear, broker OK, recovery disabled, telemetry failures `0`, market-data fetch failures `0`, mismatch count `0`. Exposure counts are historical packet facts only. | No live operation is authorized by this row; capture fresh status before operations. | `SESSION_HANDOFF.md` |
| lpfs-diagnostics-20260627 | 2026-06-27 | Diagnostics | dual/local | Partial; candle factors quarantined | reference | `reports/live_ops/lpfs_trade_diagnostics/20260627_121200` | manifest SHA-256 `d30a72bea2669ba87e547eacd2604b34c0aaa8772dbab03b7adf2d716a81bb13` | Closed-trade and non-candle lifecycle fields remain reference evidence, but RSI/MACD/EMA/volume/candle-derived fields were generated before the lane-authoritative candle-source guardrail and must not support strategy conclusions. | No live runner or strategy change. | `docs/reviews/2026-07-04-lpfs-candle-provenance-guardrail.md` |
| lpfs-candle-provenance-incident-20260704 | 2026-07-04 | Strategy research | dual/local | Warning; invalidated candle attribution | historical | `reports/live_ops/lpfs_trade_diagnostics/20260704_082040`; `reports/live_ops/lpfs_strategy_diagnostics_refresh/20260704_195931` | tracked review artifact | Records that local workstation MT5 candle roots were not lane-authoritative for FTMO/IC attribution. Candle-derived conclusions from those packets are quarantined until regenerated from validated lane-source candles; lifecycle/weekly broker facts remain separately classified by their own packets. | No VPS/MT5 access, no live operation, no journal rewrite, no broker mutation, no strategy change. | `docs/reviews/2026-07-04-lpfs-candle-provenance-guardrail.md` |
| lpfs-candidate-matrix-20260705 | 2026-07-05 | Strategy research | dual/local | Guarded research matrix | current | `reports/live_ops/lpfs_candidate_backtest_matrix/20260705_064500` | manifest SHA-256 `23c3d3da7afff6fab030816bcfc30645c0a900da443a8490d6a257ded53f4b6a` | Maintained-builder candidate matrix from safe July 4 diagnostics/factor packets. H8 risk/ATR `<0.5` remains the leading research candidate; broad structure/side filters are diagnostic only; incomplete candle/spread factor coverage is a data gap, not proposal evidence. | No live strategy, risk, sizing, SL/TP, config, recovery, VPS, broker, reconciliation, canary, or broker-send change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-skipped-opportunities-20260705 | 2026-07-05 | Strategy research | dual/local | Account-size diagnostic | current | `reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000` | manifest SHA-256 `ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f` | Maintained skipped-opportunity packet from safe July 4 filtered lifecycle copies. It found `4` IC `volume_below_min` broker-minimum skips and `0` FTMO broker-minimum skips in that evidence window. These are non-executed setup diagnostics, not closed trades. | No live strategy, risk, sizing, SL/TP, config, recovery, VPS, broker, reconciliation, canary, or broker-send change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-candidate-matrix-20260627 | 2026-06-27 | Strategy research | dual/local | Reference | reference | `reports/live_ops/lpfs_candidate_backtest_matrix/20260627_122800` | manifest SHA-256 `4e3191ef8075f7c2511d9ed419884fe1ea389b0696c50e119cf6315875621d60` | Candidate matrix for recent-window and long-history comparisons. | No live change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-divergence-20260627 | 2026-06-27 | Strategy research | dual/local | Reference | reference | `reports/live_ops/lpfs_live_backtest_divergence/20260627_124500` | manifest SHA-256 `e76af5226a87a5c885f81f049a80234a558101fffb171f665f1dcabd04b7e9b7` | Live-vs-backtest divergence attribution. | No live change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-h8-candidate-20260627 | 2026-06-27 | Strategy research | dual/local | Active candidate | current | `reports/live_ops/lpfs_h8_compressed_risk_candidate/20260627_125500` | manifest SHA-256 `894581b8eeff1da94869b999a3c153da53b077eb099b4c084aea653c899ba801` | Keeps H8 compressed risk as research-only candidate. | No live filter or risk change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-h8-interactions-20260627 | 2026-06-27 | Strategy research | dual/local | Reference | reference | `reports/live_ops/lpfs_h8_compressed_risk_interactions/20260627_130500` | manifest SHA-256 `1f66b98321f55ec5821bc39f08167c010475ba79570d7846529b16ad1193a89e` | Interaction isolation for H8 compressed risk and low-spread intersection. | No live change. | `docs/lpfs_strategy_iteration_context.md` |
| lpfs-research-closeout-20260627 | 2026-06-27 | Strategy research | dual/local | No live change | current | `reports/live_ops/lpfs_strategy_research_readiness/20260627_131500` | manifest SHA-256 `1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6` | Decision: reject H8 low-spread-only, keep H8 compressed risk as research candidate, require next eligible weekly criteria before escalation. | No live strategy, risk, sizing, SL/TP, spread, recovery, config, or broker-send change. | `docs/lpfs_strategy_iteration_context.md` |

## Deployment And Operations Packets

| id | date | domain | lane | status | current_label | path | hash_or_manifest | question_answered | non_actions | canonical_reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lpfs-ra002-ra003-20260615 | 2026-06-15 | Deployment | dual | Pass | current | `C:\Users\Cody\OneDrive\Desktop\TradeAutomation\reports\live_ops\lpfs_ra002_ra003_deploy_20260615_001507` | manual manifest SHA-256 `892523e60613e868ceba84d161aecf5ab8a02a2f22b8b701d9e7026f87b60a72`; final status SHA-256 `2e997f7e84c1691316ba1e46737ba68691b0a3bdd22c611988f4a687c4259aab` | Latest accepted operating boundary at runtime SHA `6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`; final proof showed both lanes running, kill switches clear, broker OK, recovery disabled, telemetry failures `0`, market-data failures `0`, mismatch `0`. | No reconciliation, canary, recovery enablement, manual broker mutation, config, strategy, risk, sizing, SL/TP, or broker-send change. | `SESSION_HANDOFF.md` |
| lpfs-frame-skip-20260612 | 2026-06-12 | Deployment | dual | Pass | historical | `C:\TradeAutomationEvidence\lpfs_market_data_frame_skip_deploy\20260612_133553` | manifest SHA-256 `21ea1596cf79476842f88d53aff88865dc01629d0e374cdbb86fd58161de6657`; final status SHA-256 `446698cc075c01b85782bc9710e05baf6d0b2ee35418eeda8f0116f70ec983cb` | Confirms transient market-data frame-skip behavior while broker/account/order/position failures remain fail-closed. | No reconciliation, canary, recovery, manual broker mutation, config, strategy/risk/sizing/SL/TP/broker-send change. | `docs/history/lpfs_operations.md` |
| lpfs-active-repair-ftmo-20260609 | 2026-06-09 | Deployment | FTMO | Pass | historical | `C:\TradeAutomationEvidence\lpfs_active_position_repair_deploy\20260609_232004\ftmo_v3` | manifest SHA-256 `a78a4eb4b0dc9aa9162cd737ecfc951ed03cd8cab7b8e0ac8af4d9e8171cf81d` | FTMO active-position state/broker repair pass at SHA `45efa748423f20881507cda9d4f81e4afe617bde`; mismatch `0`. | No recovery, reconciliation-only run, canary, broker mutation, config, journal migration, or strategy/risk/sizing/SL/TP/broker-send change. | `docs/history/lpfs_operations.md` |
| lpfs-active-repair-ic-20260609 | 2026-06-09 | Deployment | IC | Pass | historical | `C:\TradeAutomationEvidence\lpfs_active_position_repair_deploy\20260609_232004\ic_v3` | manifest SHA-256 `cd51fb720477de10cb6295f60198bab402717ea1b0253efda6eec94a2027729a` | IC active-position state/broker repair pass at SHA `45efa748423f20881507cda9d4f81e4afe617bde`; mismatch `0`. | No recovery, reconciliation-only run, canary, broker mutation, config, journal migration, or strategy/risk/sizing/SL/TP/broker-send change. | `docs/history/lpfs_operations.md` |
| lpfs-active-repair-final-20260609 | 2026-06-09 | Live status | dual | Pass | historical | `C:\CodexWorktrees\TradeAutomation-lpfs-c01-forward-fix\reports\live_ops\lpfs_dual_vps_status_20260609_234530.md` | final dual-status manifest SHA-256 `f7f4eed83c711b2c22e21c62bc5569c866c9f7963974e60b795c6d05309930e4`; root evidence manifest SHA-256 `1212407f35fa3d8d618ed8e7a71d1595618361b821afc5fcb76a9b61261ec2d0` | Final dual-lane active-position repair proof. | No live strategy/config/broker mutation. | `docs/history/lpfs_operations.md` |
| lpfs-telemetry-ftmo-20260607 | 2026-06-07 | Deployment | FTMO | Pass | historical | `C:\TradeAutomationEvidence\lpfs_phase1_telemetry\ftmo_task_repair_retry_20260607_201146` | manifest SHA-256 `4ec14b8ad6f4ab0bb3fbe22e86dd20140039c95c8e41ce0ae1f4977e8a1a9461` | Phase 1 telemetry separation deployed; lifecycle journals no longer receive new live `market_snapshot` rows. | No historical journal cleanup or strategy change. | `docs/history/lpfs_operations.md` |
| lpfs-telemetry-ic-20260607 | 2026-06-07 | Deployment | IC | Pass | historical | `C:\TradeAutomationEvidence\lpfs_phase1_telemetry\ic_deploy_20260607_202435` | manifest SHA-256 `7aba24f3227988473c9d6ab46a877e1c228e20faf29a5626cc11d664b900f23f` | Phase 1 telemetry separation deployed for IC. | No historical journal cleanup or strategy change. | `docs/history/lpfs_operations.md` |
| lpfs-c01-ftmo-retry-20260602 | 2026-06-02 | Deployment | FTMO | Superseded | superseded | `C:\TradeAutomationEvidence\lpfs_c01_deploy\20260602_160716\ftmo_stage1_retry` | manifest SHA-256 `f8155e042fb183070440f22516c05de8075203964217252edea19f05100e2341` | Historical FTMO contained retry; Stage 5 later superseded paused-state evidence. | No IC access at that checkpoint. | `docs/history/lpfs_operations.md` |
| lpfs-c01-ic-stage3-20260602 | 2026-06-02 | Deployment | IC | Superseded | superseded | `C:\TradeAutomationEvidence\lpfs_c01_deploy\20260602_152110\ic_stage3` | manifest SHA-256 `033a67a66a5064015d38c5c1a69d084d21cc4130e1539040a854421ab8fb81ed` | Historical IC contained Stage 3; Stage 5 later superseded paused-state evidence. | No FTMO access at that checkpoint. | `docs/history/lpfs_operations.md` |
| lpfs-weekly-incident-20260523 | 2026-05-23 | Reporting incident | dual | Historical warning | historical | `reports/live_ops/lpfs_dual_vps_status_20260523_140154.md` | status packet path recorded; see history doc for context | Unsafe production journal read was followed by stopped runners; both lanes were restarted and verified healthy. | Future reporting must use bounded/shared-read collection and fresh dual status after production-adjacent reads. | `docs/history/lpfs_operations.md` |

## Process Review Artifacts

| id | date | domain | lane | status | current_label | path | hash_or_manifest | question_answered | non_actions | canonical_reference |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| repo-hardening-20260704 | 2026-07-04 | Process | repo | Implemented | reference | `docs/reviews/2026-07-04-repo-structure-workflow-hardening.md` | tracked review artifact | Adds repo maintenance policy, decision log, process audit, and advisory size warnings. | No live behavior or generated artifact changes. | `docs/decision_log.md` |
| context-hardening-20260704 | 2026-07-04 | Process | repo | Role-reviewed | current | `docs/reviews/2026-07-04-context-architecture-hardening.md` | tracked review artifact | Documents team review, evidence-index schema, migration audit, and verification plan for first-read hardening. | No live behavior, runtime, journal, broker, config, report, or generated dashboard change. | `docs/decision_log.md` |
