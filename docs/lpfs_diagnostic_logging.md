# LPFS Diagnostic Logging

Last updated: 2026-05-23.

This note documents the logging-only diagnostic upgrade for LPFS. It is not a
strategy change: entries, exits, sizing, timeframe mix, spread gates, market
recovery rules, and MT5 order behavior are unchanged until a separate research
decision is approved and deployed.

## Coverage Audit

| Decision question | Current pre-upgrade coverage | Gap | Added diagnostic coverage |
| --- | --- | --- | --- |
| Is poor performance concentrated by symbol, timeframe, side, week, or exit result? | Already usable from closed trade summaries and weekly reports. | No setup-quality context for each closed trade. | Closed diagnostic rows now carry setup and execution context beside result fields. |
| Are live trades matching the 10-year backtest setup population? | Hard to join. Live `signal_key` had symbol/timeframe/side/signal time/candidate, but closed rows did not retain full setup metadata. | Missing LP/FS geometry, ATR/risk context, setup age, and canonical join fields at close. | Lifecycle rows carry versioned `diagnostics.setup`, `diagnostics.strategy`, and `diagnostics.backtest_join`. |
| Are spread, slippage, missed entries, recovery entries, or order timing explaining the gap? | Partially logged. Spread blocks and market recovery events existed, and order sent rows had placement lag. | Context was scattered and not consistently available on close rows. | Diagnostic payloads include market quote, spread gate, execution path, retcodes, lag, and recovery path fields. |
| Are H8 or other timeframe buckets materially outside backtest expectations? | Weekly report shows basic timeframe buckets. | No per-trade backtest comparison report with diagnostic columns. | `scripts/build_lpfs_trade_diagnostics.py` writes `closed_trade_diagnostics.csv` and `backtest_comparison.csv`. |
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
  result fields plus flattened diagnostic columns when present;
- `backtest_comparison.csv`: live-versus-backtest aggregates by lane,
  timeframe, symbol, side, symbol/timeframe, and timeframe/side;
- `summary.md`: short human-readable report summary.

Older journals remain valid input. Rows before this schema simply have blank or
missing diagnostic columns.

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
alone. Use the enriched rows to compare live trades against the 10-year
commission-adjusted backtest by symbol, timeframe, side, session/hour, weekday,
`risk_atr`, `bars_from_lp_break`, setup age, spread-risk bucket, execution
path, recovery path, hold time, and close reason.

A live heuristic change should be a separate proposal and deployment. Prefer
small reversible candidates, such as an H8 gate/reduction, spread/session
filter, setup-age or ATR/risk filter, entry-zone adjustment, or correlated
exposure limit, only if the enriched data and backtest splits support it.
