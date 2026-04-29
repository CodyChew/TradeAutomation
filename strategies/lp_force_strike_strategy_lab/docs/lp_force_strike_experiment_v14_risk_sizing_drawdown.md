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
  `reports/strategies/lp_force_strike_experiment_v14_risk_sizing_drawdown/20260429_175908`
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
| Quality-weighted diagnostic | 303.7% | 6.1% | 8.5% | -3.8% | 5.6% |
| High-timeframe tilt | 250.1% | 8.0% | 10.5% | -4.3% | 5.6% |

## Recommended Read

Use the balanced equal-LTF ladder as the first practical risk schedule:

- it keeps H4 and H8 equal;
- it gives higher risk to cleaner H12, D1, and W1 trades;
- it keeps risk-reserved max drawdown below fixed `0.25%`;
- it avoids the high stress profile of fixed `0.50%`.

Fixed `0.25%` remains the closest simple alternative. It gives more total
return, but does not express the observed timeframe quality difference.

Fixed `0.50%` is useful as a stress diagnostic, not the first practical default.

## Next Step

Use V14 to choose account risk. The next research slice should test account
constraints such as daily loss, max loss, same-symbol stacking limits, and
execution caps without changing LP, Force Strike, entry, stop, target, or
pullback-wait behavior.
