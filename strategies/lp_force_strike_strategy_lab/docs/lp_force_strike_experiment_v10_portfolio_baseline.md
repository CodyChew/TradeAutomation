# LP Force Strike Experiment V10 Portfolio Baseline

## Question

Does a practical portfolio exposure cap improve drawdown and underwater behavior
enough to replace taking every LP + Force Strike trade?

## Scope

- Config: `configs/strategies/lp_force_strike_experiment_v10_portfolio_baseline.json`
- Input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- Report:
  `reports/strategies/lp_force_strike_experiment_v10_portfolio_baseline/20260429_133443`
- Dashboard: `docs/v10.html`
- Pivots: LP3, LP4, LP5.
- Timeframes: all H4/H8/H12/D1/W1 trades from V9.

## Rules Tested

- `take_all`: accepts every trade for that LP pivot.
- `cap_4r`, `cap_6r`, `cap_8r`, `cap_10r`:
  - one open trade per symbol;
  - max open risk equals cap value;
  - risk is measured as 1R per accepted trade;
  - same-symbol same-time conflicts prefer higher timeframe first:
    W1 > D1 > H12 > H8 > H4.

## Guardrails

- Max closed-trade drawdown: 30R.
- Longest underwater period: 180 days.
- Ranking rule: only rows that pass both guardrails can be selected by total R.

## Result

| LP | Portfolio | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---|---:|---:|---:|---:|---:|---|
| 3 | take all | 13,012 | 1,512.3R | 1.265 | 33.4R | 111D | No |
| 3 | cap 4R | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | Yes |
| 3 | cap 6R | 11,226 | 1,235.6R | 1.249 | 32.6R | 125D | No |
| 4 | take all | 9,512 | 1,224.4R | 1.297 | 35.5R | 249D | No |
| 5 | take all | 7,519 | 1,004.8R | 1.310 | 31.7R | 254D | No |
| 5 | cap 4R | 6,431 | 888.4R | 1.322 | 24.0R | 229D | No |

Only LP3 cap 4R passed both guardrails.

## Read

Taking all trades produces the highest total R for LP3, but it breaches the
30R drawdown cap. LP3 cap 4R gives up about 411R of total return versus take-all
but brings max drawdown inside the guardrail while keeping underwater time under
180 days.

LP5 has the best trade quality from V9, but its portfolio curve stays
underwater too long in V10. Its capped versions improve drawdown, but not enough
to pass the 180D underwater rule.

## Current Conclusion

Use LP3 cap 4R as the current practical portfolio baseline. It is not the
highest-return raw curve, but it is the only tested V10 row that satisfies both
the drawdown and underwater constraints.

Next step: V11 should keep the LP3 cap 4R exposure rule and test whether all
timeframes should be traded, or whether a cleaner timeframe subset improves
return/DD and underwater behavior.
