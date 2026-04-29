# V13 Relaxed Portfolio Rule Selection

## Purpose

V13 re-checks whether the V10/V12 `cap_4r` baseline is too conservative. It
keeps the signal and trade model fixed, then ranks portfolio rules by long-run
Total R after robustness checks instead of forcing the older 30R / 180D
guardrails as hard selectors.

## Fixed Strategy Model

- LP pivot strength: `3`.
- Timeframes: `H4`, `H8`, `H12`, `D1`, `W1`.
- Entry: 0.5 signal-candle pullback.
- Stop: full Force Strike structure.
- Target: single `1R`.
- Pullback wait: fixed 6 bars.
- Input: existing V9 trade log only; no signal rerun.

## Run

- Config:
  `configs/strategies/lp_force_strike_experiment_v13_relaxed_portfolio_selection.json`
- Input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- Report:
  `reports/strategies/lp_force_strike_experiment_v13_relaxed_portfolio_selection/20260429_172705`
- Dashboard:
  `docs/v13.html`

## Result

| Portfolio rule | Trades | Total R | PF | Max DD | Underwater | Negative years | Negative symbols |
|---|---:|---:|---:|---:|---:|---:|---:|
| take_all | 13,012 | 1,512.3R | 1.265 | 33.4R | 111D | 0 | 0 |
| one_symbol_no_cap | 11,519 | 1,267.1R | 1.248 | 33.7R | 172D | 0 | 0 |
| cap_16r | 11,519 | 1,267.1R | 1.248 | 33.7R | 172D | 0 | 0 |
| cap_8r | 11,467 | 1,266.4R | 1.250 | 33.7R | 170D | 0 | 0 |
| cap_12r | 11,518 | 1,266.1R | 1.248 | 33.7R | 172D | 0 | 0 |
| cap_10r | 11,509 | 1,263.2R | 1.248 | 33.7R | 172D | 0 | 0 |
| cap_6r | 11,226 | 1,235.6R | 1.249 | 32.6R | 125D | 0 | 0 |
| cap_4r | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | 0 | 0 |

## Decision

Use `take_all` as the current research baseline if account risk per trade is
kept small enough.

The reason is practical: `take_all` adds about `411R` over `cap_4r`, has shorter
underwater (`111D` vs `162D`), has no negative years, has no negative symbols,
and does not depend on one year or ticker. The max drawdown is higher
(`33.4R` vs `26.7R`), but at `0.25%` risk per trade that is about `8.3%` closed
trade drawdown versus about `6.7%` for `cap_4r`.

## Exposure Caveat

`take_all` is not free. It reached:

- max concurrent trades: `17`;
- max same-symbol stack: `4`;
- max same-time new trades: `12`;
- max open risk at `0.25%` per trade: about `4.25%`;
- max open risk at `0.50%` per trade: about `8.50%`.

Before live execution, the next research slice should model FTMO-style daily
loss, max loss, broker execution constraints, and same-symbol stacking behavior.

## Robustness Notes

For `take_all`:

- worst month: `2017-03`, about `-16.2R`;
- worst quarter: `2019Q1`, about `-10.2R`;
- longest underwater period: `2017-03-07` to `2017-06-26`, about `111D`;
- max drawdown trough: `2023-04-11`, about `33.4R`;
- weakest symbol: `GBPCAD`, still positive at about `11.2R`;
- best symbol: `EURAUD`, about `107.2R`;
- top symbol share: about `7.1%`;
- top three symbol share: about `19.4%`.

Current interpretation: the higher-return version does not show obvious
single-period or single-ticker dependency in the available 10-year dataset.

## Next Research

V14 should not change the LP or Force Strike logic. It should keep V13
`take_all` as the baseline and test whether that baseline survives realistic
account constraints:

- risk per trade examples: `0.10%`, `0.25%`, `0.50%`;
- max concurrent trade caps: uncapped, 8, 10, 12, 15;
- same-symbol stack caps: uncapped, 1, 2;
- FTMO-style daily loss and max loss breaches;
- worst day, worst week, worst month, top underwater periods;
- ticker, timeframe, and period concentration after constraints.

The decision should be whether `take_all` remains practical, or whether a
lighter execution cap preserves most return while reducing account-level risk.
