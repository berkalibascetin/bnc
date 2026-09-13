# Binance Universe Validation Report

Generated at (UTC): `2026-09-12T11:03:30.365392+00:00`

## Scope

Universe expansion test only. Strategy logic was not modified.

## Final configuration

| Setting | Value |
|---|---|
| Exchange | `binance` |
| dry_run | `True` |
| timeframe | `1d` |
| max_open_trades | `5` |
| Strategy | `Score4WindowStrategy` |
| risk_pct | `3.0` (unchanged) |
| Pair count | **100** |

## Safety checks

- `dry_run == true`: **PASS**
- Futures/leverage not enabled: **PASS** (spot StaticPairList only)
- Strategy entry/exit/score/risk logic unchanged: **PASS**
- Must-include pairs present: **PASS** (`BTC/ETH/SOL/BNB/XRP`)

## Final pairlist (100 pairs)

```
BTC/USDT
ETH/USDT
SOL/USDT
BNB/USDT
XRP/USDT
ZEC/USDT
NEAR/USDT
SUI/USDT
DOGE/USDT
UNI/USDT
ENA/USDT
TRX/USDT
ADA/USDT
LINK/USDT
PEPE/USDT
TAO/USDT
AVAX/USDT
RAY/USDT
ARB/USDT
WLD/USDT
REZ/USDT
ETHFI/USDT
DASH/USDT
BCH/USDT
LTC/USDT
XLM/USDT
PAXG/USDT
TRUMP/USDT
AAVE/USDT
DOT/USDT
SOPH/USDT
ONDO/USDT
INJ/USDT
FET/USDT
PENGU/USDT
POL/USDT
LSK/USDT
MINA/USDT
APT/USDT
FIL/USDT
HBAR/USDT
AERO/USDT
BLUR/USDT
ZRO/USDT
ZEN/USDT
CAKE/USDT
PROM/USDT
SHIB/USDT
PENDLE/USDT
TIA/USDT
ICP/USDT
THETA/USDT
DOGS/USDT
MORPHO/USDT
IOST/USDT
CHZ/USDT
JST/USDT
RENDER/USDT
OP/USDT
EIGEN/USDT
VIRTUAL/USDT
ALGO/USDT
WBTC/USDT
TREE/USDT
ETC/USDT
SEI/USDT
ATOM/USDT
COTI/USDT
CRV/USDT
LDO/USDT
BONK/USDT
JTO/USDT
STRK/USDT
BERA/USDT
VET/USDT
WIF/USDT
RUNE/USDT
ORDI/USDT
STX/USDT
PYTH/USDT
EGLD/USDT
FLOKI/USDT
AR/USDT
LUNC/USDT
ENS/USDT
XTZ/USDT
DYDX/USDT
QNT/USDT
SAND/USDT
AXS/USDT
COMP/USDT
NEO/USDT
IOTA/USDT
GRT/USDT
SNX/USDT
NOT/USDT
FLOW/USDT
IMX/USDT
MANA/USDT
GMX/USDT
```

## Selection methodology

See `docs/binance_universe_methodology.md`.

- Methodology ID: `BINANCE_SPOT_USDT_CURATED100_QV24H_V1`
- Selection rule counts: `{"must_include": 5, "priority_established": 76, "curated_top_volume": 19}`
- Survivorship warning: **documented** (current listed universe ≠ historical top-100)

## Data availability

See `docs/binance_universe_data_availability.md`.

- Pairs checked: **100**
- Historically available (>=60 daily candles): **99**
- Insufficient history: AERO/USDT (58 candles) — kept in dry-run whitelist for live observation; partial for long backtests

## Validation results

| Check | Result |
|---|---|
| Unit tests (`pytest`) | **22 passed** |
| Config validation | **PASS** |
| Strategy load | **PASS** |
| Pairlist validation | **PASS** (100 USDT spot pairs) |
| Dry-run startup (this cloud host) | **PARTIAL** — reached `RUNNING` with Binance + dry_run + risk_pct=3.0 + max_open_trades=5; websocket market streams return HTTP 451 due to cloud geo-restriction. Use Windows host with normal Binance access for full dry-run observation. |
| Real trading | **NOT enabled** |

## Baseline comparison (offline backtest, SAME strategy)

Timerange: `20240912-20260912`, timeframe `1d`, `max_open_trades=5`, `risk_pct=3`.

> Using today's 100-coin membership for history is subject to **survivorship bias**.
> Compare signal discovery / capacity only; do not treat as strategy quality proof.

| Metric | 5-pair baseline | ~100-pair universe |
|---|---:|---:|
| Pairs scanned | 5 | 100 |
| Closed trades | 203 | 810 |
| Rejected entry signals (slots full) | 0 | 19219 |
| Total profit % | +6.81% | -4.37% |
| Max drawdown | 3.59% | 15.11% |
| Avg stake | ~19.6 USDT | ~11.6 USDT |

### Interpretation

- Broader universe increases opportunity discovery (203 → 810 closed trades; 19219 rejected entries while `max_open_trades=5`).
- Concurrent exposure intentionally unchanged (`max_open_trades=5`).
- Do not change strategy thresholds in response to this result in this task.

## What changed

- Config backup under `user_data/config_backups/`
- `user_data/config.json` → Binance dry-run StaticPairList (100 pairs)
- `user_data/config_binance_universe100.json`
- `user_data/config_baseline_5pairs_binance.json`
- Optional cloud mirror config for geo-restricted hosts
- Universe artifacts in `user_data/universes/`
- 1d OHLCV downloaded to `user_data/data/binance/` (gitignored)
- Docs in `docs/`
- Builder/download scripts in `scripts/`

## What did NOT change

- Score4WindowStrategy entry/exit/score/risk logic
- `risk_pct` default (=3.0)
- timeframe (=1d)
- `max_open_trades` (=5)
- No live trading / no futures / no leverage

## Recommended next step

On Windows (Binance reachable):

```powershell
freqtrade trade -c user_data/config.json --userdir user_data --strategy Score4WindowStrategy
```

Observe dry-run over multiple daily candles without changing strategy parameters.
