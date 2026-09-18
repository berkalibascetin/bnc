# FreqAI Short-Term Leaderboard

- Generated: `2026-09-13T14:14:36.060836+00:00`
- Full timerange: `20260301-20260901`
- Pairs: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT
- ROI 10% / SL -10% / max_open_trades 5 / stake unlimited
- FreqAI train_period_days=120, backtest_period_days=30 (unchanged from 1d LB)
- Classifier labels: existing `up`/`down` (not BUY/HOLD/SELL)
- AI entries require Score4Window `total_score >= 2` confirmation (AI is filter, not replacement)
- Top-15 / drop-exit: OFF in this research config; universe is 5 majors only

- Research-only layer; Score4WindowStrategy and 1d FreqAI strategies untouched.
- Short-term strategies require Score4Window total_score>=2 + FreqAI confirmation.
- Classifier target vocabulary remains up/down (project FreqAI convention).
- MultiTarget horizons: 1h=6/12/24, 4h=2/3/6 candles; strong-move thresh=1% on ~24h.
- Pair universe = existing 5 majors (not 100+). Top-15 gate inactive here.
- Ranking uses Sharpe then lower DD then profit (not profit-only).
- Subperiods default to baseline + best-AI per TF for cost; set SHORTTERM_SUBPERIODS_ALL=1 for full grid.

## 4h results

| # | Strategy | TF | Trades | Profit% | WR% | PF | DD% | Sharpe | Sortino |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Score4Window (AI-siz) | 4h | 56 | 2.47 | 55.36 | 1.23 | 5.65 | 0.53 | 1.16 |
| 2 | CatBoost MultiClass Hybrid | 4h | 194 | 2.49 | 48.97 | 1.07 | 10.07 | 0.47 | 0.66 |
| 3 | LightGBM Classifier Hybrid | 4h | 215 | 0.79 | 49.77 | 1.02 | 7.66 | 0.17 | 0.22 |
| 4 | CatBoost Regressor | 4h | 5 | 0.84 | 60.00 | 1.20 | 4.00 | 0.05 | 5.42 |
| 5 | XGBoost Regressor | 4h | 46 | -0.21 | 52.17 | 0.99 | 7.93 | -0.02 | -0.03 |
| 6 | LightGBM MultiTarget Hybrid | 4h | 120 | -0.60 | 51.67 | 0.97 | 8.48 | -0.11 | -0.12 |
| 7 | LightGBM Regressor | 4h | 58 | -3.03 | 50.00 | 0.86 | 13.89 | -0.32 | -0.41 |
| 8 | CatBoost MultiTarget Hybrid | 4h | 83 | -4.36 | 46.99 | 0.75 | 7.83 | -0.79 | -0.93 |
| 9 | XGBoost Classifier Hybrid | 4h | 210 | -10.38 | 45.71 | 0.70 | 13.13 | -2.51 | -2.80 |

### vs Score4Window baseline

| Strategy | ΔProfit% | ΔDD% | ΔPF | ΔSharpe | ΔTrades |
|---|---:|---:|---:|---:|---:|
| CatBoost MultiClass Hybrid | 0.02 | 4.42 | -0.16 | -0.06 | 138 |
| LightGBM Classifier Hybrid | -1.68 | 2.01 | -0.21 | -0.36 | 159 |
| CatBoost Regressor | -1.63 | -1.65 | -0.03 | -0.49 | -51 |
| XGBoost Regressor | -2.67 | 2.28 | -0.24 | -0.55 | -10 |
| LightGBM MultiTarget Hybrid | -3.07 | 2.83 | -0.26 | -0.64 | 64 |
| LightGBM Regressor | -5.50 | 8.24 | -0.37 | -0.85 | 2 |
| CatBoost MultiTarget Hybrid | -6.83 | 2.19 | -0.48 | -1.33 | 27 |
| XGBoost Classifier Hybrid | -12.85 | 7.48 | -0.53 | -3.04 | 154 |

### Subperiod robustness

#### p1_mar_apr (`20260301-20260501`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | CatBoost MultiClass Hybrid | 62 | 9.36 | 1.81 | 4.96 |
| 2 | Score4Window (AI-siz) | 17 | -0.32 | 2.55 | -0.25 |

#### p2_may_jun (`20260501-20260701`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | Score4Window (AI-siz) | 23 | -4.25 | 5.90 | -3.34 |
| 2 | CatBoost MultiClass Hybrid | 76 | -4.89 | 7.95 | -3.46 |

#### p3_jul_aug (`20260701-20260901`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | Score4Window (AI-siz) | 28 | 8.19 | 1.06 | 5.72 |
| 2 | CatBoost MultiClass Hybrid | 62 | 7.08 | 2.93 | 3.45 |

## 1h results

| # | Strategy | TF | Trades | Profit% | WR% | PF | DD% | Sharpe | Sortino |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | LightGBM Regressor | 1h | 109 | 14.69 | 58.72 | 1.61 | 7.80 | 1.82 | 2.17 |
| 2 | XGBoost Regressor | 1h | 96 | 10.28 | 53.12 | 1.51 | 7.52 | 1.42 | 1.75 |
| 3 | Score4Window (AI-siz) | 1h | 62 | 3.88 | 56.45 | 1.20 | 9.47 | 0.52 | 0.98 |
| 4 | CatBoost Regressor | 1h | 4 | 0.05 | 50.00 | 1.03 | 2.03 | 0.00 | 0.01 |
| 5 | LightGBM MultiTarget Hybrid | 1h | 188 | -0.97 | 42.02 | 0.96 | 7.07 | -0.21 | -0.25 |
| 6 | CatBoost MultiTarget Hybrid | 1h | 168 | -4.17 | 43.45 | 0.83 | 8.28 | -0.89 | -1.07 |
| 7 | LightGBM Classifier Hybrid | 1h | 390 | -8.57 | 38.72 | 0.79 | 12.95 | -2.45 | -3.11 |
| 8 | CatBoost MultiClass Hybrid | 1h | 325 | -9.88 | 41.85 | 0.74 | 13.06 | -2.80 | -3.20 |
| 9 | XGBoost Classifier Hybrid | 1h | 366 | -14.44 | 37.98 | 0.70 | 18.77 | -3.87 | -4.52 |

