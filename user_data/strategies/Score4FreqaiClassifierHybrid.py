# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
"""
FreqAI classifier hybrid: Score4Window-style features + up/down MultiClass target.

Works with:
  --freqaimodel CatboostClassifier
  --freqaimodel LightGBMClassifier
  --freqaimodel XGBoostClassifier
"""

from __future__ import annotations

import logging
from functools import reduce

import numpy as np
import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)


class Score4FreqaiClassifierHybrid(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False

    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    timeframe = "1d"
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
        dataframe["%-close-bb_lower-period"] = dataframe["close"] / bollinger["lower"]
        dataframe["%-relative_volume-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        # Score4Window-style directional window feature
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
        # Deterministic 4-window total score as a non-expanded feature
        s5 = np.sign(dataframe["close"] - dataframe["close"].shift(5))
        s10 = np.sign(dataframe["close"] - dataframe["close"].shift(10))
        s21 = np.sign(dataframe["close"] - dataframe["close"].shift(21))
        s42 = np.sign(dataframe["close"] - dataframe["close"].shift(42))
        dataframe["%-total_score"] = s5 + s10 + s21 + s42
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        label_period = int(self.freqai_info["feature_parameters"]["label_period_candles"])
        self.freqai.class_names = ["down", "up"]
        dataframe["&s-up_or_down"] = np.where(
            dataframe["close"].shift(-label_period) > dataframe["close"], "up", "down"
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            dataframe["do_predict"] == 1,
            dataframe["&s-up_or_down"] == "up",
            dataframe["volume"] > 0,
        ]
        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions), ["enter_long", "enter_tag"]
            ] = (1, "freqai_up")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            dataframe["do_predict"] == 1,
            dataframe["&s-up_or_down"] == "down",
            dataframe["volume"] > 0,
        ]
        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "exit_long"] = 1
        return dataframe
