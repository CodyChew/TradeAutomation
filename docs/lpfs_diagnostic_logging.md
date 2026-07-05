# LPFS Diagnostic Logging

Last updated: 2026-06-01 during the C-01 timestamp repair.

This note documents the logging-only diagnostic upgrade for LPFS. It is not a
strategy change: entries, exits, sizing, timeframe mix, spread gates, market
recovery rules, and MT5 order behavior are unchanged until a separate research
decision is approved and deployed.

For the current evidence-gated strategy-iteration handoff, read
`docs/lpfs_strategy_iteration_context.md` after this file.

For production-derived conclusions, also read
`docs/lpfs_c01_live_safety_release.md`. Historical MT5-derived timestamps must
be normalized through the immutable C-01 tool before comparison. The
diagnostic builder deliberately retains flexible local `--journal` inputs, but
raw legacy production rows are not trustworthy strategy evidence until their
timestamp provenance is resolved. The normalizer classifies every historical
`*_utc` leaf, rebuilds embedded event signal keys with either `T` or
space-separated timestamps, and sets `safe_for_strategy_analysis=false` if any
timestamp path remains unresolved.

## Coverage Audit

| Decision question | Current pre-upgrade coverage | Gap | Added diagnostic coverage |
| --- | --- | --- | --- |
| Is poor performance concentrated by symbol, timeframe, side, week, or exit result? | Already usable from closed trade summaries and weekly reports. | No setup-quality context for each closed trade. | Closed diagnostic rows now carry setup and execution context beside result fields. |
| Are live trades matching the 10-year backtest setup population? | Hard to join. Live `signal_key` had symbol/timeframe/side/signal time/candidate, but closed rows did not retain full setup metadata. | Missing LP/FS geometry, ATR/risk context, setup age, and canonical join fields at close. | Lifecycle rows carry versioned `diagnostics.setup`, `diagnostics.strategy`, and `diagnostics.backtest_join`. |
| Are spread, slippage, missed entries, recovery entries, or order timing explaining the gap? | Partially logged. Spread blocks and market recovery events existed, and order sent rows had placement lag. | Context was scattered and not consistently available on close rows. | Diagnostic payloads include market quote, spread gate, execution path, retcodes, lag, and recovery path fields. |
| Are H8 or other timeframe buckets materially outside backtest expectations? | Weekly report shows basic timeframe buckets. | No per-trade backtest comparison report with diagnostic columns. | `scripts/build_lpfs_trade_diagnostics.py` writes closed-trade, backtest, comparison, confluence, and summary outputs. |
| Are outcomes worse because of setup quality, execution quality, or sample variance? | Not enough evidence from closed rows alone. | Missing per-trade setup geometry and execution path at the same row granularity as R/PnL. | New diagnostics make this analyzable after enough enriched closed trades accumulate. |

## Journal Schema

New logging is additive. Existing journal fields are not renamed or removed.
High-volume `market_snapshot` rows retain their existing cadence and now add
raw MT5 epoch, semantics, and provenance fields needed to audit C-01.

Sparse lifecycle rows can now include:

- top-level `diagnostic_schema_version` and `diagnostics` on direct audit rows
  such as `order_intent_created` and dry-run order checks;
- `notification_event.fields.diagnostic_schema_version` and
  `notification_event.fields.diagnostics` on notification lifecycle rows.

Broker-side partial closes are journaled as lifecycle evidence and are not
counted as closed trades. Final close rows aggregate all verified MT5 close
deals for the position, so summaries and diagnostic reports count the trade
once while preserving close deal tickets, closed volume, realized broker PnL,
and volume-weighted R.

The current diagnostic payload is versioned as `schema_version=2`. Older
`schema_version=1` rows remain readable. Schema v2 adds
`timestamp_semantics_version=mt5_epoch_utc_v2` plus raw MT5 epoch and
provenance fields where sparse broker lifecycle rows provide them. It uses
these groups:

- `setup`: setup id, symbol, timeframe, side, signal/entry indices, entry,
  stop, target, risk distance, LP/FS geometry, ATR, `risk_atr`, setup age, and
  model metadata;
- `strategy`: pivot strength, max bars from LP break, LP-before-FS setting,
  max entry wait bars, spread-risk limit, recovery mode, and risk/exposure
  limits;
