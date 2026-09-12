# pragma pylint: disable=missing-docstring, invalid-name
"""ATRVolatilityBreakout — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class ATRVolatilityBreakout(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 30
    process_only_new_candles = True
    use_exit_signal = False
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    atr_mult = DecimalParameter(0.5, 3.0, default=1.5, decimals=1, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        # breakout vs prior close +/- k*ATR (known at open conceptually; use prior ATR)
        dataframe["break_level"] = dataframe["close"].shift(1) + float(self.atr_mult.value) * dataframe["atr"].shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (dataframe["close"] > dataframe["break_level"]) & (dataframe["volume"] > 0)
        fresh = dataframe["close"].shift(1) <= dataframe["break_level"].shift(1)
        dataframe.loc[cond & fresh.fillna(False), ["enter_long", "enter_tag"]] = (1, "atr_bo")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

