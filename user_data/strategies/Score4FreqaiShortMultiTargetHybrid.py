# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
"""
Short-term FreqAI MultiTarget hybrid (research only).

Horizons (config timeframe driven):
  1h: 6 / 12 / 24 candles (~6h / 12h / 24h)
  4h: 2 / 3 / 6 candles (~8h / 12h / 24h)

Targets keep existing MultiTarget style:
  direction classes with distinct strings across columns
  + move-size on the long (≈24h) horizon

Entry: Score4Window total_score >= 2 AND all three direction targets == up.
"""

from __future__ import annotations

import logging
from functools import reduce

import numpy as np
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IStrategy

from score4window_scoring import apply_score4window_scores, DEFAULT_ENTRY_SCORE_THRESHOLD

logger = logging.getLogger(__name__)

# Absolute move threshold on ≈24h horizon (short-term; 1d leaderboard used 0.03)
SHORT_STRONG_MOVE = 0.01


def _horizons_for_timeframe(timeframe: str) -> dict[str, int]:
    tf = (timeframe or "1h").lower()
    if tf == "4h":
        return {"short": 2, "mid": 3, "long": 6}
    # default 1h (and any other short TF research default)
    return {"short": 6, "mid": 12, "long": 24}


class Score4FreqaiShortMultiTargetHybrid(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False

    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    timeframe = "1h"
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count: int = 42

    order_types = {
        "entry": "market",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi-period"] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx-period"] = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-sma-period"] = ta.SMA(dataframe, timeperiod=period)
        dataframe["%-ema-period"] = ta.EMA(dataframe, timeperiod=period)
        dataframe["%-roc-period"] = ta.ROC(dataframe, timeperiod=period)
        dataframe["%-atr-period"] = ta.ATR(dataframe, timeperiod=period)

        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=period, stds=2.0
        )
        dataframe["%-bb_width-period"] = (
            bollinger["upper"] - bollinger["lower"]
        ) / bollinger["mid"]
        dataframe["%-relative_volume-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        dataframe["%-score_window-period"] = np.sign(
            dataframe["close"] - dataframe["close"].shift(period)
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-pct-change"] = dataframe["close"].pct_change()
        dataframe["%-raw_volume"] = dataframe["volume"]
        dataframe["%-raw_price"] = dataframe["close"]
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-day_of_week"] = (dataframe["date"].dt.dayofweek + 1) / 7
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour / 23.0
        apply_score4window_scores(dataframe)
        dataframe["%-total_score"] = dataframe["total_score"]
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        hz = _horizons_for_timeframe(str(self.timeframe))
        # Distinct class strings across targets (MultiTarget requirement)
        for name, n in hz.items():
            future = dataframe["close"].shift(-n)
            dataframe[f"&s-dir_{name}"] = np.where(
                future > dataframe["close"], f"up_{name}", f"down_{name}"
            )

        long_n = hz["long"]
        ret_long = dataframe["close"].shift(-long_n) / dataframe["close"] - 1.0
        dataframe["&s-move_long"] = np.where(
            ret_long.abs() >= SHORT_STRONG_MOVE, "strong_long", "weak_long"
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        apply_score4window_scores(dataframe)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            dataframe["total_score"] >= DEFAULT_ENTRY_SCORE_THRESHOLD,
            dataframe["do_predict"] == 1,
            dataframe["&s-dir_short"] == "up_short",
            dataframe["&s-dir_mid"] == "up_mid",
            dataframe["&s-dir_long"] == "up_long",
            dataframe["volume"] > 0,
        ]
        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions), ["enter_long", "enter_tag"]
            ] = (1, "s4_mt_all_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            dataframe["do_predict"] == 1,
            dataframe["&s-dir_long"] == "down_long",
            dataframe["volume"] > 0,
        ]
        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "exit_long"] = 1
        return dataframe
