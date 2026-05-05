# LPFS New MT5 Account Validation

This workflow validates a new MT5 account as a separate broker-data
environment before dry-run or live-send work. It is local-first and does not
touch the current VPS live runner.

Current naming convention: when a broker/account is identified, prefer a
stable slug such as `icmarkets_raw_spread` for ignored local configs and
journal/state files. Keep account numbers and credentials out of tracked docs.

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

## 5. Dry-Run / Order-Check Only

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
