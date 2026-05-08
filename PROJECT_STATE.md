# TradeAutomation Project State

Last updated: 2026-05-09 after refreshing LPFS weekly performance status,
fast-forwarding both VPS checkouts to the latest docs/reporting commit, and
verifying both live runners remained operational.

## Purpose

This repository is a Python-first trading research workspace. TradingView is
used for visual inspection, while Python modules and MT5 broker data are the
source of truth for strategy research and live execution work.

## Read This First In A New Codex Session

1. `SESSION_HANDOFF.md` for the latest operational snapshot.
2. `strategies/lp_force_strike_strategy_lab/START_HERE.md` for the LPFS
   first-read path, environment boundaries, and resume prompts.
3. `PROJECT_STATE.md` for the overall workspace state.
4. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for the current
   LP + Force Strike strategy research.
5. `docs/strategy.html` for the current V13 mechanics + V15 risk-bucket guide.
6. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before continuing execution work.
7. `docs/phase2_production_hardening.md` before operating watchdogs,
   kill-switch controls, heartbeat, status checks, or Task Scheduler setup.
8. `docs/lpfs_lightsail_vps_runbook.md` before VPS remote access,
   deployment, or maintenance.
9. `docs/lpfs_icmarkets_vps_runbook.md` before IC VPS maintenance.
10. `docs/lpfs_new_mt5_account_validation.md` before validating another MT5
   account or broker feed.
11. `docs/ea_migration.html` and `mql5/lpfs_ea/README.md` before continuing
   native MQL5 EA or Strategy Tester work.
12. `docs/live_weekly_performance.html` for the latest FTMO/IC live weekly
   performance checkpoint.
13. `shared/market_data_lab/PROJECT_STATE.md` for dataset status.
14. `concepts/lp_levels_lab/PROJECT_STATE.md` and
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
- `mql5/lpfs_ea`: isolated native MQL5 EA migration workspace. It is
  Strategy Tester-only in v1 and must not be treated as production live
  execution. Compile and tester load/config smoke passed; full-result smoke is
  pending until the EA gets single-chart smoke mode and new-bar gating.
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

## Current Secondary MT5 Account Validation

On 2026-05-05, a local-only IC Markets Raw Spread account validation was run
from the local PC MT5 terminal. The VPS live account was not changed.

Local ignored artifacts:

- account audit:
  `reports/mt5_account_validation/lpfs_new_account/20260505_155656`
- broker dataset:
  `data/raw/lpfs_new_mt5_account/forex`
- V22 run:
  `reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/20260505_160405`
- comparison:
  `reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/20260505_160405/comparison_to_current_v22`
- dry-run config:
  `config.lpfs_icmarkets_raw_spread.local.json`
- dry-run journal/state:
  `data/live/lpfs_icmarkets_raw_spread_dry_run_journal.jsonl`
  and `data/live/lpfs_icmarkets_raw_spread_dry_run_state.json`

Read-only audit result:

- server: `ICMarketsSC-MT5-2`
- currency: `USD`
- symbols available/visible: `28/28`
- timeframe probes: `140/140 OK`
- volume min/step: `0.01/0.01` for all audited FX symbols
- stop/freeze levels: `0/0` for all audited FX symbols

Data pull result:

- datasets pulled: `140`
- failures: `0`
- coverage starts around `2016-05-09` for H4/H8/H12/D1 and `2016-05-08`
  for W1.

V22 separated comparison against the current FTMO-backed baseline:

- trades: `11,937` vs `11,834`
- win rate: `59.09%` vs `58.37%`
- total R: `2,010.6R` vs `1,487.5R`
- average R: `0.1684R` vs `0.1257R`
- profit factor: `1.406` vs `1.289`
- max drawdown: `18.0R` vs `26.0R`

Current local IC validation status:

- scale-2 dry-run frames processed: `140`
- current fresh setups: `AUDCHF H8`, `GBPCAD H12`, `NZDCHF W1`
- broker `order_check` calls: `3`, all passed
- one-cycle live-send smoke test sent one `AUDCHF H8` `BUY_LIMIT`, ticket
  `4419969921`
- the user manually canceled ticket `4419969921`
- MT5 and local smoke state reconciled to `0` pending orders and `0` positions
- VPS FTMO live runner and VPS MT5 login were not changed

Dedicated IC VPS production status:

