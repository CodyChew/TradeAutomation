# TradeAutomation Project State

Last updated: 2026-05-04 local time after LPFS Amazon Lightsail VPS
production-task installation, go-live check, and Windows process-count
clarification.

## Purpose

This repository is a Python-first trading research workspace. TradingView is
used for visual inspection, while Python modules and MT5 broker data are the
source of truth for strategy research and future live execution work.

## Read This First In A New Codex Session

1. `SESSION_HANDOFF.md` for the latest operational snapshot.
2. `PROJECT_STATE.md` for the overall workspace state.
3. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for the current
   LP + Force Strike strategy research.
4. `docs/strategy.html` for the current V13 mechanics + V15 risk-bucket guide.
5. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before continuing execution work.
6. `docs/phase2_production_hardening.md` before operating watchdogs,
   kill-switch controls, heartbeat, status checks, or Task Scheduler setup.
7. `docs/lpfs_lightsail_vps_runbook.md` before moving LPFS to Amazon
   Lightsail.
8. `shared/market_data_lab/PROJECT_STATE.md` for dataset status.
9. `concepts/lp_levels_lab/PROJECT_STATE.md` and
   `concepts/force_strike_pattern_lab/PROJECT_STATE.md` only when changing
   concept behavior.

Useful dashboard entry point:

```text
docs/index.html
https://codychew.github.io/TradeAutomation/
```

## Current Structure

- `concepts/lp_levels_lab`: reusable LP levels concept.
- `concepts/force_strike_pattern_lab`: reusable raw Force Strike pattern
  concept.
- `shared/market_data_lab`: MT5 candle pulls, validation, Parquet storage, and
  dataset manifests.
- `shared/backtest_engine_lab`: strategy-neutral OHLC bracket-trade simulator.
- `strategies/lp_force_strike_strategy_lab`: active LP + Force Strike strategy
  research, MT5 execution contract, dry-run order-check adapter, and Telegram
  notification contract.
- `docs/`: static GitHub Pages dashboards.
- `data/` and `reports/`: generated local data/results, intentionally ignored by
  git.

Local side labs that are not part of this repo are preserved beside the repo in
`../TradingResearchLabs/`. The active repo root should stay focused on the
tracked TradeAutomation structure above plus ignored local artifacts such as
`data/`, `reports/`, `venv/`, and `venv.zip`.

## Current Dataset State

The FTMO FOREX major/cross dataset covers the 28 pairs built from AUD, CAD,
CHF, EUR, GBP, JPY, NZD, and USD.

Pulled locally:

- `M30`, `H4`, `D1`, `W1`: canonical 10-year dataset.
- `H8`: native MT5 add-on dataset.
- `H12`: native MT5 add-on dataset.

Dataset regression gate:

```powershell
.\venv\Scripts\python scripts\verify_dataset_fingerprint.py
```

Current result on 2026-04-29:

- `status=OK`
- `fingerprint_datasets=168`
- `aggregation_checks=140`

The gate compares the local Parquet files against
`configs/datasets/fingerprints/ftmo_forex_major_crosses_10y.json` and verifies
that settled `H4`, `H8`, `H12`, `D1`, and `W1` candles aggregate exactly from
`M30`. It skips the newest one day for aggregation checks because MT5 can have
small live-edge cache drift between native higher-timeframe candles and M30.

Core logic regression gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Current result on 2026-05-05:

- 333 unittest cases across the scoped core labs after corrected V19.
- `100.00%` line and branch coverage for the scoped core packages.
- Scope and edge-case rules documented in `docs/testing_strategy.md`.

Known data-quality interpretation:

- Current verdict is `OK_WITH_WARNINGS`, not failed.
- Known long-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- V1 through V6 strategy experiments excluded those four symbols for a clean
  conservative baseline.
- A 2026-04-29 ad hoc run tested those four symbols with the current V6 model.
  They loaded successfully and were not obvious performance outliers. Future
  experiments can use all 28 pairs, while keeping the gap caveat visible.
- Latest live-ended bars are incomplete and are dropped in backtests.

## Current LP Rules

LP levels are implemented in:

