# LP Force Strike Experiment V7/V8 Entry Wait

Date: 2026-04-29

## Question

Should the pullback-entry order stop using the fixed 6-bar wait and instead
remain active until either:

- the pullback entry is filled; or
- the would-be 1R target is reached first, meaning the setup is skipped?

The cancellation level is specifically 1R from the planned entry and full Force
Strike structure stop.

## Baseline

The comparison baseline is the full-28 equivalent of V6:

- V6 clean 24-pair run:
  `reports/strategies/lp_force_strike_experiment_v6_h12_bridge/20260428_191017`
- plus the four gap-symbol ad hoc run:
  `reports/strategies/lp_force_strike_gap_symbols_adhoc/20260429_061423`

This keeps the symbol universe consistent with V7/V8 while preserving the
original fixed 6-bar pullback wait.

## V7: Cancel-First Same-Bar Rule

- config:
  `configs/strategies/lp_force_strike_experiment_v7_entry_until_1r_cancel.json`
- report:
  `reports/strategies/lp_force_strike_experiment_v7_entry_until_1r_cancel/20260429_062506`
- dashboard: `docs/v7.html`
- entry wait: until entry or 1R cancel
- same candle touches entry and 1R: cancel first

## V8: Entry-First Same-Bar Rule

- config:
  `configs/strategies/lp_force_strike_experiment_v8_entry_until_1r_entry_priority.json`
- report:
  `reports/strategies/lp_force_strike_experiment_v8_entry_until_1r_entry_priority/20260429_063204`
- dashboard: `docs/v8.html`
- entry wait: until entry or 1R cancel
- same candle touches entry and 1R: entry first

## Result

| Run | Trades | Win Rate | Avg R | PF | Total R |
|---|---:|---:|---:|---:|---:|
| Full-28 fixed 6-bar baseline | 13,012 | 58.0% | 0.116R | 1.265 | 1,512.3R |
| V7 cancel-first | 4,885 | 35.7% | -0.321R | 0.519 | -1,568.7R |
| V8 entry-first | 9,627 | 55.3% | 0.062R | 1.133 | 598.3R |

By timeframe, V8 was weaker than the fixed 6-bar baseline on every tested
timeframe:

| Timeframe | Baseline PF | V8 PF | Baseline Avg R | V8 Avg R |
|---|---:|---:|---:|---:|
| H4 | 1.192 | 1.083 | 0.087R | 0.040R |
| H8 | 1.243 | 1.103 | 0.108R | 0.049R |
| H12 | 1.410 | 1.260 | 0.169R | 0.115R |
| D1 | 1.497 | 1.294 | 0.198R | 0.128R |
| W1 | 1.623 | 1.324 | 0.237R | 0.139R |

## Conclusion

Do not replace the fixed 6-bar pullback wait with the 1R-cancel wait rule.

The conservative cancel-first version is unusable. The entry-first version is
positive, but it reduces trade count, win rate, average R, profit factor, and
total R across every timeframe. The current fixed 6-bar baseline remains the
better rule.

The useful lesson is that a hard 1R cancellation removes too many trades that
still have positive expectancy. Future entry research should focus on smaller
timing filters, portfolio exposure controls, or timeframe-specific execution
rather than replacing the fixed 6-bar pullback window with this rule.
