# Shared Labs

Shared labs hold strategy-neutral infrastructure used across concepts and
strategy research.

## Current Labs

- `market_data_lab`: canonical MT5 candle schema, validation, Parquet storage,
  manifests, pull helpers, and reusable symbol universes.

## Rule

Concepts and strategies should consume shared data contracts instead of
inventing their own candle schemas. Strategy-specific assumptions belong inside
strategy labs, not in shared data code.
