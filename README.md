# bnc — Freqtrade Score4WindowStrategy

This repository contains a **Freqtrade** strategy only. It does not reimplement
exchange connectivity, backtesting, or order management.

## Strategy

- **Name:** `Score4WindowStrategy`
- **ID:** `SCORE_4WINDOW_V1`
- **Framework:** Freqtrade `IStrategy` INTERFACE_VERSION = 3
- **Source of truth for the bot engine:** https://github.com/freqtrade/freqtrade

Deterministic price-only scoring across four lookback windows (default 5 / 10 / 21 / 42).
Enter long when `total_score >= 2`. Shorts disabled. Exits via Freqtrade ROI/stoploss.

## Setup

```bash
pip install -r requirements.txt
# or: pip install -e /path/to/freqtrade
```

## Unit tests

```bash
pytest tests/test_score4window_strategy.py -q
```

## Backtest

Uses the official Freqtrade backtesting engine (config defaults to Gate.io for
environments where Binance is geo-restricted):

```bash
freqtrade download-data -c user_data/config.json --userdir user_data --timeframe 1d --days 200 -p BTC/USDT
freqtrade backtesting -c user_data/config.json --userdir user_data --strategy Score4WindowStrategy --timerange 20260301-20260901 -i 1d
```

## Baseline threshold study (no hyperopt)

Compare `entry_score_threshold` ∈ {1,2,3,4} on the same timerange without
permanently changing strategy defaults. Also reports trade outcomes by
`enter_tag` (`score_1`…`score_4`) from a threshold=1 run, plus a small liquid
USDT multi-pair sample (BTC/ETH/SOL/BNB/XRP).

```bash
# downloads data, runs threshold grid + multi-pair, writes reports/score4window_baseline_report.json
python scripts/run_score4window_baseline.py

# or reuse local OHLCV:
python scripts/run_score4window_baseline.py --skip-download
```

Multi-pair config: `user_data/config_baseline.json`  
Timerange: `20260301-20260901` · Timeframe: `1d`

This stage does **not** add Fibonacci, volatility, volume, VWAP, breakout, or news filters.
