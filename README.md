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
