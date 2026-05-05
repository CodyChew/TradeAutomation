# LPFS New MT5 Account Validation

This workflow validates a new MT5 account as a separate broker-data
environment before dry-run or live-send work. It is local-first and does not
touch the current VPS live runner.

Current naming convention: when a broker/account is identified, prefer a
stable slug such as `icmarkets_raw_spread` for ignored local configs and
journal/state files. Keep account numbers and credentials out of tracked docs.

Dashboard view:

```text
docs/account_validation.html
```

This generated page is the first visual summary for the current IC Markets Raw
Spread validation. It shows the account audit, V22 comparison, official
FTMO-vs-IC commission comparison, commission-adjusted V22 comparison, and the
V15 risk-bucket study on commission-adjusted R.

## Safety Boundary

- Log into the new account on the local PC MT5 terminal.
- Do not change the VPS MT5 login.
- Do not run local `LIVE_SEND`.
- Keep `LPFS_Live` on the VPS unchanged.
- Treat all outputs under `data/` and `reports/` as local, ignored artifacts.

## 1. Read-Only Account Audit

After logging into the new account locally, run:

```powershell
.\venv\Scripts\python scripts\audit_lpfs_new_mt5_account.py `
  --expected-login "NEW_ACCOUNT_LOGIN" `
  --expected-server "NEW_ACCOUNT_SERVER" `
  --select-symbols
```

The script writes a timestamped report under:

```text
reports/mt5_account_validation/lpfs_new_account/
```

It records non-secret account metadata, terminal metadata, symbol specs,
current tick snapshots, and H4/H8/H12/D1/W1 candle probes. It does not call
`order_check` or `order_send`.

## 2. Pull New Broker Dataset

If the audit confirms the account and symbol/timeframe coverage, pull a
separate dataset:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py `
  --config configs/datasets/lpfs_new_mt5_account_forex_10y.example.json `
  --output reports/mt5_account_validation/lpfs_new_account/dataset_pull.json
```

The dataset goes to:

```text
data/raw/lpfs_new_mt5_account/forex
```

## 3. Rerun Current LPFS Baseline

Run the current baseline on the new broker dataset:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v22_lp_fs_separation.py `
  --config configs/strategies/lp_force_strike_experiment_v22_new_mt5_account.example.json
```

This produces a separate report under:

```text
reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/
```

The baseline remains V13 mechanics + V15 risk buckets + V22 LP/FS separation.

## 4. Compare Against Current Baseline

Compare the new-account V22 run to the latest existing V22 baseline:

```powershell
.\venv\Scripts\python scripts\compare_lpfs_new_mt5_account_v22.py `
  --new-run-dir "reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/YYYYMMDD_HHMMSS"
```

Review:

- `comparison_summary.csv`
- `comparison_summary.json`
- `symbol_timeframe_delta.csv`

Large changes in trade count, PF, average R, total R, drawdown, or specific
symbol/timeframe contribution mean the broker feed is materially different and
needs review before dry-run.

Cost caveat: the current V22 baseline and the current IC Markets rerun both use
candle spread data with `round_turn_commission_points=0.0` and zero explicit
slippage. That makes the first comparison useful for broker-candle behavior,
but it is not a net profitability answer for a commissioned raw-spread account.
Use the commission-aware sensitivity pass before promoting a new account.

As of the latest dashboard-source check, official broker pages showed:

- FTMO Forex: `$2.50` per lot per side, `$5.00` round turn per lot.
- IC Markets Raw Spread MetaTrader: `$3.50` per lot per side, `$7.00` round
  turn per lot.

## 5. Commission And Risk-Bucket Study

Apply symbol-aware commission to the existing V22 trade rows:

```powershell
.\venv\Scripts\python scripts\run_lpfs_account_commission_sensitivity.py
```

The study writes ignored local artifacts under:

```text
reports/strategies/lp_force_strike_account_commission_sensitivity/
```

Current IC Markets Raw Spread result on the accepted V22 LP/FS-separated
variant:

- FTMO-backed baseline after `$5.00` round-turn commission: `1,141.8R`,
  `0.0965R` average trade, PF `1.216`, max drawdown `29.9R`.
- IC Markets Raw Spread after `$7.00` round-turn commission: `1,531.1R`,
  `0.1283R` average trade, PF `1.297`, max drawdown `24.1R`.
- IC remains stronger by `389.4R` even though its modeled commission burden is
  higher (`0.0402R` average per trade vs `0.0292R` on the FTMO baseline).

The same script reruns the V15 64-row H4/H8, H12/D1, and W1 bucket grid on the
commission-adjusted R stream. Current key rows:

- Adopted live row `0.20% / 0.30% / 0.75%`: IC `386.84%` total return,
  `7.23%` reserved DD, return/DD `53.53`; FTMO baseline `305.10%`,
  `11.23%` reserved DD, return/DD `27.18`.
- Growth alternative `0.25% / 0.30% / 0.60%`: IC `426.70%` total return,
  `9.55%` reserved DD; FTMO baseline `327.20%`, `10.82%` reserved DD.
- IC highest-return practical row: `0.25% / 0.30% / 0.75%`, `433.93%`
  return, `9.55%` reserved DD.

Interpretation: the IC account shows similar or stronger bucket behavior than
the current adopted live strategy after explicit commission. This is still
analysis only; it does not approve `LIVE_SEND`.

## 6. Dry-Run / Order-Check Only

Only after the backtest comparison is acceptable:

```powershell
Copy-Item config.lpfs_new_mt5_account.example.json config.lpfs_new_mt5_account.local.json
notepad config.lpfs_new_mt5_account.local.json
```

Set the expected login/server and keep:

```json
"live_send_enabled": false,
"execution_mode": "DRY_RUN"
```

Then run dry-run only:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_dry_run_executor.py `
  --config config.lpfs_new_mt5_account.local.json
```

This path calls `order_check` only and never sends orders.

For the current IC Markets Raw Spread validation, the ignored local config was
named:

```text
config.lpfs_icmarkets_raw_spread.local.json
```

Its journal/state paths use the same `lpfs_icmarkets_raw_spread` slug.