### vs Score4Window baseline

| Strategy | ΔProfit% | ΔDD% | ΔPF | ΔSharpe | ΔTrades |
|---|---:|---:|---:|---:|---:|
| LightGBM Regressor | 10.81 | -1.66 | 0.41 | 1.29 | 47 |
| XGBoost Regressor | 6.40 | -1.95 | 0.31 | 0.89 | 34 |
| CatBoost Regressor | -3.82 | -7.43 | -0.18 | -0.52 | -58 |
| LightGBM MultiTarget Hybrid | -4.85 | -2.40 | -0.24 | -0.73 | 126 |
| CatBoost MultiTarget Hybrid | -8.05 | -1.18 | -0.37 | -1.41 | 106 |
| LightGBM Classifier Hybrid | -12.45 | 3.49 | -0.41 | -2.97 | 328 |
| CatBoost MultiClass Hybrid | -13.76 | 3.60 | -0.46 | -3.32 | 263 |
| XGBoost Classifier Hybrid | -18.31 | 9.30 | -0.50 | -4.39 | 304 |

### Subperiod robustness

#### p1_mar_apr (`20260301-20260501`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | LightGBM Regressor | 33 | 10.18 | 1.16 | 5.82 |
| 2 | Score4Window (AI-siz) | 24 | -0.52 | 4.57 | -0.24 |

#### p2_may_jun (`20260501-20260701`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | LightGBM Regressor | 42 | -5.04 | 9.80 | -1.46 |
| 2 | Score4Window (AI-siz) | 23 | -6.14 | 8.67 | -2.58 |

#### p3_jul_aug (`20260701-20260901`)

| # | Strategy | Trades | Profit% | DD% | Sharpe |
|---|---|---:|---:|---:|---:|
| 1 | Score4Window (AI-siz) | 29 | 12.09 | 1.63 | 6.19 |
| 2 | LightGBM Regressor | 33 | 7.37 | 1.37 | 4.01 |

## BEST AI vs BASELINE

| Timeframe | Baseline | Best AI | AI Advantage (Profit%) | DD Difference | Verdict |
|---|---|---|---:|---:|---|
| 4h | Score4Window (AI-siz) (2.47%) | CatBoost MultiClass Hybrid (2.49%) | 0.02 | 4.42 | AI profit artırdı fakat drawdown belirgin şekilde kötüleşti; otomatik olarak daha iyi kabul edilmedi. |
| 1h | Score4Window (AI-siz) (3.88%) | LightGBM Regressor (14.69%) | 10.81 | -1.66 | Bu model ileri test için aday. |

## Answers

**1. 1H'de AI, Score4Window'u geçiyor mu?**

Evet — LightGBM Regressor hem profit hem risk açısından baseline üstü.

**2. 4H'de AI, Score4Window'u geçiyor mu?**

Kısmen — CatBoost MultiClass Hybrid profit'te önde ama DD/risk iyileşmedi (otomatik galip sayılmadı).

**3. Hangi model en iyi?**

LightGBM Regressor on 1h (profit 14.69%, DD 7.80%, Sharpe 1.82)

**4. MultiTarget gerçekten classifier/regressor modellerinden daha iyi mi?**

Ortalama Sharpe — MultiTarget: -0.50, Classifier: -1.83, Regressor: 0.49.

**5. CatBoost mu LightGBM mi daha iyi?**

Ortalama Sharpe — CatBoost: -0.66, LightGBM: -0.18.

**6. 1H mi 4H mi bizim kısa vadeli hedefimize daha uygun görünüyor?**

1h (composite Sharpe/DD proxy).

**7. AI yalnızca profit artırıyor mu, yoksa DD'yi de iyileştiriyor mu?**

4h: Δprofit=0.02, ΔDD=4.42; 1h: Δprofit=10.81, ΔDD=-1.66

**8. AI'ın eklenmesi istatistiksel olarak anlamlı görünüyor mu?**

Trade sayıları: CatBoost MultiClass Hybrid=194, LightGBM Classifier Hybrid=215, CatBoost Regressor=5, XGBoost Regressor=46, LightGBM MultiTarget Hybrid=120, LightGBM Regressor=58, CatBoost MultiTarget Hybrid=83, XGBoost Classifier Hybrid=210. 1h/4h'de örneklem 1d'den daha zengin (120g train ≈612@4h / ≈2448@1h), ama tek dönem + sabit hiperparametre → keşifsel; production iddiası yok.

**9. Sonuçlar tek bir döneme bağımlı mı?**

4h: p1_mar_apr→CatBoost MultiClass Hybrid; p2_may_jun→Score4Window (AI-siz); p3_jul_aug→Score4Window (AI-siz) | 1h: p1_mar_apr→LightGBM Regressor; p2_may_jun→LightGBM Regressor; p3_jul_aug→Score4Window (AI-siz)

## Decision

En az bir TF'de AI hem profit hem risk açısından aday görünüyor; yine de production'a alınmadı — sadece ileri research.

No model promoted to production.
