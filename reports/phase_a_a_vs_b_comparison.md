# Phase A — Model A vs Model B

**Verdict:** `A_STILL_AHEAD` — Model B is **not** an upgrade. Do **not** start Phase B on this result.

Frozen baseline A was not re-run or re-optimized. B = A stack + Phase A FreqAI prediction gate (`prediction > 0`, `do_predict == 1`), historical candle Top-15 entry gate ON, drop-exit OFF.

## Comparable settings

| Setting | A / B |
|---------|-------|
| Requested timerange | `20240101-20260901` |
| Timeframe | `1d` |
| max_open_trades | 100 |
| stake | unlimited |
| dry_run | true |
| Fee | 0.10% worst-case Binance tier (same path for both) |
| Top-15 | candle-causal entry gate |
| Drop-exit | OFF |

## Effective windows (important)

| Model | Effective backtest window | Notes |
|-------|---------------------------|-------|
| **A (frozen)** | **2024-08-16 → 2026-09-01** | startup candles + local history |
| **B (FreqAI)** | **2025-05-01 → 2026-09-01** | FreqAI `train_period_days=180` warmup delays first tradable bar |

B’s shorter live window is expected for Phase A FreqAI, not a config bug. Absolute PnL is therefore **not** period-matched; B still underperforms on rate metrics (profit factor, expectancy, Sharpe/Sortino, avg trade) and trade count.

## Comparison table

| Metric | Model A (frozen) | Model B (FreqAI) |
|--------|------------------|------------------|
| trades | **2426** | **846** |
| win rate | 52.60% | 51.77% |
| profit | **+26.67% / +266.74 USDT** | **+5.71% / +57.06 USDT** |
| profit factor | 1.19 | 1.11 |
| expectancy | 0.110 USDT/trade | 0.067 USDT/trade |
| max drawdown | 8.96% | **6.31%** (lower) |
| Sharpe (closed trades) | 4.71 | 1.46 |
| Sortino (closed trades) | 10.93 | 3.07 |
| average trade | +0.435% | +0.268% |
| fees (sum) | n/a in export | n/a in export (fee rate 0.10% both) |
| average duration | 3d 17h 32m | 4d 13h 47m |

## Robustness read (not auto-success)

- **Trade count:** B has ~35% of A’s trades (846 vs 2426). Gate is binding; sample is thinner.
- **Profit / PF / expectancy / Sharpe / Sortino / avg trade:** all favor **A**.
- **Drawdown:** B’s max DD is lower (6.31% vs 8.96%) — the only clear B advantage, consistent with fewer/selectiver entries, not with higher edge.
- **Win rate:** essentially flat (52.6% vs 51.8%).
- **Duration:** B holds slightly longer.
- **Window bias:** even granting B a shorter FreqAI warmup window, absolute profit is far below A; risk-adjusted closed-trade Sharpe/Sortino remain much weaker.

**Conclusion:** Phase A FreqAI prediction gate does **not** improve the frozen Score4Window + Top-15 baseline on this local dataset. Keep A as the research baseline. Phase B (cross-sectional S1/S2/rank features, etc.) should **not** start from an assumption that B won.

## Artifacts

- `reports/phase_a_model_b_backtest.md` / `.json`
- `reports/phase_a_a_vs_b_comparison.md` / `.json`
- Frozen A: `reports/phase_a_baseline_a_after_top15_fix.md`
