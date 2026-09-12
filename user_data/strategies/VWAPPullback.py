# pragma pylint: disable=missing-docstring, invalid-name
"""VWAPPullback — backtest-only candidate. Not for live."""

from pandas import DataFrame
import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class VWAPPullback(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 60
    process_only_new_candles = True
    use_exit_signal = False
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    vwap_len = IntParameter(10, 60, default=20, space="buy", optimize=False, load=True)
    ema_trend = IntParameter(30, 100, default=50, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = int(self.vwap_len.value)
        tp = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        vol = dataframe["volume"].replace(0, np.nan)
        # rolling VWAP proxy
        dataframe["vwap"] = (tp * dataframe["volume"]).rolling(n).sum() / dataframe["volume"].rolling(n).sum()
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=int(self.ema_trend.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        uptrend = dataframe["close"] > dataframe["ema_trend"]
        touch = dataframe["low"] <= dataframe["vwap"]
        reclaim = dataframe["close"] > dataframe["vwap"]
        cond = uptrend & touch & reclaim & (dataframe["volume"] > 0)
        fresh = ~((dataframe["low"].shift(1) <= dataframe["vwap"].shift(1)) & (dataframe["close"].shift(1) > dataframe["vwap"].shift(1)))
        dataframe.loc[cond & fresh, ["enter_long", "enter_tag"]] = (1, "vwap_pb")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

