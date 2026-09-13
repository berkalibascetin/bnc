#!/usr/bin/env bash
# Model A (deterministic baseline) vs Model B (FreqAI Phase A) backtest helpers.
# Dry-run / research only. Does NOT place live orders.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TIMERANGE="${TIMERANGE:-20240101-20260901}"
CONFIG_A="${CONFIG_A:-user_data/config.json}"
CONFIG_B="${CONFIG_B:-user_data/config_freqai_dryrun.json}"

echo "== Model A: deterministic Score4Window + Top-15 (drop-exit OFF) =="
echo "freqtrade backtesting -c ${CONFIG_A} --strategy Score4WindowStrategy --timerange ${TIMERANGE} --export trades --breakdown month"
echo
echo "== Model B: Model A + FreqAI prediction gate =="
echo "freqtrade backtesting -c ${CONFIG_B} --strategy Score4WindowFreqaiStrategy --freqaimodel LightGBMRegressor --timerange ${TIMERANGE} --export trades --breakdown month"
echo
echo "Compare: total profit, trade count, win rate, PF, expectancy, avg trade, max DD, Sharpe, Sortino, duration, fees, exposure."
echo "Do not declare FreqAI superior without measuring OOS metrics."