- `market`: bid, ask, spread points, quote time, raw MT5 epoch values,
  timestamp semantics, and provenance when available;
- `spread_gate`: spread price, risk price, spread-risk fraction, limit, and
  pass/fail where available;
- `execution`: pending-limit versus market-recovery path, stage, broker risk
  per lot, order check/send retcodes/comments, signal-to-fill lag, and
  fill-to-close duration;
- `backtest_join`: symbol, timeframe, side, signal index, signal time,
  candidate id, setup id, signal key, and a stable trade key string.

Sensitive values remain excluded by the existing journal sanitization layer.
Do not add account logins, passwords, Telegram tokens, server names, or full
MT5 account dumps to diagnostics.

## Report Command

Build the additive local diagnostic report from operator-supplied local journal
evidence:

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl"
```

The output directory is:

```text
reports/live_ops/lpfs_trade_diagnostics/<timestamp>/
```

Files:

- `closed_trade_diagnostics.csv`: one row per closed live trade, with old
  result fields plus flattened diagnostic columns and offline-derived analysis
  fields when present;
- `backtest_diagnostics.csv`: one row per benchmark backtest trade, enriched
  with the same offline time/session/setup/candle buckets where candle data is
  available;
- `backtest_comparison.csv`: live-versus-backtest aggregates by lane,
  timeframe, symbol, side, symbol/timeframe, timeframe/side, session, weekday,
  setup buckets, execution buckets, and candle-derived regimes;
- `timeframe_confluence.csv`: FTMO/IC timeframe rows with live/backtest deltas,
  evidence thresholds, and the current research action;
- `summary.md`: short human-readable report summary.

## Factor Attribution Matrix

After a diagnostics packet exists, build the maintained offline factor matrix:

```powershell
.\venv\Scripts\python scripts\build_lpfs_factor_attribution.py `
  --diagnostics-dir reports\live_ops\lpfs_trade_diagnostics\<timestamp>
```

The output directory is:

```text
reports/live_ops/lpfs_factor_attribution/<timestamp>/
```

The builder is local/reporting-only. It validates the diagnostics packet
manifest before reading `closed_trade_diagnostics.csv` and
`backtest_diagnostics.csv`, then writes:

- `factor_attribution_matrix.csv`: lane-first rows by price-structure,
  momentum, volume, time/session, and core symbol/timeframe/side factors;
- `cross_lane_factor_confluence.csv`: FTMO/IC comparison for the same
  factor/value, preserving one-lane divergence separately from both-lane
  weakness;
- `summary.md`: concise research-only interpretation and caveats;
- `manifest.json`: input/output hashes, row counts, factor coverage, timestamp
  range, data-validity flags, and explicit non-actions.

Rows marked as research candidates are not live filters. They require the
strategy-change gate: FTMO/IC evidence where comparable, recent 3/6/12 month
support, long-history guardrails, sample-size and removal-breadth checks, and
explicit operator approval.

## Candidate Backtest Matrix

After factor attribution identifies a research candidate, build the maintained
candidate matrix from the same diagnostics packet:

```powershell
.\venv\Scripts\python scripts\build_lpfs_candidate_backtest_matrix.py `
  --diagnostics-dir reports\live_ops\lpfs_trade_diagnostics\<timestamp> `
  --factor-attribution-dir reports\live_ops\lpfs_factor_attribution\<timestamp> `
  --candidate-config configs\strategy_research\lpfs_candidate_matrix_current.json