```text
concepts/lp_levels_lab/src/lp_levels_lab/levels.py
```

Current lookback mapping:

- `M30`: 5 days.
- `H4`: 30 days.
- `H8`: 60 days.
- `H12`: 180 days.
- `D1` / `2D`: 1 year.
- `W1`: 4 years.

TradingView visual indicator is kept aligned at:

```text
concepts/lp_levels_lab/tradingview/lp_levels.pine
```

## Current Strategy Model Under Test

The current live/research baseline is V13 mechanics with V15 risk buckets:

```text
LP3 take_all across H4/H8/H12/D1/W1
0.5 signal-candle pullback
full Force Strike structure stop
single 1R target
fixed 6-bar pullback wait
```

The strategy combines:

- active LP wick-break trap;
- raw Force Strike confirmation within the configured window;
- pullback entry into the signal candle zone;
- OHLC bracket simulation with candle spread and conservative same-bar
  stop-first handling.

Live broker testing currently scales the V15 risk ladder with
`live_send.risk_bucket_scale=0.05`, so H4/H8 are `0.01%`, H12/D1 are `0.015%`,
and W1 is `0.0375%`.

Latest research decisions:

- V16 bid/ask execution realism did not materially weaken V15. Keep current
  live FS structure stops unchanged; spread buffers remain follow-up research.
- V17 LP-FS proximity tightening did not beat current V15. Do not require the
  Force Strike structure to touch/cross the selected LP.

## Latest Timeframe Comparison

Latest completed comparison is V6:

```text
reports/strategies/lp_force_strike_experiment_v6_h12_bridge/20260428_191017
docs/v6.html
```

V6 results for `signal_zone_0p5_pullback__fs_structure__1r`:

| Timeframe | Trades | Avg R | PF | Win Rate |
|---|---:|---:|---:|---:|
| H4 | 5,642 | 0.084R | 1.185 | 56.9% |
| H8 | 2,674 | 0.099R | 1.221 | 56.7% |
| H12 | 1,844 | 0.157R | 1.375 | 59.2% |
| D1 | 855 | 0.208R | 1.527 | 61.2% |
| W1 | 170 | 0.252R | 1.678 | 62.9% |

Interpretation:

- H8 is only a modest improvement over H4.
- H12 is a meaningful bridge between H8 and D1.
- D1 and W1 remain the cleanest timeframes by quality.
- H12 should remain in the forward research set.

## Dashboard State

Static dashboards exist at:

- `docs/v1.html`: broad baseline.
- `docs/v2.html`: H4/D1/W1 midpoint focus.
- `docs/v3.html`: entry zones, ATR filters, partial exits.
- `docs/v4.html`: train/test stability filters.
- `docs/v5.html`: H8 bridge.
- `docs/v6.html`: H12 bridge.
- `docs/v7.html`: conservative 1R-cancel entry-wait test.
- `docs/v8.html`: entry-priority 1R-cancel entry-wait test.
- `docs/v9.html`: LP pivot strength sensitivity.
- `docs/v10.html`: portfolio exposure cap baseline.
- `docs/v11.html`: practical timeframe mix study.
- `docs/v12.html`: LP pivot finalization.
- `docs/v13.html`: relaxed portfolio rule selection.
- `docs/v14.html`: risk sizing and drawdown study.
- `docs/v15.html`: 3-bucket risk ladder sensitivity.
- `docs/v16.html`: bid/ask execution realism and spread-buffer research.
- `docs/v17.html`: LP-FS proximity tightening research.
- `docs/strategy.html`: current strategy guide for V13 mechanics + V15 risk
  buckets, including signal rules, backtest trade model, MT5-not-final status,
  edge cases, and deterministic inline SVG diagrams.
- `docs/live_ops.html`: live-run behavior, lifecycle scenarios, and operator
  commands.
- `docs/phase2_production_hardening.md`: implemented local
  production-hardening runbook for launcher, watchdog, kill switch, runtime
  folder, heartbeat, status command, Task Scheduler, and VPS readiness.
- `docs/lpfs_lightsail_vps_runbook.md`: Amazon Lightsail Windows VPS setup,
  security, sizing, Task Scheduler, and liaison packet.

