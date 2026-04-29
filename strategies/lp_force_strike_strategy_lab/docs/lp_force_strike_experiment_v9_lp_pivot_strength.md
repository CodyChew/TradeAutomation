# LP Force Strike Experiment V9 LP Pivot Strength

## Question

Should the LP Levels concept keep pivot strength 3 as the default for this
strategy, or does a wider/narrower LP pivot produce better trade quality?

## Scope

- Config: `configs/strategies/lp_force_strike_experiment_v9_lp_pivot_strength.json`
- Report:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831`
- Dashboard: `docs/v9.html`
- Symbols: all 28 FX major/cross pairs.
- Timeframes: H4, H8, H12, D1, W1.
- LP pivot strengths tested: 2, 3, 4, 5.

## Constants

- H4 LP lookback: 30 days.
- H8 LP lookback: 60 days.
- H12 LP lookback: 180 days.
- D1 LP lookback: 365 days.
- W1 LP lookback: 1460 days.
- LP break-to-FS window: 6 bars, counting the LP break candle as bar 1.
- Entry: 0.5 signal-candle pullback.
- Stop: full Force Strike structure.
- Target: single 1R.
- Pullback wait: fixed 6 bars.
- Costs: candle spread from MT5 data.
- Latest incomplete bar: dropped before simulation.

## Overall Result

| LP Pivot | Trades | Win Rate | Avg R | PF | Total R |
|---:|---:|---:|---:|---:|---:|
| 2 | 18,898 | 57.7% | 0.110R | 1.248 | 2,072.0R |
| 3 | 13,012 | 58.0% | 0.116R | 1.265 | 1,512.3R |
| 4 | 9,512 | 58.5% | 0.129R | 1.297 | 1,224.4R |
| 5 | 7,519 | 58.8% | 0.134R | 1.310 | 1,004.8R |

## Read

LP pivot 5 has the best average R and profit factor, but has the fewest trades.
LP pivot 4 is the better balanced comparison point because it improves over
the current LP3 baseline while keeping more sample than LP5.

LP pivot 2 is the broadest signal source and gives the highest total R, but it
also has the weakest quality metrics. It should not become the quality default
without a portfolio-level test proving that the extra frequency is useful.

## Current Conclusion

Do not treat LP5 as the final execution default yet. Use LP5 as the
quality-focused follow-up and LP4 as the balanced follow-up. LP3 remains the
historical baseline, but V9 shows it is not the strongest quality setting for
the current trade model.
