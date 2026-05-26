# LPFS Diagnostic Logging

Last updated: 2026-05-26.

This note documents the logging-only diagnostic upgrade for LPFS. It is not a
strategy change: entries, exits, sizing, timeframe mix, spread gates, market
recovery rules, and MT5 order behavior are unchanged until a separate research
decision is approved and deployed.

For the current evidence-gated strategy-iteration handoff, read
`docs/lpfs_strategy_iteration_context.md` after this file.

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
High-volume `market_snapshot` rows are unchanged.

Sparse lifecycle rows can now include:

- top-level `diagnostic_schema_version` and `diagnostics` on direct audit rows
  such as `order_intent_created` and dry-run order checks;
- `notification_event.fields.diagnostic_schema_version` and
  `notification_event.fields.diagnostics` on notification lifecycle rows.

The diagnostic payload is versioned as `schema_version=1` and uses these groups:

- `setup`: setup id, symbol, timeframe, side, signal/entry indices, entry,
  stop, target, risk distance, LP/FS geometry, ATR, `risk_atr`, setup age, and
  model metadata;
- `strategy`: pivot strength, max bars from LP break, LP-before-FS setting,
  max entry wait bars, spread-risk limit, recovery mode, and risk/exposure
  limits;
- `market`: bid, ask, spread points, and quote time when available;
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

Build the additive local diagnostic report from safely collected local journal
copies:

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

Older journals remain valid input. Rows before this schema simply have blank or
missing diagnostic columns.

Offline indicator enrichment uses local candle roots only. The report defaults
to `data/raw/ftmo/forex` for FTMO and `data/raw/lpfs_new_mt5_account/forex` for
IC when those folders exist, and can be overridden with:

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl" `
  --candle-root "FTMO=data\raw\ftmo\forex" `
  --candle-root "IC=data\raw\lpfs_new_mt5_account\forex"
```

Derived fields are computed offline from copied journals, benchmark CSVs, and
local candle datasets. Do not add RSI, momentum, volume regime, or percentile
work to the live runner loop for strategy review.

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

`scripts/summarize_lpfs_live_gate_attribution.py` now defaults to
`--tail-lines 200000`, uses a shared-read stream for remote SSH journals, and
requires `--allow-full-scan` for an unbounded full remote scan.

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
