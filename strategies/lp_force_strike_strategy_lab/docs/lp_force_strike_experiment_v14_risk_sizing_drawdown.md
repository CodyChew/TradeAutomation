# LP + Force Strike Experiment V14 Risk Sizing And Drawdown

## Purpose

V14 converts the current V13 `take_all` baseline from raw R results into
account-risk drawdowns. It is a drawdown and sizing study, not a prop-firm
pass/fail test.

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
  `../../configs/strategies/lp_force_strike_experiment_v14_risk_sizing_drawdown.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v14_risk_sizing_drawdown/20260429_235134`
- dashboard: `../../docs/v14.html`

## Risk Schedules Tested

Fixed risk:

- `0.10%` per trade;
- `0.25%` per trade;
- `0.50%` per trade.

Timeframe ladders:

- Conservative equal-LTF: H4 `0.10%`, H8 `0.10%`, H12 `0.20%`, D1 `0.30%`,
  W1 `0.40%`.
- Balanced equal-LTF: H4 `0.15%`, H8 `0.15%`, H12 `0.25%`, D1 `0.40%`,
  W1 `0.60%`.
- Tight H12-D1 basket: H4 `0.15%`, H8 `0.15%`, H12 `0.30%`, D1 `0.30%`,
  W1 `0.45%`.
- Quality-weighted diagnostic: H4 `0.10%`, H8 `0.15%`, H12 `0.25%`,
  D1 `0.40%`, W1 `0.60%`.
- High-timeframe tilt: H4 `0.05%`, H8 `0.05%`, H12 `0.20%`, D1 `0.50%`,
  W1 `0.75%`.

H4 and H8 are equal in the primary ladders because their win rate and PF are
close. The H8-upweighted row is a diagnostic only.

## Drawdown Views

- Realized drawdown: based on closed trade P/L by exit time.
- Risk-reserved drawdown: subtracts full open trade risk while trades are
  active. This is the more conservative live-account stress view because it
  makes overlapping exposure visible.

## Main Results

| Schedule | Total Return | Realized DD | Risk-Reserved DD | Worst Month | Max Reserved Open Risk |
|---|---:|---:|---:|---:|---:|
| Fixed 0.10% | 151.2% | 3.3% | 3.9% | -1.6% | 2.0% |
| Fixed 0.25% | 378.1% | 8.3% | 9.8% | -4.1% | 5.0% |
| Fixed 0.50% | 756.1% | 16.7% | 19.5% | -8.1% | 10.0% |
| Conservative equal-LTF | 240.3% | 4.8% | 6.7% | -2.7% | 4.2% |
| Balanced equal-LTF | 332.6% | 6.2% | 8.6% | -3.6% | 5.7% |
| Tight H12-D1 basket | 324.2% | 5.9% | 7.9% | -3.0% | 5.1% |
| Quality-weighted diagnostic | 303.7% | 6.1% | 8.5% | -3.8% | 5.6% |
| High-timeframe tilt | 250.1% | 8.0% | 10.5% | -4.3% | 5.6% |

## Recommended Read

Use the tight H12-D1 basket as the first practical risk schedule:

- it keeps H4 and H8 equal;
- it puts H12 and D1 in the same middle basket;
- it keeps W1 higher without stretching the risk range as much as Balanced;
- it improves risk-reserved DD from `8.6%` to `7.9%` versus Balanced;
- it lowers max reserved open risk from `5.7%` to `5.1%` versus Balanced;
- it gives up only about `8.4%` total return versus Balanced;
- it keeps risk-reserved max drawdown below fixed `0.25%`;
- it avoids the high stress profile of fixed `0.50%`.

Balanced equal-LTF remains the growth-tilted ladder. It has slightly higher
total return, but also higher risk-reserved DD and max open risk.

Fixed `0.25%` remains the closest simple alternative. It gives more total
return, but does not express the observed timeframe quality difference.

Fixed `0.50%` is useful as a stress diagnostic, not the first practical default.

## Risk Tolerance Calibration

For a more aggressive version, scale the recommended tight H12-D1 basket first:

```text
multiplier = target risk-reserved DD / 7.86
new timeframe risk = current timeframe risk * multiplier
```

This keeps the tested timeframe weighting intact. Increasing only H4/H8 is a
different hypothesis because those timeframes are more frequent and lower
quality than D1/W1, so it should be tested as a separate ladder before being
used.

Approximate scaled tight H12-D1 ladders:

| Target risk-reserved DD | H4 | H8 | H12 | D1 | W1 | Est. total return |
|---:|---:|---:|---:|---:|---:|---:|
| 6% | 0.11% | 0.11% | 0.23% | 0.23% | 0.34% | 247% |
| 8% | 0.15% | 0.15% | 0.31% | 0.31% | 0.46% | 330% |
| 10% | 0.19% | 0.19% | 0.38% | 0.38% | 0.57% | 412% |
| 12% | 0.23% | 0.23% | 0.46% | 0.46% | 0.69% | 495% |
| 15% | 0.29% | 0.29% | 0.57% | 0.57% | 0.86% | 618% |
| 20% | 0.38% | 0.38% | 0.76% | 0.76% | 1.14% | 825% |

## Next Step

Use V14 to choose account risk. The next research slice should test account
constraints such as daily loss, max loss, same-symbol stacking limits, and
execution caps without changing LP, Force Strike, entry, stop, target, or
pullback-wait behavior.