The dashboard generator is:

```text
scripts/build_lp_force_strike_dashboard.py
```

Dashboard interpretation text is centralized in:

```text
configs/dashboards/lp_force_strike_pages.json
```

The home page generator is:

```text
scripts/build_lp_force_strike_index.py
```

The pages were made responsive and given explicit interpretation summaries on
2026-04-29. On 2026-04-30, V6-V15 gained a prominent `Decision Brief` block so
the important chat-style conclusions are visible before the metric tables. V14
also has `Risk Schedule Composition` and `Risk Tolerance Calibration` sections
so the recommended ladder and scaled risk options are easy to read. V15 adds
`Practical Return Leaderboard`, `Efficiency Leaderboard`, bucket-effect tables,
and W1-sliced grid heatmaps.

Future dashboard changes should update the metadata/generator first, then
regenerate the versioned pages. V14 is generated by:

```text
scripts/run_lp_force_strike_risk_sizing_experiment.py
```

V15 is generated by:

```text
scripts/run_lp_force_strike_bucket_sensitivity_experiment.py
```

The strategy-guide page is generated by:

```text
scripts/build_lp_force_strike_strategy_page.py
```

## Current Recommendation

The current research baseline after V13 is:

- LP pivot strength `3`.
- all `H4/H8/H12/D1/W1` timeframes.
- `take_all` portfolio handling: allow all trades, including same-symbol
  stacking.
- 0.5 signal-candle pullback, full Force Strike structure stop, single 1R
  target, and fixed 6-bar pullback wait.

V13 relaxed the older 30R max-drawdown / 180D underwater guardrails from hard
selection rules into context. Under that more trader-practical ranking,
`take_all` became the current research baseline:

| Portfolio | Trades | Total R | Max DD | Underwater | Negative years | Negative symbols |
|---|---:|---:|---:|---:|---:|---:|
| take_all | 13,012 | 1,512.3R | 33.4R | 111D | 0 | 0 |
| cap_4r | 10,037 | 1,100.9R | 26.7R | 162D | 0 | 0 |

Interpretation:

- `take_all` adds about `411R` over `cap_4r` and has shorter underwater.
- The higher drawdown is about `8.3%` at `0.25%` risk per trade, versus about
  `6.7%` for `cap_4r`.
- No negative years, no negative symbols, and no obvious year/ticker
  concentration skew were found in V13.
- The caveat is exposure: `take_all` reached 17 concurrent trades and max
  same-symbol stack of 4.

Next useful research:

- use V15's account-risk bucket schedule as the starting point for execution
  readiness;
- build the MT5 dry-run executor with broker `order_check`, audit journal, and
  Telegram events before any `order_send` path;
- run an execution-realism pass that compares the current OHLC baseline against
  bid/ask-aware entry, TP, and SL triggers, including short SLs that can be hit
  by Ask even when the Bid chart does not visibly touch the stop;
- test whether adding a small stop buffer beyond the Force Strike structure
  improves or hurts expectancy after accounting for larger risk distance,
  smaller position size, and changed TP distance;
- later test daily/max loss constraints, same-symbol stacking limits, and max
  concurrent trade limits against broker-realistic behavior.

Latest V14 risk-sizing read:

- V14 did not rerun MT5 data or signals. It used the V13 baseline trade rows.
- Tight H12-D1 basket is the practical starting schedule:
  H4 `0.15%`, H8 `0.15%`, H12 `0.30%`, D1 `0.30%`, W1 `0.45%`.
- Tight H12-D1 result: `+324.2%` total return, `5.9%` realized max DD,
  `7.9%` risk-reserved max DD, and `5.1%` max reserved open risk.
- Balanced equal-LTF remains the growth-tilted alternative:
  `+332.6%` total return, `6.2%` realized max DD, `8.6%`
  risk-reserved max DD, and `5.7%` max reserved open risk.
- Fixed `0.25%` is the closest simple alternative: `+378.1%` total return,
  `8.3%` realized max DD, and `9.8%` risk-reserved max DD.
