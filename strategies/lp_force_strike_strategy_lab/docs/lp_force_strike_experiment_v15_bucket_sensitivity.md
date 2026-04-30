# LP + Force Strike Experiment V15 Risk Bucket Sensitivity

## Purpose

V15 tests whether the V14 risk ladder should be changed after separating
account risk into three buckets:

- lower timeframe bucket: `H4/H8`;
- middle bucket: `H12/D1`;
- weekly bucket: `W1`.

No MT5 pull or signal rerun is needed. The run uses existing LP3 trade rows
from V9 and keeps all strategy mechanics unchanged:

- all `H4/H8/H12/D1/W1`;
- `take_all` portfolio handling;
- `0.5` signal-candle pullback;
- full Force Strike structure stop;
- single `1R` target;
- fixed 6-bar pullback wait.

## Run Details

- config:
  `../../configs/strategies/lp_force_strike_experiment_v15_bucket_sensitivity.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v15_bucket_sensitivity/20260430_125620`
- dashboard: `../../docs/v15.html`

## Grid Tested

V15 tested `64` ladders:

- `H4/H8`: `0.10%`, `0.15%`, `0.20%`, `0.25%`;
- `H12/D1`: `0.20%`, `0.30%`, `0.40%`, `0.50%`;
- `W1`: `0.30%`, `0.45%`, `0.60%`, `0.75%`.

Practical filter used in this run:

- risk-reserved max drawdown <= `10%`;
- max reserved open risk <= `6%`;
- worst month >= `-5%`.

These are research filters, not prop-firm pass/fail rules.

## Main Results

| Row | H4/H8 | H12/D1 | W1 | Total Return | Realized DD | Reserved DD | Max Open Risk | Worst Month |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V14 tight baseline | 0.15% | 0.30% | 0.45% | 324.2% | 5.9% | 7.9% | 5.1% | -3.03% |
| Most-efficient practical | 0.20% | 0.30% | 0.75% | 383.2% | 6.6% | 7.9% | 5.75% | -3.22% |
| Highest-return practical | 0.25% | 0.30% | 0.60% | 421.8% | 8.2% | 9.7% | 5.95% | -4.05% |
| Near-miss growth row | 0.25% | 0.30% | 0.75% | 428.6% | 8.1% | 9.6% | 6.10% | -4.05% |

The near-miss growth row fails only the configured `6%` max reserved open-risk
filter.

## Recommended Read

Use the most-efficient practical row as the first account-constraint candidate:

```text
H4/H8 0.20%, H12/D1 0.30%, W1 0.75%
```

This row keeps risk-reserved max drawdown essentially flat versus V14 while
lifting total return by about `59%`.

Keep the highest-return practical row as the growth alternative:

```text
H4/H8 0.25%, H12/D1 0.30%, W1 0.60%
```

It adds more return, but it uses almost all of the configured max open-risk
allowance and raises risk-reserved drawdown to about `9.7%`.

Do not increase `H12/D1` above `0.30%` without a separate drawdown-tolerance
decision. No `0.40%` or `0.50%` middle-bucket row passed the practical filters.

## Next Step

Run account-level constraints using the most-efficient practical row first and
the highest-return practical row as a growth contrast. The next test should
model daily loss, max loss, same-symbol stacking, and max concurrent trade
limits without changing LP, Force Strike, entry, stop, target, or pullback-wait
behavior.
