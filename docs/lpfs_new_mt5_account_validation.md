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
commission-adjusted R stream. The current FTMO live reference remains
`0.20% / 0.30% / 0.75%`; the IC Markets Raw Spread analysis recommendation is
a separate growth-practical row, `0.25% / 0.30% / 0.75%`.

Current key rows:

- Adopted live row `0.20% / 0.30% / 0.75%`: IC `386.84%` total return,
  `7.23%` reserved DD, return/DD `53.53`; FTMO baseline `305.10%`,
  `11.23%` reserved DD, return/DD `27.18`.
- Growth alternative `0.25% / 0.30% / 0.60%`: IC `426.70%` total return,
  `9.55%` reserved DD; FTMO baseline `327.20%`, `10.82%` reserved DD.
- IC recommended growth-practical row: `0.25% / 0.30% / 0.75%`,
  `433.93%` return, `9.55%` reserved DD, `5.80%` max open risk, `-4.46%`
  worst month, and about `153` reserved underwater days.

Decision: if the IC account can accept more growth, prefer
`0.25% / 0.30% / 0.75%`. It gives more return than
`0.25% / 0.30% / 0.60%` with effectively the same reserved DD and worst month.
Do not promote the higher H12/D1 `0.40%` or `0.50%` rows without a separate
exposure decision because those rows breach the `6%` max-open-risk practical
cap.

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

The committed new-account example config now supports a per-timeframe
`risk_buckets_pct` override. For the IC Markets Raw Spread validation it is set
to the analysis recommendation:

```json
"risk_buckets_pct": {
  "H4": 0.25,
  "H8": 0.25,
  "H12": 0.30,
  "D1": 0.30,
  "W1": 0.75
}
```

`risk_bucket_scale` still multiplies this bucket shape. Use dry-run/order-check
to test the full IC bucket shape locally; keep `live_send.live_send_enabled`
false until a separate live-send plan is approved.

The per-trade max-risk cap is now config-specific. The default remains
`max_risk_pct_per_trade=0.75`; the ignored local IC dry-run config may raise it
to `1.5` when testing `risk_bucket_scale=2.0` so W1 signals are checked at the
intended `1.50%` target rather than rejected by the generic guardrail.

Latest local dry-run evidence after switching the ignored IC config to scale-2
IC bucket validation:

- `140` frames processed.
- Latest-bar setups detected: `AUDCHF H8`, `GBPCAD H12`, and `NZDCHF W1`.
- Effective targets were `H4/H8 0.50%`, `H12/D1 0.60%`, and `W1 1.50%`.
- The ignored IC config sets `dry_run.max_risk_pct_per_trade=1.5`, so the W1
  scale-2 signal is checked instead of blocked by the default `0.75` cap.
- All three created pending intents and passed MT5 `order_check`.
- Rounded actual risks were `AUDCHF H8 0.399898%` at `0.03` lots,
  `GBPCAD H12 0.591292%` at `0.04` lots, and `NZDCHF W1 1.354304%` at
  `0.05` lots.
- Live orders sent: `0`.

Local one-cycle live-send smoke evidence:

- Config used: ignored `config.lpfs_icmarkets_raw_spread.live_smoke.local.json`.
- Account verified before send: `ICMarketsSC-MT5-2`; account login remains in
  the ignored local config / active MT5 terminal, not committed docs.
- Existing IC strategy orders/positions before send: `0/0`.
- One-cycle smoke runner processed `140` frames.
- Sent one pending order: `AUDCHF H8` `BUY_LIMIT`, ticket `4419969921`,
  volume `0.03`, entry `0.56107`, stop `0.55951`, target `0.56264`.
- Two setups (`GBPCAD H12`, `NZDCHF W1`) were blocked by market recovery
  because current executable price was worse than the original entry.
- The user manually canceled ticket `4419969921`.
- Reconciliation confirmed broker state and local smoke state both returned to
  `0` pending orders and `0` positions.
- The VPS FTMO runner and VPS MT5 account were not changed.

For the current IC Markets Raw Spread validation, the ignored local config was
named:

```text
config.lpfs_icmarkets_raw_spread.local.json
```

Its journal/state paths use the same `lpfs_icmarkets_raw_spread` slug.