- Fixed `0.50%` is a high-return/high-stress diagnostic, not the first
  practical default: `+756.1%` total return and `19.5%` risk-reserved max DD.
- For more or less aggressive sizing, scale the tight H12-D1 ladder first:
  `multiplier = target risk-reserved DD / 7.86`.
- Do not simply increase H4/H8 without testing. H4/H8 are more frequent and
  lower-quality than D1/W1, so increasing only lower timeframe risk is a new
  ladder hypothesis rather than a neutral sizing change.

V14 calibration examples:

| Target risk-reserved DD | H4 | H8 | H12 | D1 | W1 | Est. return |
|---:|---:|---:|---:|---:|---:|---:|
| 10% | 0.19% | 0.19% | 0.38% | 0.38% | 0.57% | 412% |
| 15% | 0.29% | 0.29% | 0.57% | 0.57% | 0.86% | 618% |
| 20% | 0.38% | 0.38% | 0.76% | 0.76% | 1.14% | 825% |

Latest V15 risk-bucket read:

- V15 did not rerun MT5 data or signals. It used the V13/V14 baseline trade
  rows.
- On 2026-05-01, the LPFS selector was patched to use the most extreme valid LP
  across the active trap window, then V9 was regenerated. Old/new V9
  `signals.csv` and `trades.csv` were byte-identical, so V10-V15 metrics stayed
  unchanged.
- V15 tested 64 ladders across three buckets: `H4/H8`, `H12/D1`, and `W1`.
- Practical filters were risk-reserved DD <= `10%`, max reserved open risk <=
  `6%`, and worst month >= `-5%`.
- Use the most-efficient practical row as the first account-constraint
  candidate: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- Most-efficient row result: `+383.2%` total return, `6.6%` realized max DD,
  `7.9%` risk-reserved max DD, `5.75%` max reserved open risk, and `-3.22%`
  worst month.
- Keep the highest-return practical row as the growth alternative: H4/H8
  `0.25%`, H12/D1 `0.30%`, W1 `0.60%`.
- Highest-return practical result: `+421.8%` total return, `8.2%` realized max
  DD, `9.7%` risk-reserved max DD, `5.95%` max reserved open risk, and
  `-4.05%` worst month.
- The V14 tight baseline was H4/H8 `0.15%`, H12/D1 `0.30%`, W1 `0.45%`, with
  `+324.2%` total return and `7.9%` risk-reserved max DD.
- Do not increase `H12/D1` above `0.30%` without a separate drawdown-tolerance
  decision. No `0.40%` or `0.50%` middle-bucket row passed the practical
  filters.

Do not replace the fixed 6-bar pullback wait with the V7/V8 1R-cancel wait
rule. V8, the fairer entry-priority version, was positive but weaker than the
full-28 fixed 6-bar baseline on every timeframe.

## Execution Readiness State

The repo now has both a dry-run adapter and a guarded live-send adapter.
The dry-run path remains broker-safe and never sends orders. The live-send path
can place real MT5 pending orders only when explicit local config flags and MT5
account checks pass:

- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/execution_contract.py`
  converts a tested `TradeSetup` into an MT5 pending-order intent or a precise
  rejection reason.
- `docs/mt5_execution_contract.md` documents the broker boundary.
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/notifications.py`
  defines notification events and a Telegram adapter.