```

The output directory is:

```text
reports/live_ops/lpfs_candidate_backtest_matrix/<timestamp>/
```

The builder is local/reporting-only. It validates source manifests and hashes
before reading `closed_trade_diagnostics.csv`, `backtest_diagnostics.csv`, and
the optional factor-attribution packet, then writes:

- `candidate_definitions.csv`: research-only candidate IDs, labels, filter
  expressions, factor families, candle-provenance requirements, and rationale;
- `candidate_filter_matrix.csv`: per candidate/window/lane baseline,
  candidate-subset, after-exclusion, removal share, delta R, and coverage
  status;
- `candidate_live_context.csv`: current safe live packet context by FTMO, IC,
  and combined;
- `candidate_guardrails.csv`: live confluence, sample status, factor coverage,
  removal breadth, and decision boundary;
- `candidate_overlap_matrix.csv`: overlap and confound checks across candidate
  pairs for live and backtest windows;
- `candidate_decision_summary.csv`: one row per candidate with the current
  decision and recommended next step;
- `summary.md` and `manifest.json`.

Incomplete factor coverage is a data gap, not a pass/fail backtest guardrail.
For example, candle-derived or spread-risk fields may be valid live diagnostics
while still lacking long-history backtest coverage. Such candidates must not be
promoted to `PROPOSAL_READY` until their factor coverage is sufficient or the
proposal explicitly excludes that factor family from its proof.

Candidate matrix rows remain research-only. They do not approve live filters,
risk haircuts, sizing changes, SL/TP changes, config changes, recovery changes,
VPS actions, or broker-send changes.

## Skipped Opportunity Diagnostics

Closed-trade diagnostics only analyze trades that actually reached a final
close row. Some valid LPFS signals can still be blocked before order placement
because the account/broker minimum volume is larger than the calculated risk
size. Build the skipped-opportunity report from safely collected local
lifecycle copies when IC/FTMO comparability or account-size effects matter:

```powershell
.\venv\Scripts\python scripts\build_lpfs_skipped_opportunity_diagnostics.py `
  --journal "FTMO=path\to\copied_ftmo_lifecycle.jsonl" `
  --journal "IC=path\to\copied_ic_lifecycle.jsonl"
```

The output directory is:

```text
reports/live_ops/lpfs_skipped_opportunity_diagnostics/<timestamp>/
```

The builder is local/reporting-only. It records input journal hashes and writes:

- `skipped_opportunity_events.csv`: one logical skipped opportunity per lane,
  signal key, and rejection reason;
- `volume_below_min_opportunities.csv`: the focused account-size subset, with
  raw/rounded/min volume, symbol, timeframe, side, signal key, risk/ATR,
  spread-risk context, and setup diagnostics where available;
- `skipped_opportunity_summary.csv`: reason and lane summaries with
  `closed_trade_count_impact=0`;
- `summary.md`, `manifest.json`, and `manifest.sha256.txt`.

This first report intentionally includes only `volume_below_min`. It excludes
retryable spread/session blocks, `order_check_failed`, `order_rejected`,
closed trades, partial closes, and final closes. Use
`scripts/summarize_lpfs_live_gate_attribution.py` for broader gate behavior.

Skipped opportunities are not closed trades, are not broker PnL, and are not
direct evidence that a live filter or sizing change should be deployed. They
answer a narrower question: whether account size or broker minimum volume is
causing forward-test evidence to differ between FTMO and IC.

Older journals remain valid input. Rows before this schema simply have blank or
missing diagnostic columns.

Diagnostics intentionally remain flexible offline tooling: `--journal` may
point to archived, historical, synthetic, or safely collected local copies and
does not require a collector manifest. For production evidence, prefer
snapshots produced by `scripts/collect_lpfs_live_journal_snapshots.py`. Never
pass an active VPS runtime journal path directly.

Offline indicator enrichment never uses local candle roots by default. A candle
root must be explicit and must include source provenance. For live FTMO/IC
strategy attribution, the provenance must be lane-authoritative, such as a
reviewed snapshot collected from that lane's VPS/broker-feed source. Local
workstation MT5 candles are not lane-authoritative for FTMO or IC.

Use the lane candle snapshot collector to produce ignored, manifest-backed
broker-feed roots before enabling candle-derived RSI/MACD/EMA/volume/structure
diagnostics for live lanes:

```powershell
.\venv\Scripts\python scripts\collect_lpfs_lane_candle_snapshots.py `
  --lane FTMO `
  --lane IC `
  --history-years 1
```

The collector is read-only with respect to LPFS live operations: it does not
change tasks, kill switches, configs, runtime state, journals, orders, or
positions. It also sets `allow_symbol_select=false` for the MT5 dataset pull,
so hidden symbols stop the packet as a data gap instead of mutating terminal
symbol visibility. Increase `--history-years` or use explicit
`--date-start-utc` / `--date-end-utc` only when the research question needs a
larger lane-feed window.

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl" `
  --candle-root "FTMO=path\to\ftmo_vps_broker_feed_candles" `
  --candle-source-provenance "FTMO=vps_lane_broker_feed" `
  --candle-root "IC=path\to\ic_vps_broker_feed_candles" `
  --candle-source-provenance "IC=vps_lane_broker_feed"
```