- SSH alias: `lpfs-ic-vps`.
- Host: `EC2AMAZ-DT73P0T`, Tailscale IP `100.98.12.113`.
- Repo: `C:\TradeAutomation`.
- Runtime: `C:\TradeAutomationRuntimeIC`.
- Task: `LPFS_IC_Live`.
- Startup alert task: `LPFS_IC_Startup_Alert`.
- Config: ignored `config.lpfs_icmarkets_raw_spread.local.json`.
- Broker: `ICMarketsSC-MT5-2`, company `Raw Trading Ltd`, currency `USD`.
- Risk: IC growth-practical buckets `0.25% / 0.30% / 0.75%` with
  `risk_bucket_scale=2.0`; effective targets are H4/H8 `0.50%`, H12/D1
  `0.60%`, W1 `1.50%`.
- Identity: magic `231500`, broker comment prefix `LPFSIC`, separate Telegram
  channel.
- First IC VPS live-send smoke completed with `1` tracked pending order and
  `0` active positions before continuous task startup.
- `LPFS_IC_Live` is installed/running. Use
  `scripts/Get-LpfsDualVpsStatus.ps1` from the local repo to capture both FTMO
  and IC status packets into ignored `reports/live_ops/` files.
- FTMO has matching startup alert task `LPFS_FTMO_Startup_Alert`. Startup alert
  tasks send `VPS STARTED` Telegram cards and journal `vps_startup_alert` after
  Windows boot; they do not import MT5 or touch live trading state.
- Live gate-attribution script:
  `scripts/summarize_lpfs_live_gate_attribution.py`. It reads local journals or
  streams FTMO/IC journals over SSH, omits high-volume `market_snapshot` rows by
  default, and writes ignored Markdown under `reports/live_ops/`.
- Latest read-only dual VPS status at 2026-05-06 21:16 SGT: FTMO task and IC
  task both running with fresh heartbeat, kill switches clear, clean
  `main...origin/main`, and latest cycles at `140` frames with `orders_sent=0`,
  `setups_blocked=0`, `setups_rejected=0`.
- Latest generated attribution artifact:
  `reports/live_ops/lpfs_gate_attribution_20260506_2138.md` (ignored). It
  covered FTMO from `2026-05-05T08:42:28Z` to `2026-05-06T13:25:56Z` and IC from
  `2026-05-05T19:49:36Z` to `2026-05-06T13:38:19Z`. FTMO had `18` unique
  decision signals, `10` placements, `0` spread waits, `1` market-recovery price
  wait, and `5` expiries. IC had `7` unique decision signals, `4` placements,
  `0` spread waits, `3` market-recovery price waits, and `1` entry-touch/path
  skip. Both had `0` retryable waits inside the 12-hour weekly-open window.

2026-05-08 rollover/spread-wait QA note:

- IC `AUDNZD H4` and `AUDNZD H8` stopped out around `05:02 SGT` while FTMO kept
  the comparable positions open. The IC journal showed a rollover spread spike
  near the close (`bid=1.21071`, `ask=1.21456`, `385` points). This is currently
  treated as broker quote/spread/feed divergence during daily rollover, not as a
  strategy or executor bug.
- The 10-year commission-adjusted V22 separated trade audit showed
  rollover-containing intraday exit bars remained net positive after both stops
  and targets: IC `2,461` exits for `+364.3R`; FTMO `2,487` exits for `+308.8R`.
  Candle-level testing includes spread through bid/ask simulation, but may miss
  tick-only rollover spikes that are not preserved in OHLC/spread bars.
- The one-hour placement lag later that morning was retryable
  `spread_too_wide` WAITING behavior through the 05:00-06:00 SGT rollover
  window. Both VPS lanes were running, and delayed CAD-cross orders placed after
  spread normalized near 06:00 SGT.
- Current decision: no code or ops patch. Keep monitoring through
  `scripts/Get-LpfsDualVpsStatus.ps1`,
  `scripts/summarize_lpfs_live_gate_attribution.py`, MT5 history, and journal
  rows. Build a dedicated rollover report only if this pattern repeats or
  materially harms PnL.

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

Fresh FTMO challenge sizing is now tracked separately from live validation.
Latest research run:
`reports/strategies/lpfs_ftmo_challenge_frontier/20260508_112959`, surfaced at
`docs/ftmo_challenge_profiles.html`.

- Fresh 100k FTMO Challenge profile: H4/H8 `0.20%`, H12/D1 `0.20%`, W1
  `0.65%`; `248.70%` 10-year return, `9.46%` risk-reserved DD, `4.45%`
  estimated max daily-loss stress, and `4.45%` max open risk.
- Aggressive/funded profile: H4/H8 `0.20%`, H12/D1 `0.25%`, W1 `0.55%`;
  `270.12%` 10-year return, `9.14%` risk-reserved DD, `4.95%` estimated max
  daily-loss stress, and `4.95%` max open risk. This is close to FTMO's `5%`
  daily-loss boundary.
- This was research-only. No live config, VPS runtime state, journal, MT5
  order, or scheduled task changed.