- `docs/telegram_notifications.md` documents Telegram setup and safety rules.
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/dry_run_executor.py`
  adds the dry-run MT5 adapter around the execution and notification
  contracts. It pulls closed candles, normalizes broker time to UTC, logs live
  bid/ask/spread, writes JSONL audit/state files, and calls `order_check` only.
  The setup provider now builds the pending pullback order directly from the
  latest closed signal candle, instead of using the historical backtest builder
  that requires a later pullback-fill candle.
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
  adds the live-send path around the same setup provider and execution
  contract. It reconciles MT5 open orders, historical orders, positions, and
  deal history before scanning new signals, sends pending
  `BUY_LIMIT`/`SELL_LIMIT` orders only after all checks pass, rejects stale
  late-start setups whose entry already traded before placement, adopts exact
  matching broker orders/positions instead of re-sending duplicates, and writes
  atomically persisted restart-safe state for pending orders, active positions,
  sent notification keys, and last seen close deal.
- `scripts/run_lp_force_strike_live_executor.py` is the finite-cycle live-send
  runner and holds a single-runner lock beside the live state file. It now also
  supports `--runtime-root`, `--kill-switch-path`, and `--heartbeat-path` for
  Phase 2 production operation.
- `scripts/run_lpfs_live_forever.ps1`, `scripts/Set-LpfsKillSwitch.ps1`, and
  `scripts/Get-LpfsLiveStatus.ps1` provide the local/VPS watchdog, emergency
  stop file, timestamped logs, heartbeat, and pasteable status snapshot.
- `config.local.example.json` documents the ignored local config shape.
- `docs/dry_run_executor.md` documents setup, credentials, journal/state files,
  and the dry-run operating limits.

Execution contract facts:

- Current V15 efficient bucket risks are encoded: H4/H8 `0.20%`, H12/D1
  `0.30%`, W1 `0.75%`.
- Long setups become `BUY_LIMIT` intents only when entry is below current ask.
- Short setups become `SELL_LIMIT` intents only when entry is above current bid.
- Pending expiry follows the fixed 6-bar pullback wait:
  `fs_signal_time + timeframe_delta * 7`.
- Dry-run lot sizing uses equity, `trade_tick_value`, `trade_tick_size`, and
  volume step, rounded down.
- Live-send lot sizing uses `mt5.order_calc_profit` for broker/account-currency
  risk per lot, then floors volume to broker step and caps/rejects as needed.
- Required pre-send rejections include duplicate signal key, invalid geometry,
  non-tradeable symbol, spread cap, broker stop/freeze distance, missing risk
  bucket, invalid tick/volume metadata, max open risk, same-symbol stack, and
  concurrent trade limits.
- Equality at the max-open-risk boundary is allowed; exceeding it is rejected.

Telegram contract facts:

- Telegram is reporting only; it never decides whether to trade.
- Credentials must come from `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- The notifier defaults to dry-run behavior and uses injectable HTTP clients in
  tests.
- Event types include signal detected, setup rejected, order intent created,
  order-check passed/failed, order sent/adopted/rejected, pending
  expired/cancelled, position opened, SL/TP/manual close, runner
  started/stopped, executor error, and kill switch activated.

Dry-run adapter facts:

- Local config file `config.local.json` is intentionally ignored.
- Default MT5 mode attaches to an already-open terminal session, then verifies
  expected login/server before order checks.
- Explicit MT5 login/password/server mode remains available but is not the
  default.
