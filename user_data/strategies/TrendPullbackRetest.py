# pragma pylint: disable=missing-docstring, invalid-name
"""TrendPullbackRetest — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class TrendPullbackRetest(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 220
    process_only_new_candles = True
    use_exit_signal = False
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    ema_trend = IntParameter(50, 250, default=100, space="buy", optimize=False, load=True)
    ema_pull = IntParameter(10, 50, default=20, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=int(self.ema_trend.value))
        dataframe["ema_pull"] = ta.EMA(dataframe, timeperiod=int(self.ema_pull.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        uptrend = dataframe["close"] > dataframe["ema_trend"]
        touch = dataframe["low"] <= dataframe["ema_pull"]
        reclaim = dataframe["close"] > dataframe["ema_pull"]
        cond = uptrend & touch & reclaim & (dataframe["volume"] > 0)
        fresh = ~(
            (dataframe["close"].shift(1) > dataframe["ema_trend"].shift(1))
            & (dataframe["low"].shift(1) <= dataframe["ema_pull"].shift(1))
            & (dataframe["close"].shift(1) > dataframe["ema_pull"].shift(1))
        )
        dataframe.loc[cond & fresh, ["enter_long", "enter_tag"]] = (1, "pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

