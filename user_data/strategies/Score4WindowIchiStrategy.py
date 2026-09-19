# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
"""
Score4Window + Ichimoku hybrid (SCORE_4WINDOW_ICHI_V1)

Adapted from popular community ichiV1 (EMA fan + Ichimoku cloud) to our stack:

  * Score4Window ``total_score`` remains the PRIMARY entry gate.
  * Ichimoku cloud + EMA-fan magnitude are OPTIONAL confirmation filters
    (ON by default for this strategy; toggle via IntParameters).
  * Does NOT overwrite OHLC with Heikin-Ashi (would corrupt SW4 scoring).
  * Uses leading senkou spans only (no chikou / displaced cloud lookahead).
  * Keeps SW4 risk_pct position sizing, ROI/SL, and dry-run market orders.

Research notes baked in:
  - Community ichiV1 is widely copied; raw form uses buy/sell v2 API + HA OHLC.
  - Freqtrade docs: INTERFACE_VERSION 3 (enter_long / exit_long).
  - technical.ichimoku: avoid chikou_span; compare leading_senkou_span_*.
  - FreqAI (later): these columns can become features; SW4 stays the score core.
"""

from __future__ import annotations

from functools import reduce

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IntParameter, CategoricalParameter

from Score4WindowStrategy import Score4WindowStrategy
from ichi_confirm import crossed_below as _crossed_below, ichimoku_leading


# Re-export for tests / FreqAI feature hooks.
__all__ = ["Score4WindowIchiStrategy", "ichimoku_leading"]