- Environment fallback exists for `MT5_USE_EXISTING_TERMINAL_SESSION`,
  `MT5_EXPECTED_LOGIN`, `MT5_EXPECTED_SERVER`, `MT5_LOGIN`, `MT5_PASSWORD`,
  `MT5_SERVER`, `MT5_PATH`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`.
- The current FTMO-style terminal should use
  `dry_run.broker_timezone="Europe/Helsinki"` so broker EET/EEST timestamps
  normalize to canonical UTC.
- Local dry-run was moved from the EURUSD smoke-test scope to the full V15
  universe: 28 major/cross pairs x `H4/H8/H12/D1/W1` = 140 checks per cycle.
- On 2026-05-01 local time, one full-universe dry-run cycle with corrected
  broker timezone found four current order-check-passing intents:
  `AUDJPY D1 short`, `EURNZD H8 short`, `GBPJPY H12 short`, and
  `NZDCHF H4 long`.
- Local broker testing now uses `dry_run.risk_bucket_scale=0.1`, reducing the
  V15 risk ladder to H4/H8 `0.02%`, H12/D1 `0.03%`, and W1 `0.075%` while
  preserving the relative timeframe weighting.
- Real credentials, broker/account details, API keys, and live trading config
  must remain local-only and must not be logged.
- Telegram is optional and best-effort. Missing Telegram credentials disable
  Telegram without changing trade validity.
- The local journal keeps all dry-run and live lifecycle events. Telegram now
  sends compact trader-facing cards; raw retcodes, broker comments, exact
  floats, and diagnostics stay in JSONL.
- The runner script is
  `scripts/run_lp_force_strike_dry_run_executor.py --config config.local.json`.

Live-send adapter facts:

- Local config block: `live_send`.
- Required enablement:
  `execution_mode="LIVE_SEND"`, `live_send_enabled=true`, and
  `real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`.
- Current low-risk live-test defaults:
  `risk_bucket_scale=0.05`, `max_open_risk_pct=0.65`,
  `max_same_symbol_stack=4`, `max_concurrent_strategy_trades=17`.
- Scaled risk ladder: H4/H8 `0.01%`, H12/D1 `0.015%`, W1 `0.0375%`.
- Dynamic spread gate: spread must be <= 10% of the setup's entry-to-stop
  distance before `order_check` and again immediately before `order_send`.
- Single-runner protection: a lock file beside `lpfs_live_state.json` prevents
  two live runners from managing the same state concurrently.
- State persistence is atomic and broker-affecting state is saved immediately
  after safety mutations, including successful live send/adoption.
- Immediately before `order_send`, live-send checks for an exact matching
  broker pending order or already-open matching position and adopts it instead
  of sending a duplicate.
- Current spread-too-wide behavior is retryable for that exact signal key.
  Spread-only blocks send/log one WAITING event, do not mark the signal
  processed, and can place later if spread improves before entry touch or
  expiry. The one old NZDCHF spread skip was cleaned from local live state
  explicitly instead of keeping compatibility code.
- First Lightsail weekly-open observation: after market open, the runner
  correctly reconciled the two old broker-missing pending orders out of local
  state, then emitted multiple spread-too-wide WAITING cards and one
  entry-already-touched SKIPPED card. This is expected conservative live
  behavior around poor liquidity, but it can make forward execution differ from
  V15 if it persists during normal liquid hours.
- Next evidence task before any spread-rule change: build a live gate
  attribution report from `lpfs_live_journal.jsonl` showing detected setups,
  placed orders, spread waits, later placements after spread improved,
  entry-touch skips, expiries, symbols/timeframes affected, and whether blocks
  cluster around weekly open.
- V19 TP-near robustness has now been run as research-only evidence:
  `docs/v19.html` and
  `reports/strategies/lp_force_strike_experiment_v19_tp_near_robustness/20260504_194519`.
  It keeps the V15 LPFS baseline, uses the V16 no-buffer bid/ask control, and
  now uses hard reduced-TP semantics for close variants. Hard `close_pct_90`
  reached `1,594.0R`, only `+58.8R` versus `1,535.2R` control, and is not a
  live candidate. The strongest V19 live-design candidate is
  `lock_0p50r_pct_90`: `1,878.7R`, PF about `1.356`, `+343.5R` versus
  control, `390` saved-from-stop trades, `259` sacrificed full-TP trades, and
  `308` same-bar-conflict rows. No live behavior changed. The next TP-near step
  must be a separate live stop-protection design and VPS deployment plan.
- Once a pending order is placed, spread widening does not auto-cancel it and
  does not currently trigger a dedicated Telegram alert.
- Research gap: the historical baseline includes candle-spread cost drag, but
  exits are still triggered from OHLC reference highs/lows rather than full
  bid/ask paths. A short can be stopped live by Ask even if a Bid-only chart
  does not show the stop touched. Before changing live behavior, rerun V9/V15
  with bid/ask-aware trigger assumptions and compare a no-buffer baseline
  against small Force Strike structure stop buffers.
- Late-start missed-entry guard: if MT5 bars after the signal candle already
  touched the planned pullback entry before the live order could be placed, the
  setup is rejected instead of placing a stale pending order.
- Pending expiry is enforced by actual MT5 bar count: the live runner cancels
  after the configured 6 real bars from the signal candle. Friday bars after the
  signal count, weekend time does not, and Monday continues the remaining count.
- Every live pending order carries broker-side SL, TP, a conservative
  `ORDER_TIME_SPECIFIED` emergency backstop, magic number, and compact comment;
  the full signal key plus bar-count expiry metadata stay in local state.
- Pending-to-position reconciliation requires broker comment or historical
  order/deal linkage; same symbol/magic/volume alone is not enough.
- Telegram lifecycle alerts cover `ORDER PLACED`, `ORDER ADOPTED`, `ENTERED`,
  `TAKE PROFIT`, `STOP LOSS`, `TRADE CLOSED`, `WAITING`, `SKIPPED`,
  `REJECTED`, `CANCELLED`, `RUNNER STARTED`, and `RUNNER STOPPED`.
  Spread-only WAITING cards are retryable; fill, close, expiry, and
  cancellation cards reply to the original order/adoption card when Telegram
  returns a message ID.
- Manual or unknown close reasons are reported as `TRADE CLOSED` with MT5 PnL/R
  instead of being mislabeled as stop losses.
- Runner start/stop cards are process heartbeat alerts. They show cadence,
  requested/completed cycles, runtime, state-save status, and SGT start/stop
  time. They are also written to the live JSONL journal.
- Phase 2 process controls are implemented outside the trade engine:
  production runtime root defaults to `C:\TradeAutomationRuntime`, kill switch
  file defaults to `KILL_SWITCH` beside the live state, heartbeat defaults to
  `lpfs_live_heartbeat.json`, and watchdog logs go under
  `C:\TradeAutomationRuntime\data\live\logs`.
- The kill switch stops new live cycles before MT5 initialization, before each
  cycle, and during sleeps. It does not close open positions or delete broker
  pending orders by itself.
- Runtime-root migration is fail-closed by default: if the old configured live
  state exists and the new runtime-root state is missing, the runner exits until
  state is copied or `--allow-empty-runtime-state` is intentionally used after
  broker-state verification.
- Manual recent-trade summary:
  `scripts/summarize_lpfs_live_trades.py --config config.local.json --limit 5`
  with optional `--post-telegram`.
- Live Ops dashboard page: `docs/live_ops.html`.
- The runner script is
  `scripts/run_lp_force_strike_live_executor.py --config config.local.json`.

Last verified local live-send snapshot after the fresh 2026-05-01 test cycle:

This is a historical handoff snapshot. Before acting, verify MT5, ignored live
state, and the JSONL journal because broker state can change after this file is
written.

- Previous live journal/state were archived to:
  `data/live/lpfs_live_journal.jsonl.bak_20260501_034805` and
  `data/live/lpfs_live_state.json.bak_20260501_034805`.
- Last verified MT5 strategy pending orders:
  `EURNZD H8 SHORT SELL_LIMIT #257048012` and
  `GBPJPY H12 SHORT SELL_LIMIT #257048014`.
