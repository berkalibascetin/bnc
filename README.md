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

### Position sizing (built-in)

The strategy sizes each entry from score and volatility:

```text
size_pct = (total_score * risk_pct) / atr_pct
stake    = wallet * size_pct / 100
```

- `atr_pct` = ATR(14) / close * 100 (computed by the strategy)
- `risk_pct` default = **3**
- Cap: `max_position_pct` default = 25 (safety)

Example: score=2, risk=3, ATR%=4 → invest **1.5%** of wallet.

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

## Optional confirmation filters (OFF by default)

Filters are implemented in `Score4WindowStrategy` but **all default to OFF**,
so the live/default strategy remains the original 4-window score baseline.

Enable one filter at a time via `user_data/strategies/Score4WindowStrategy.json`
(or the evaluation script) for A/B tests:

- `enable_volume_filter`
- `enable_momentum_filter`
- `enable_breakout_filter`
- `enable_retest_filter`
- `enable_volatility_filter`
- `enable_fibonacci_filter`

### Filter evaluation

```bash
# uses Gate.io 1d data for BTC/ETH/SOL/BNB/XRP across 3 periods
python scripts/run_score4window_filter_eval.py
```

Report: `reports/score4window_filter_evaluation.json`

First-pass result: **no filter is recommended for production**. Volume/breakout
helped in 2024-09→2025-09 but failed in 2025-09→2026-09 (regime sensitivity /
overfit risk). Keep baseline score-only entry until a filter wins on all periods.

