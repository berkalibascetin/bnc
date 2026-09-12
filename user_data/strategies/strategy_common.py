"""
Shared helpers for candidate strategies (backtest-only suite).

Risk model (documented):
  size_pct = risk_pct / atr_pct
  stake    = wallet * size_pct / 100
capped by max_position_pct (default 25).

This approximates "risk X% of equity per trade" when ATR% ≈ stop distance.
It is NOT identical to exchange stop-based risk if ROI/stoploss exits differ.
Score4Window keeps its own score * risk_pct / atr_pct formula.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
from pandas import DataFrame, Series


def atr_pct_series(dataframe: DataFrame, atr: Series) -> Series:
    return (atr / dataframe["close"]) * 100.0


def calc_size_pct(
    risk_pct: float,
    atr_pct: float,
    *,
    min_atr_pct: float = 0.1,
    max_position_pct: float = 25.0,
) -> float:
    if atr_pct is None or np.isnan(atr_pct) or atr_pct <= 0:
        return 0.0
    vol = max(float(atr_pct), float(min_atr_pct))
    size = float(risk_pct) / vol
    return float(min(max(size, 0.0), float(max_position_pct)))


def supertrend(dataframe: DataFrame, period: int = 10, multiplier: float = 3.0) -> DataFrame:
    """Classic Supertrend without lookahead (uses only current and past bars).

    Skips ATR warmup NaNs so bands do not permanently poison the series.
    """
    hl2 = (dataframe["high"] + dataframe["low"]) / 2.0
    atr = dataframe["atr"]
    basic_ub = (hl2 + multiplier * atr).to_numpy()
    basic_lb = (hl2 - multiplier * atr).to_numpy()
    close = dataframe["close"].to_numpy()
    n = len(dataframe)

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)

    for i in range(n):
        if np.isnan(basic_ub[i]) or np.isnan(basic_lb[i]):
            continue
        if i == 0 or np.isnan(final_upper[i - 1]) or np.isnan(final_lower[i - 1]):
            final_upper[i] = basic_ub[i]
            final_lower[i] = basic_lb[i]
            direction[i] = 1
            st[i] = final_lower[i]
            continue

        final_upper[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1])
            else final_upper[i - 1]
        )
        final_lower[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1])
            else final_lower[i - 1]
        )
        if direction[i - 1] == 1:
            direction[i] = -1 if close[i] < final_lower[i] else 1
        else:
            direction[i] = 1 if close[i] > final_upper[i] else -1
        st[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    out = dataframe.copy()
    out["st_line"] = st
    out["st_dir"] = direction
    return out


class RiskSizingMixin:
    """Mixin expecting DecimalParameter risk_pct / max_position_pct / min_atr_pct and atr_pct col."""

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        if self.dp is None:
            return proposed_stake
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return proposed_stake
        last = dataframe.iloc[-1]
        atr_pct = float(last.get("atr_pct", 0) or 0)
        size_pct = calc_size_pct(
            float(self.risk_pct.value),
            atr_pct,
            min_atr_pct=float(self.min_atr_pct.value),
            max_position_pct=float(self.max_position_pct.value),
        )
        if size_pct <= 0:
            return proposed_stake
        stake_currency = self.config.get("stake_currency", "USDT")
        capital = (
            float(self.wallets.get_total(stake_currency))
            if self.wallets is not None
            else float(max_stake)
        )
        if capital <= 0:
            return proposed_stake
        stake = capital * (size_pct / 100.0)
        stake = min(stake, float(max_stake))
        if min_stake is not None:
            stake = max(float(min_stake), stake)
        return stake
