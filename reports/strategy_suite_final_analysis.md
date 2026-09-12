# Strategy Backtest Suite — Final Analysis

**Date:** 2026-09-12  
**Scope:** Research backtests only (no live trading, no hyperopt)  
**Engine:** Freqtrade backtesting  
**Pairs:** BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT  
**Exchange data:** Binance via cloudmirror (`data-api.binance.vision`)  
**Config:** `user_data/config_suite_binance5_cloudmirror.json`

## Decisions (where config was incomplete)

| Topic | Decision |
|---|---|
| Pair universe | 5 liquid USDT pairs (matches prior baseline harness; full 100-pair dry-run list too slow for 273-job matrix) |
| Timeframes | **1d / 4h / 1h** tested. **5m/15m skipped** (not present in local data; full history download too large for this pass) |
| Period F (2024-03-12→2026-09-12) | **SKIPPED** — local OHLCV starts ~2024-07-05 |
| Risk 2% / 3% / 5% | Modeled as `size_pct = risk_pct / atr_pct` (cap 25%). Score4Window uses `score * risk_pct / atr_pct`. Same ROI 10% / SL −10% as baseline |
| Higher risk ≠ better | Rankings use Sharpe / PF / expectancy / DD — not raw return alone |
| Hyperopt | Not run (per brief) |

## Artifacts

- `reports/strategy_backtest_results.csv` (273 runs)
- `reports/strategy_summary.csv`
- `reports/strategy_suite_report.md` / `.json`
- Copies at repo root: `strategy_backtest_results.csv`, `strategy_summary.csv`

## Lookahead

`freqtrade lookahead-analysis` on Score4Window, DonchianBreakout, RSIMomentum, TimeSeriesMomentum, MACDMomentum (**1d**, timerange covering recent year):

**No bias detected** (0 biased signals / exits).

## Headline rankings

1. **BEST OVERALL (robust):** Score4WindowStrategy — only strategy with **3 STRONG** period tags (A_1m, B_6m, E_2y)
2. **BEST SHORT TERM (A_1m):** Score4WindowStrategy — Ret≈3.36%, PF≈5.4, Sharpe≈8.6, 19 trades
3. **BEST MEDIUM TERM (B_6m):** Score4WindowStrategy — Ret≈2.49%, PF≈1.79, Sharpe≈1.08, 42 trades
4. **BEST LONG TERM (E_2y):** Score4WindowStrategy — Ret≈6.81%, PF≈1.42, Sharpe≈0.82, 203 trades
5. **MOST ACTIVE QUALITY:** Score4WindowStrategy (highest trade count among quality-tagged runs)
6. **LOWEST DRAWDOWN (among non-fail multi-period):** VWAPPullback tends to keep DD lower than Score4Window on C_1y, but expectancy still negative there
7. **BEST PROFIT FACTOR (short windows):** Score4Window A_1m (PF≈5.4); over full matrix many alts inflate PF with few trades
8. **BEST RISK/REWARD:** Score4Window on A_1m / B_6m (Sortino strong); alts do not beat it consistently
9. **BEST OOS / ROBUSTNESS:** Score4Window (3 active periods). Next: RSIMomentum, MACDMomentum, TimeSeriesMomentum, DonchianBreakout, ATRVolatilityBreakout, BollingerBreakout (2 periods each)
10. **SCORE4WINDOW VS BEST ALT:** On **C_1y (2025-09→2026-09)** almost everything **FAIL**s (negative expectancy), including Score4Window. No alternative earns a clean pass on that window with default rules. Prefer multi-period robustness over C_1y-only ROI.

## Classification summary (all 273 runs)

| Status | Count |
|---|---|
| FAIL | 177 |
| ACTIVE_CANDIDATE | 63 |
| WATCH | 17 |
| LOW_ACTIVITY | 13 |
| STRONG_CANDIDATE | 3 (all Score4Window) |

## Important regime note

**C_1y and D_13m are hostile** for default-parameter trend/breakout rules on this 5-pair set. Strategies that look fine on B_6m / E_2y often collapse on C_1y → treat single-window winners as **OVERFIT_RISK** unless they also pass other periods.

## Risk sweep (C_1y, 1d)

Raising risk 2→3→5 mainly **scales drawdown**; it does **not** rescue negative-expectancy systems. Do not prefer 5% risk on return alone.

## Timeframe sweep

On this matrix, **1d >> 4h/1h** for quality. Lower TFs produced more trades but worse PF/Sharpe / deeper DD for most candidates (including Score4Window).

## Candidate shortlist for later (controlled) hyperopt

Only after OOS holdout design:

1. Score4WindowStrategy (baseline champion)
2. RSIMomentum
3. MACDMomentum
4. TimeSeriesMomentum
5. DonchianBreakout
6. ATRVolatilityBreakout
7. BollingerBreakout
8. VWAPPullback (activity/DD interesting, verify expectancy)

**Not recommended now:** Supertrend (weak / period-fragile after fix), pure mean-reversion set (RSI/ZScore/Bollinger MR), TTMSqueeze defaults, TrendPullbackRetest defaults.

## Supertrend note

Initial Supertrend helper had ATR-warmup NaN poisoning (0 trades). Fixed in `strategy_common.supertrend`; suite re-ran Supertrend jobs. Still not a top robustness pick.