- Local active strategy positions at that time: none.
- Telegram sent compact cards for those two orders and for skipped
  `AUDJPY D1 SHORT` (entry already touched) and `NZDCHF H4 LONG` (spread too
  wide).
- Clearing live state intentionally re-arms processed signals and can place
  duplicate pending orders if the same latest-candle setups still pass.

Next execution phase:

1. Treat the current `config.local.json` path as real-account capable. The user
   confirmed the connected MT5 account is real.
2. Before any new run, inspect
   `data/live/lpfs_live_journal.jsonl`, `data/live/lpfs_live_state.json`, MT5
   pending orders/positions, and Telegram messages.
3. The live runner is a finite-cycle CLI. For a manual long run, use a very
   large cycle count and Ctrl+C to stop it; do not present this as guaranteed
   Windows service uptime.
4. Keep collecting low-risk forward evidence from MT5, Telegram, live state,
   and the JSONL journal before changing strategy rules or scaling risk.
5. Phase 2 local rehearsal passed on 2026-05-03 without changing strategy
   behavior. The Amazon Lightsail Windows VPS deployment then passed staged
   verification on 2026-05-04: repo at `C:\TradeAutomation`, runtime at
   `C:\TradeAutomationRuntime`, MT5 Python attach to the FTMO terminal works,
   copied state/journal match the two LPFS pending orders, direct one-cycle,
   watchdog one-cycle, Task Scheduler smoke, and Task Scheduler one-cycle tests
   passed, Telegram delivery works after the `certifi` HTTPS fix, and final
   at-logon task `LPFS_Live` is installed. The user then cleared the VPS kill
   switch and started `LPFS_Live`; status showed heartbeat `running`,
   `pending_orders=2`, `active_positions=0`, and `processes=2`.
   `processes=2` is expected on Windows when it is the venv launcher process
   plus its child Python interpreter for the same LPFS command. Confirm with
   `parent_pid`, `exe`, heartbeat freshness, and matching config/runtime root;
   do not treat that shape as a duplicate runner by itself.

