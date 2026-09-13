# Phase A — Model B backtest (FreqAI gate)

- Timerange requested: `20240101-20260901`
- Strategy: `Score4WindowFreqaiStrategy` + `LightGBMRegressor`
- Elapsed: `820.5147092342377` sec
- Drop-exit: OFF; historical candle Top-15 entry gate: ON
- Baseline A: frozen (not re-run / not optimized)

## B metrics

- trades: `846`
- win_rate: `0.5177304964539007`
- total_profit: `57.061021`
- profit_pct: `0.057061020999999996`
- profit_factor: `1.1106319439757923`
- expectancy: `0.06744801536643019`
- max_drawdown: `0.0631138788084271`
- sharpe: `1.4638150119749376`
- sortino: `3.066270899340186`
- avg_profit: `0.0026754811066404065`
- fees: `None`
- avg_duration: `4 days, 13:47:00`
- backtest_start: `2025-05-01 00:00:00`
- backtest_end: `2026-09-01 00:00:00`

## Frozen A (reference)

- strategy: `Score4WindowStrategy`
- effective_timerange: `2024-08-16 00:00:00 → 2026-09-01 00:00:00`
- timeframe: `1d`
- trades: `2426`
- win_rate: `0.5259686727122836`
- profit_pct: `0.26674261335`
- total_profit: `266.74261335`
- profit_factor: `1.1943710964452867`
- sharpe: `4.707412131765382`
- sortino: `10.930170809302597`
- max_drawdown: `0.0896481513559791`
- avg_profit: `0.004351618828462857`
- avg_duration: `3 days, 17:32:00`
- expectancy: `0.10995161308738664`
- fees: `None`