class Score4WindowIchiStrategy(Score4WindowStrategy):
    """
    Strategy ID: SCORE_4WINDOW_ICHI_V1

    Entry = SW4 score gate AND (optional) Ichimoku/fan confirmation.
    """

    STRATEGY_ID = "SCORE_4WINDOW_ICHI_V1"

    # Ichimoku periods: classic daily defaults (uploaded ichiV1 used 20/60/120/30 on 5m).
    ichi_conversion = IntParameter(5, 30, default=9, space="buy", optimize=False, load=True)
    ichi_base = IntParameter(10, 60, default=26, space="buy", optimize=False, load=True)
    ichi_lag = IntParameter(20, 120, default=52, space="buy", optimize=False, load=True)

    # EMA fan (ichiV1 trend_close_* family), periods in bars of the strategy timeframe.
    fan_fast = IntParameter(3, 48, default=12, space="buy", optimize=False, load=True)
    fan_slow = IntParameter(24, 200, default=96, space="buy", optimize=False, load=True)
    buy_min_fan_magnitude_gain = DecimalParameter(
        1.000, 1.020, default=1.002, decimals=3, space="buy", optimize=False, load=True
    )
    buy_fan_magnitude_shift_value = IntParameter(
        1, 6, default=3, space="buy", optimize=False, load=True
    )

    # How many EMA levels must sit above the cloud (1=close only … up to slow).
    buy_trend_above_senkou_level = IntParameter(
        1, 4, default=1, space="buy", optimize=False, load=True
    )
    # Require close > open on Heikin-Ashi of that bar scale? We use EMA(close)>EMA(open)
    # proxies without mutating candles (bullish fan levels 1..3).
    buy_trend_bullish_level = IntParameter(
        0, 3, default=2, space="buy", optimize=False, load=True
    )

    enable_ichi_filter = IntParameter(0, 1, default=1, space="buy", optimize=False, load=True)
    enable_ichi_exit = IntParameter(0, 1, default=1, space="buy", optimize=False, load=True)
    sell_trend_indicator = CategoricalParameter(
        ["trend_close_mid", "trend_close_slow", "kijun_sen"],
        default="trend_close_mid",
        space="sell",
        optimize=False,
        load=True,
    )

    # Need enough history for slow fan + ichi lag.
    startup_candle_count: int = 120

    plot_config = {
        "main_plot": {
            "leading_senkou_span_a": {
                "color": "green",
                "fill_to": "leading_senkou_span_b",
                "fill_label": "Ichimoku Cloud (leading)",
                "fill_color": "rgba(255,76,46,0.15)",
            },
            "leading_senkou_span_b": {},
            "trend_close_fast": {"color": "#FF5733"},
            "trend_close_mid": {"color": "#E3FF33"},
            "trend_close_slow": {"color": "#33FF7D"},
        },
        "subplots": {
            "score": {
                "total_score": {"color": "blue"},
            },
            "fan": {
                "fan_magnitude": {"color": "orange"},
                "fan_magnitude_gain": {"color": "purple"},
            },
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)

        # EMA fan on raw close/open (no Heikin-Ashi OHLC overwrite).
        f_fast = int(self.fan_fast.value)
        f_mid = max(f_fast * 2, f_fast + 1)
        f_slow = int(self.fan_slow.value)
        if f_slow <= f_mid:
            f_slow = f_mid + 1

        dataframe["trend_close_fast"] = ta.EMA(dataframe["close"], timeperiod=f_fast)
        dataframe["trend_close_mid"] = ta.EMA(dataframe["close"], timeperiod=f_mid)
        dataframe["trend_close_slow"] = ta.EMA(dataframe["close"], timeperiod=f_slow)
        dataframe["trend_open_fast"] = ta.EMA(dataframe["open"], timeperiod=f_fast)
        dataframe["trend_open_mid"] = ta.EMA(dataframe["open"], timeperiod=f_mid)
        dataframe["trend_open_slow"] = ta.EMA(dataframe["open"], timeperiod=f_slow)

        dataframe["fan_magnitude"] = (
            dataframe["trend_close_fast"] / dataframe["trend_close_slow"]
        )
        dataframe["fan_magnitude_gain"] = (
            dataframe["fan_magnitude"] / dataframe["fan_magnitude"].shift(1)
        )

        ichi = ichimoku_leading(
            dataframe,
            conversion_line_period=int(self.ichi_conversion.value),
            base_line_periods=int(self.ichi_base.value),
            laggin_span=int(self.ichi_lag.value),
        )
        for key, series in ichi.items():
            dataframe[key] = series

        # Convenience aliases used by plot / exit selector.
        dataframe["senkou_a"] = dataframe["leading_senkou_span_a"]
        dataframe["senkou_b"] = dataframe["leading_senkou_span_b"]

        dataframe["filt_ichi"] = self._ichi_confirm_mask(dataframe).astype(int)
        return dataframe

    def _ichi_confirm_mask(self, dataframe: DataFrame):
        """Vectorized ichiV1-style confirmation (causal)."""
        conditions: list = []
        level = int(self.buy_trend_above_senkou_level.value)
        cloud_a = dataframe["leading_senkou_span_a"]
        cloud_b = dataframe["leading_senkou_span_b"]

        # Price / EMA fan above cloud.
        if level >= 1:
            conditions.append(dataframe["close"] > cloud_a)
            conditions.append(dataframe["close"] > cloud_b)
        if level >= 2:
            conditions.append(dataframe["trend_close_fast"] > cloud_a)
            conditions.append(dataframe["trend_close_fast"] > cloud_b)
        if level >= 3:
            conditions.append(dataframe["trend_close_mid"] > cloud_a)
            conditions.append(dataframe["trend_close_mid"] > cloud_b)
        if level >= 4:
            conditions.append(dataframe["trend_close_slow"] > cloud_a)
            conditions.append(dataframe["trend_close_slow"] > cloud_b)

        bull = int(self.buy_trend_bullish_level.value)
        if bull >= 1:
            conditions.append(dataframe["trend_close_fast"] > dataframe["trend_open_fast"])
        if bull >= 2:
            conditions.append(dataframe["trend_close_mid"] > dataframe["trend_open_mid"])
        if bull >= 3:
            conditions.append(dataframe["trend_close_slow"] > dataframe["trend_open_slow"])

        conditions.append(
            dataframe["fan_magnitude_gain"] >= float(self.buy_min_fan_magnitude_gain.value)
        )
        conditions.append(dataframe["fan_magnitude"] > 1.0)

        shift_n = int(self.buy_fan_magnitude_shift_value.value)
        for x in range(shift_n):
            conditions.append(
                dataframe["fan_magnitude"].shift(x + 1) < dataframe["fan_magnitude"]
            )

        if not conditions:
            return dataframe["close"] > 0
        return reduce(lambda a, b: a & b, conditions)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Primary gate: Score4Window (parent).
        dataframe = super().populate_entry_trend(dataframe, metadata)

        if int(self.enable_ichi_filter.value) != 1:
            return dataframe

        ichi_ok = dataframe["filt_ichi"] == 1
        # Keep SW4 entries only where Ichimoku/fan also confirms.
        entered = dataframe["enter_long"] == 1
        dataframe.loc[entered & ~ichi_ok, "enter_long"] = 0
        dataframe.loc[entered & ichi_ok, "enter_tag"] = (
            dataframe.loc[entered & ichi_ok, "enter_tag"].astype(str) + "|ichi"
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        if int(self.enable_ichi_exit.value) != 1:
            return dataframe

        sell_col = str(self.sell_trend_indicator.value)
        if sell_col not in dataframe.columns:
            sell_col = "trend_close_mid"

        dataframe.loc[
            _crossed_below(dataframe["close"], dataframe[sell_col]),
            ["exit_long", "exit_tag"],
        ] = (1, "ichi_fan_cross")
        return dataframe
