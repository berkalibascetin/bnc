# pragma pylint: disable=missing-docstring, invalid-name
"""RSIMeanReversion — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class RSIMeanReversion(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 30
    process_only_new_candles = True
    use_exit_signal = True
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=False, load=True)
    rsi_buy = IntParameter(20, 40, default=30, space="buy", optimize=False, load=True)
    rsi_exit = IntParameter(45, 70, default=55, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=int(self.rsi_period.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        lvl = int(self.rsi_buy.value)
        cond = (dataframe["rsi"] < lvl) & (dataframe["rsi"].shift(1) >= lvl) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "rsi_mr")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = dataframe["rsi"] > int(self.rsi_exit.value)
        dataframe.loc[cond, ["exit_long", "exit_tag"]] = (1, "rsi_ex")
        return dataframe

