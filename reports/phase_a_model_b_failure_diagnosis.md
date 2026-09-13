# Phase A — Model B failure diagnosis

Frozen A unchanged. Phase B not started. Diagnosis only.

## Setup
- A: `backtest-result-2026-09-13_12-04-47.zip` (2426 trades)
- B: `backtest-result-2026-09-13_12-14-29.zip` (846 trades)
- Predictions: 75517 unique pair/date rows
- Default B gate: `do_predict==1` and `pred > 0`
- Filter study window: A trades with `open_date >= 2025-05-01`

## 1) A trades B would filter (B window)

| Set | trades | win_rate | profit_abs | PF | expectancy | avg_profit_ratio |
|-----|--------|----------|------------|----|------------|------------------|
| A in B window | 1605 | 0.5233644859813084 | 160.57770768999995 | 1.1662904128676888 | 0.1000484160062305 | 0.0037948722691092604 |
| Would PASS gate | 669 | 0.5216741405082213 | 60.16520633 | 1.1524687922422405 | 0.08993304384155455 | 0.0031121596735896686 |
| Filtered by gate | 936 | 0.5245726495726496 | 100.41250136 | 1.1758415978011818 | 0.10727831341880341 | 0.004282836720394098 |
| Missing prediction | 0 | — | — | — | — | — |

### Reject breakdown
```json
{
  "a_trades_in_b_window": 1605,
  "missing_prediction": 0,
  "do_predict_ne_1": 4,
  "pred_le_threshold": 932,
  "passed_gate": 669,
  "filtered_by_gate": 936
}
```

## 2) B-selected vs A returns
- B actual avg profit_ratio: `0.0026754811066404065`
- A (B window) avg profit_ratio: `0.0037948722691092604`
- A∩pass-gate avg profit_ratio: `0.0031121596735896686`
- A∩filtered avg profit_ratio: `0.004282836720394098`
- B actual stats: `{"trades": 846, "win_rate": 0.5177304964539007, "total_profit_abs": 57.061021, "profit_factor": 1.1106319439757923, "expectancy": 0.06744801536643026, "avg_profit_ratio": 0.0026754811066404065, "max_drawdown_approx": 0.06277113342999997}`

## 3) Prediction distribution (B window)
```json
{
  "n": 48087,
  "mean": 0.0005350467364251746,
  "std": 0.027626407116860575,
  "p10": -0.03277421015028046,
  "p25": -0.016043640222107913,
  "p50": 0.0,
  "p75": 0.016299032054812052,
  "p90": 0.0339245842488955,
  "frac_gt_0": 0.4985339072930314,
  "frac_gt_0_005": 0.4129390479755443,
  "frac_gt_0_01": 0.3360575623349346,
  "frac_lt_0": 0.49304385800736167,
  "do_predict_1_frac": 0.991577765300393
}
```

## 4) Threshold sweep (A entries in B window with do_predict==1)

| threshold | trades | pass_rate | profit_abs | PF | expectancy | approx_maxDD |
|-----------|--------|-----------|------------|----|------------|--------------|
| -0.02 | 1151 | 0.719 | 99.01 | 1.1358904978707196 | 0.0860212754387489 | 0.06879025631999999 |
| -0.01 | 902 | 0.563 | 68.68 | 1.1224690355828568 | 0.07614502212860312 | 0.046746379890000016 |
| -0.005 | 784 | 0.490 | 66.93 | 1.1413706052566 | 0.08537405192602038 | 0.050592195189999994 |
| 0.0 | 669 | 0.418 | 60.17 | 1.1524687922422405 | 0.08993304384155455 | 0.052612895899999984 |
| 0.005 | 550 | 0.344 | 40.96 | 1.1299985504331491 | 0.07448116447272725 | 0.05290321152 |
| 0.01 | 440 | 0.275 | 28.18 | 1.1148989833458127 | 0.0640498673409091 | 0.039481019900000004 |
| 0.02 | 272 | 0.170 | 5.86 | 1.0375909159550087 | 0.02153932470588238 | 0.029054709610000007 |
| 0.03 | 185 | 0.116 | -17.53 | 0.8493269854935588 | -0.09477873000000002 | 0.03927975660000001 |
| 0.05 | 75 | 0.047 | -8.05 | 0.8331521810957851 | -0.10737347066666665 | 0.024908666840000003 |

## 5) Score / market conditions
### Passed
```json
{
  "n": 669,
  "avg_pred": 0.022549118520588107,
  "avg_entry_score": 3.327354260089686,
  "avg_btc_ret_5d": 0.004547553392402682,
  "avg_profit_ratio": 0.0031121596735896686,
  "win_rate": 0.5216741405082213,
  "score_ge_2_frac": 1.0,
  "btc_down_frac": 0.4618834080717489
}
```
### Filtered
```json
{
  "n": 936,
  "avg_pred": -0.02390804619264796,
  "avg_entry_score": 3.4006410256410255,
  "avg_btc_ret_5d": 0.008006761302106046,
  "avg_profit_ratio": 0.004282836720394098,
  "win_rate": 0.5245726495726496,
  "score_ge_2_frac": 1.0,
  "btc_down_frac": 0.45405982905982906
}
```

## 6) Low trade-count root cause
```json
{
  "a_all_trades": 2426,
  "a_trades_in_b_effective_window": 1605,
  "window_reduction_frac": 0.3384171475680132,
  "of_window_missing_pred_frac": 0.0,
  "of_window_filtered_by_threshold_or_dopredict_frac": 0.5831775700934579,
  "of_window_passed_frac": 0.41682242990654206,
  "b_actual_trades": 846,
  "primary_drivers": [
    "FreqAI warmup shortens B's effective window vs A (large trade-count cut before AI gate).",
    "Among A entries with predictions, pred<=0 threshold rejects more than do_predict!=1.",
    "Predictions are not strongly skewed positive; >0 threshold removes a large share.",
    "1d forward-return target poorly aligned with multi-day ROI/SL exits \u2014 wrong learning horizon.",
    "Filtered-out A trades had HIGHER expectancy than passed ones \u2014 gate removes good trades."
  ]
}
```

## 7) Target vs exit structure
```json
{
  "avg_hold_days": 3.7304204451772467,
  "median_hold_days": 1.0,
  "frac_hold_gt_1d": 0.4802143446001649,
  "frac_hold_ge_3d": 0.3520197856553998,
  "roi_exit_frac": 0.5226710634789777,
  "stoploss_exit_frac": 0.47155812036273703,
  "target_horizon_days": 1,
  "minimal_roi": {
    "0": 0.1
  },
  "stoploss": -0.1,
  "alignment_note": "Target=1d forward return; exits are \u00b110% ROI/SL over multi-day holds \u2014 horizon mismatch."
}
```
- A exits: `{'roi': 1268, 'stop_loss': 1144, 'force_exit': 14}`
- B exits: `{'roi': 433, 'stop_loss': 404, 'force_exit': 9}`

## Diagnosis summary
- FreqAI warmup shortens B's effective window vs A (large trade-count cut before AI gate).
- Among A entries with predictions, pred<=0 threshold rejects more than do_predict!=1.
- Predictions are not strongly skewed positive; >0 threshold removes a large share.
- 1d forward-return target poorly aligned with multi-day ROI/SL exits — wrong learning horizon.
- Filtered-out A trades had HIGHER expectancy than passed ones — gate removes good trades.

## Policy
- No Phase B implementation.
- Frozen A not modified.
- Threshold sweep is diagnostic, not an optimization claim.

