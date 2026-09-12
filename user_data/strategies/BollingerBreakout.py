# pragma pylint: disable=missing-docstring, invalid-name
"""BollingerBreakout — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class BollingerBreakout(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 40
    process_only_new_candles = True
    use_exit_signal = False
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    bb_period = IntParameter(10, 40, default=20, space="buy", optimize=False, load=True)
    bb_std = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        boll = ta.BBANDS(dataframe, timeperiod=int(self.bb_period.value), nbdevup=float(self.bb_std.value), nbdevdn=float(self.bb_std.value))
        dataframe["bb_upper"] = boll["upperband"]
        dataframe["bb_mid"] = boll["middleband"]
        dataframe["bb_lower"] = boll["lowerband"]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (dataframe["close"] > dataframe["bb_upper"]) & (dataframe["volume"] > 0)
        fresh = dataframe["close"].shift(1) <= dataframe["bb_upper"].shift(1)
        dataframe.loc[cond & fresh, ["enter_long", "enter_tag"]] = (1, "bb_bo")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

