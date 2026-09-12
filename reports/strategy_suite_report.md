# Strategy Suite Report

Jobs: 273 | FAIL-core note: C_1y is harsh for defaults

## BEST_OVERALL
- Score4WindowStrategy | TF=1d | E_2y | Ret=6.8051 DD=3.5922 PF=1.4231 Exp=0.7481 Sharpe=0.821 Trades=203 Status=STRONG_CANDIDATE

## BEST_SHORT_TERM
- Score4WindowStrategy | TF=1d | A_1m | Ret=3.3593 DD=0.4134 PF=5.4023 Exp=4.5941 Sharpe=8.64 Trades=19 Status=STRONG_CANDIDATE

## BEST_MEDIUM_TERM
- Score4WindowStrategy | TF=1d | B_6m | Ret=2.4875 DD=1.2821 PF=1.7855 Exp=1.7956 Sharpe=1.0821 Trades=42 Status=STRONG_CANDIDATE

## BEST_LONG_TERM
- Score4WindowStrategy | TF=1d | E_2y | Ret=6.8051 DD=3.5922 PF=1.4231 Exp=0.7481 Sharpe=0.821 Trades=203 Status=STRONG_CANDIDATE

## MOST_ACTIVE_QUALITY
- Score4WindowStrategy | TF=1d | A_1m | Ret=3.3593 DD=0.4134 PF=5.4023 Exp=4.5941 Sharpe=8.64 Trades=19 Status=STRONG_CANDIDATE

## LOWEST_DRAWDOWN
- RSIMeanReversion | TF=1d | C_1y | Ret=-0.1772 DD=0.4558 PF=0.7529 Exp=-0.569 Sharpe=-0.1546 Trades=21 Status=FAIL

## BEST_PROFIT_FACTOR
- VWAPPullback | TF=1d | C_1y | Ret=0.0805 DD=0.5733 PF=1.0805 Exp=-0.592 Sharpe=0.0513 Trades=27 Status=FAIL

## BEST_RISK_REWARD
- VWAPPullback | TF=1d | C_1y | Ret=0.0805 DD=0.5733 PF=1.0805 Exp=-0.592 Sharpe=0.0513 Trades=27 Status=FAIL

## SCORE4WINDOW VS BEST ALT (C_1y 1d r3)
- baseline: Score4WindowStrategy | TF=1d | C_1y | Ret=0.0833 DD=3.72 PF=1.0114 Exp=-0.9284 Sharpe=0.0189 Trades=74 Status=FAIL
- best_alt: VWAPPullback | TF=1d | C_1y | Ret=0.0805 DD=0.5733 PF=1.0805 Exp=-0.592 Sharpe=0.0513 Trades=27 Status=FAIL

## Robustness
- {'Strategy': 'Score4WindowStrategy', 'ActivePeriods': 3}
- {'Strategy': 'RSIMomentum', 'ActivePeriods': 2}
- {'Strategy': 'MACDMomentum', 'ActivePeriods': 2}
- {'Strategy': 'TimeSeriesMomentum', 'ActivePeriods': 2}
- {'Strategy': 'DonchianBreakout', 'ActivePeriods': 2}

## Top summaries
- Score4WindowStrategy: STRONG_CANDIDATE avgSharpe=2.113 avgPF=2.1248 avgRet=2.5499 bestTF=1d
- RSIMomentum: ACTIVE_CANDIDATE avgSharpe=2.0457 avgPF=0.997 avgRet=0.2167 bestTF=1d
- TimeSeriesMomentum: ACTIVE_CANDIDATE avgSharpe=1.5348 avgPF=1.1464 avgRet=0.2397 bestTF=1d
- VWAPPullback: ACTIVE_CANDIDATE avgSharpe=1.184 avgPF=5.064 avgRet=0.2694 bestTF=1d
- ATRVolatilityBreakout: ACTIVE_CANDIDATE avgSharpe=1.0061 avgPF=2.1593 avgRet=0.1748 bestTF=1d
- MultiIndicatorConfluence: ACTIVE_CANDIDATE avgSharpe=0.9482 avgPF=2.338 avgRet=-0.0514 bestTF=1d
- MACDMomentum: ACTIVE_CANDIDATE avgSharpe=0.9228 avgPF=2.8205 avgRet=0.3458 bestTF=1d
- KeltnerChannel: ACTIVE_CANDIDATE avgSharpe=0.8785 avgPF=2.2297 avgRet=0.0802 bestTF=1d
- DonchianBreakout: ACTIVE_CANDIDATE avgSharpe=0.7385 avgPF=1.7833 avgRet=0.1778 bestTF=1d
- BollingerBreakout: ACTIVE_CANDIDATE avgSharpe=0.7127 avgPF=1.784 avgRet=0.1564 bestTF=1d

## Notes
- **period_F_skipped**: Local Binance OHLCV starts ~2024-07-05; F(2024-03-12) insufficient
- **timeframes_5m_15m**: Not present locally; tested 1h+4h+existing 1d
- **pairs**: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
- **risk_model**: size_pct=risk_pct/atr_pct (Score4Window * score); ROI10%/SL-10%
- **hyperopt**: not run
- **C_1y_regime**: Most default strategies FAIL on 2025-09→2026-09; prefer multi-period robustness
