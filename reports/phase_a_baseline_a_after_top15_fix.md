# Phase A — Baseline A after historical Top-15 fix

- Timerange requested: `20240101-20260901` (local data ~2024-07-05 → clipped end)
- Effective backtest window (from freqtrade): **2024-08-16 → 2026-09-01**
- Strategy: `Score4WindowStrategy` (baseline A; no FreqAI)
- Elapsed: 338.2s
- Historical Top-15 precompute used candle-causal `score_universe(as_of=T)`

## Metrics
| Metric | Value |
|--------|-------|
| trades | 2426 |
| win_rate | 0.5259686727122836 |
| profit_pct | 0.26674261335 |
| total_profit (USDT) | 266.74261335 |
| profit_factor | 1.1943710964452867 |
| sharpe | 4.707412131765382 |
| sortino | 10.930170809302597 |
| max_drawdown | 0.0896481513559791 |
| avg_profit | 0.004351618828462857 |
| avg_duration | 3 days, 17:32:00 |

## Gate status
- Top-15 is **entry-only**, candle-causal in backtest (data ≤ T).
- `exit_when_dropped` / drop-exit remains **false**.
- Prior A run had **0 trades** due to empty live Top-15 snapshot at advise-time; this run has **2426 trades**.

## Next
- B FreqAI backtest **not** run in this step (per instructions: report A first).