Latest research decisions:

- V16 bid/ask execution realism did not materially weaken V15. Keep current
  live FS structure stops unchanged; spread buffers remain follow-up research.
- V17 LP-FS proximity tightening did not beat current V15. Do not require the
  Force Strike structure to touch/cross the selected LP.
- V19 hard reduced-TP testing rejected a simple `0.9R` take profit as too weak,
  but found `lock_0p50r_pct_90` promising under higher-timeframe bid/ask
  simulation.
- V20 lower-timeframe replay brackets the live 30-second timing question. When
  stop protection can only activate on a later M30 candle, variants were flat
  to negative versus M30 control. Under an optimistic same-M30 activation
  assumption, the idea improves but is only an upper bound. Keep live TP/SL
  behavior unchanged until finer data or forward evidence confirms the live
  timing.

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
- `docs/v18.html`: TP-near exit research.
- `docs/v19.html`: hard reduced-TP and TP-near robustness research.
- `docs/v20.html`: M30 replay protection-realism research.
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
- Broker `Market closed` placement blocks are also retryable. If MT5 returns
  retcode `10018` or a `Market closed` comment during pending-order or
  market-recovery `order_check`/`order_send`, the runner sends/logs WAITING,
  removes the processed signal key, and retries while the setup remains valid.
  True broker rejections and manual deletion of already placed orders remain
  final unless deliberately re-armed.
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
- V20 protection-realism has now been run as research-only evidence:
  `docs/v20.html` and
  `reports/strategies/lp_force_strike_experiment_v20_protection_realism/20260505_043723`.
  It keeps the V15 signal baseline but replays entries/exits/protection on M30
  bid/ask candles. It explicitly brackets live timing: default stress variants
  only lock the stop on a later M30 candle, while
  `lock_0p50r_pct_90_m30_same_assumed` is an optimistic upper bound for the
  30-second live loop. M30 replay control produced `12,022` trades, `336.9R`,
  PF about `1.058`. Same-M30 assumed produced `512.9R`, `+176.0R` versus
  control, but that relies on unknown intra-M30 ordering and is not direct live
  evidence. The practical later-M30 variants were flat to negative:
  `lock_0p50r_pct_90_m30_next` was `-53.0R` and
  `lock_0p50r_pct_90_m30_delay1` was `-5.5R` versus control. No live behavior
  changed. Current TP-near conclusion: live behavior should remain unchanged;
  the next valid evidence step is M1/tick replay or forward live attribution,
  not immediate implementation.
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
  Spread-only, market-recovery price/spread, AutoTrading-disabled, and broker
  market-closed WAITING cards are retryable; fill, close, expiry, and
  cancellation cards reply to the original order/adoption card when Telegram
  returns a message ID.
- Manual or unknown close reasons are reported as `TRADE CLOSED` with MT5 PnL/R
  instead of being mislabeled as stop losses.
- Runner start/stop cards are process heartbeat alerts. They show the
  sleep-after-cycle setting, requested/completed cycles, runtime, state-save
  status, and SGT start/stop time. The `30s` setting is a sleep after a
  completed scan, not a fixed wall-clock launch interval. They are also written
  to the live JSONL journal.
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
- Manual performance summary:
  `scripts/summarize_lpfs_live_trades.py --config config.local.json --days 7`
  or `--weeks 4` with optional `--post-telegram`; on the VPS add
  `--runtime-root C:\TradeAutomationRuntime`. It is metric-only by default and
  lists exact trades only with `--include-trades`.
- Routine Telegram summaries should omit `--include-trades`. Latest compact
  weekly posts on 2026-05-06: FTMO reported `16` closed trades, `43.8%` win
  rate, net PnL `-37.85`, total `-1.88R`; IC raw-spread reported no closed
  trades in its live journal.
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

For the native EA migration task:

```text
Continue the LPFS native MQL5 EA migration from TradeAutomation. Read
SESSION_HANDOFF.md, strategies/lp_force_strike_strategy_lab/START_HERE.md,
docs/ea_migration.html, and mql5/lpfs_ea/README.md first. Current checkpoint:
MetaEditor compile passed with 0 errors/0 warnings, MT5 Strategy Tester
load/config smoke passed, and the first EURUSD H4 tester run was intentionally
stopped because the scaffold scans the full 28-symbol x 5-timeframe basket on
every tick. Next task: add InpSmokeTestSingleChartOnly=true by default for v1
tester smoke, scan only _Symbol/_Period when enabled, add new-bar gating, then
compile and rerun a short EURUSD H4 Strategy Tester smoke. Do not touch VPS
runtime, live configs, live journals, scheduled tasks, or broker orders.
```

For LPFS live operations:

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