Derived fields are computed offline from copied journals, benchmark CSVs, and
explicit candle datasets. If provenance is `local_unverified`, the report
records the source but blocks candle enrichment from strategy-analysis fields.
Do not add RSI, momentum, volume regime, or percentile work to the live runner
loop for strategy review.

## Safe Collection Rules

Production journal/state reads are production-adjacent. Do not use unbounded
`Select-String`, `Get-Content -Raw`, or `[System.IO.File]::OpenText()` against
active runner files.

Approved readers must:

- open active files with `[System.IO.FileShare]::ReadWrite`;
- default to bounded/tail reads for remote files;
- require explicit full-scan intent for large historical reads;
- verify both live runners after any remote collection that touches active
  production files.

For routine compact summaries, use
`scripts/collect_lpfs_live_journal_snapshots.py`. It defaults to an exact
`64 MiB` source suffix, captures a fixed source byte range through a shared
read, excludes `market_snapshot` rows unless `--include-market-snapshots` is
explicitly requested, and publishes an ignored local snapshot plus manifest.
Use a larger `--max-source-bytes` only intentionally and `--allow-full-scan`
only with explicit approval. Capture a fresh dual-VPS status packet after
collection.

`scripts/summarize_lpfs_live_gate_attribution.py` defaults to
`--tail-lines 200000`, uses a shared-read stream for remote SSH journals, and
defaults to a `64 MiB` source suffix before applying the returned-row tail.
Use a larger `--max-source-bytes` only intentionally; unbounded scans require
explicit `--allow-full-scan`.

The weekly performance collector remains separate and unchanged. Its
calculations are not replaced by the compact-summary snapshot workflow.

## Iteration Gate

Do not change live strategy heuristics from the diagnostic logging upgrade
alone. Use the enriched rows to compare live trades against the recent 3, 6,
and 12 month benchmark windows first, with the full 10-year
commission-adjusted backtest as the robustness guardrail. Comparison dimensions
include symbol, timeframe, side, session/hour, weekday, `risk_atr`,
`bars_from_lp_break`, setup age, LP/FS geometry, spread-risk bucket, execution
path, recovery path, hold time, close reason, RSI/momentum regime,
ATR/volatility regime, candle body/range/wick context, and tick-volume regime
where available.

A live heuristic change should be a separate proposal and deployment. Prefer
small reversible candidates, and include both defensive and constructive
options:

- defensive: timeframe/session/spread filters, exposure reductions,
  setup-age/risk filters, or correlated exposure limits;
- constructive: entry timing, entry-zone adjustment, stop/risk-distance rules,
  target/partial/exit behavior, recovery behavior, or regime-aware management.

H8 is not a selected change candidate. Treat H8, W1, or any other timeframe as
a candidate only after enriched diagnostics show a persistent issue.

## Per-Timeframe Evidence Policy

Global LPFS defaults remain the baseline. Existing timeframe-specific risk
buckets remain allowed. New per-timeframe heuristic changes are allowed only
under evidence gating:

- FTMO and IC must show the same directional issue where comparable trades
  exist; one-lane weakness is first treated as broker/feed/execution divergence.
- Lower timeframes need more live trades before conclusions because they
  produce many more signals.
- Sparse timeframes can trigger research with fewer live trades, but need
  stronger recent-window and full-history backtest support before deployment.
- Broader independent tuning per timeframe is not the default because it raises
  overfitting and operational-complexity risk.

Use these live-sample thresholds as operating guidance, not automatic deploy
rules:

| Timeframe class | Investigate after | Research candidate after |
| --- | ---: | ---: |
| Higher frequency, such as H4 | 20 combined enriched closed trades | 40 combined enriched closed trades |
| Mid frequency, such as H8/H12/D1 | 10 combined enriched closed trades | 20 combined enriched closed trades |
| Sparse, such as W1 | 5 combined enriched closed trades | 10 combined enriched closed trades |

Two weak weeks can justify monitoring or investigation if both lanes show the
same issue. Three to four weak weeks can justify candidate research if the same
timeframe/setup/regime repeatedly underperforms. No live strategy change is
approved by the report alone; deployment still requires explicit approval,
recent-window improvement, FTMO/IC confluence, and no unacceptable degradation
in the full 10-year backtest.