## Force Strike Side-Lab Comparison Learnings

The old standalone repo at `../TradingResearchLabs/force_strike_lab/` was
reviewed on 2026-04-30. Its tests pass (`23` unittest cases), but rough branch
coverage from its own tests is about `43%`. It is useful as a research archive,
not as the execution base.

Useful old-lab ideas to mine later:

- TradingView visual-review workflow and client-facing signal labels.
- MT5 deal-history commission estimation.
- Standalone report/labeling pages for manual trade review.
- Historical D1 Force Strike-only findings as context.

Why the current `TradeAutomation` code remains the better base:

- Raw Force Strike is isolated in `concepts/force_strike_pattern_lab`.
- LP + Force Strike signal rules are isolated in the strategy lab.
- Trade simulation is shared and strategy-neutral.
- Risk, portfolio, execution contract, and notifications are separate modules.
- The strict core gate is `100.00%` line and branch coverage.

Do not merge the old `force_strike_lab` wholesale. If a useful idea is imported,
bring it across as a small, tested feature that fits the current module
boundaries.

## Git State Notes

Use git for exact commit truth:

```powershell
git status --short --branch
git log --oneline -12
```

At this handoff, all intended tracked changes should be committed and pushed to
`origin/main` before work is considered transferred. Ignored local files such as
`config.local.json`, `data/`, `reports/`, and `venv/` are intentionally not
part of the pushed handoff.

Local side labs formerly sitting untracked in this repo were moved to:

```text
../TradingResearchLabs/
```

That folder preserves `CryptoBot_test/`, `FOREX/`, `forex_experiment/`,
`mt5_strategy_lab/`, `xauusd_m1_research/`, and the standalone Git checkout
`force_strike_lab/`. Do not stage those projects into TradeAutomation unless
the user explicitly asks.

## Suggested Prompt For Next Session

```text
Continue from TradeAutomation/PROJECT_STATE.md. Focus on the LP + Force Strike
strategy lab. Read SESSION_HANDOFF.md first, then PROJECT_STATE.md,
strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md, docs/strategy.html,
docs/mt5_execution_contract.md, docs/telegram_notifications.md,
docs/dry_run_executor.md, and docs/phase2_production_hardening.md. The current
baseline is V13 `take_all` with LP3 across H4/H8/H12/D1/W1 and V15 efficient
risk buckets: H4/H8 0.20%, H12/D1 0.30%, W1 0.75%. V16 and V17 did not justify
changing live rules. Corrected V19 TP-near robustness marks
`lock_0p50r_pct_90` as a research-only live-design candidate, but no TP-near
live behavior has been implemented. A guarded live-send runner exists at
scripts/run_lp_force_strike_live_executor.py with risk_bucket_scale=0.05,
max_open_risk_pct=0.65, dynamic spread gating, restart-safe state, MT5
order/position/deal reconciliation, and compact Telegram lifecycle cards.
Connected MT5 is a real account; do not run live-send or clear state casually.
Local Phase 2 rehearsal has passed and Amazon Lightsail deployment is installed.
The VPS uses C:\TradeAutomation plus C:\TradeAutomationRuntime, MT5 Python attach
works against FTMO-Server, Telegram delivery works after the certifi HTTPS fix,
and scheduled task LPFS_Live is installed. The user has started the VPS runner;
`Get-LpfsLiveStatus.ps1` can show `processes=2` for one healthy logical runner
because Windows launches venv\Scripts\python.exe as a parent of the real child
Python interpreter. Verify parent_pid/exe/heartbeat/log freshness before
calling it duplicate. Do not change strategy behavior while doing the
operations move.
```
