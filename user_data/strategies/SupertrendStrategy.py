# pragma pylint: disable=missing-docstring, invalid-name
"""SupertrendStrategy — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class SupertrendStrategy(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 40
    process_only_new_candles = True
    use_exit_signal = True
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    st_period = IntParameter(7, 21, default=10, space="buy", optimize=False, load=True)
    st_mult = DecimalParameter(1.0, 5.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=int(self.st_period.value))
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        st = supertrend(dataframe, period=int(self.st_period.value), multiplier=float(self.st_mult.value))
        dataframe["st_dir"] = st["st_dir"]
        dataframe["st_line"] = st["st_line"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (dataframe["st_dir"] == 1) & (dataframe["st_dir"].shift(1) == -1) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "st_flip")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (dataframe["st_dir"] == -1) & (dataframe["st_dir"].shift(1) == 1)
        dataframe.loc[cond, ["exit_long", "exit_tag"]] = (1, "st_bear")
        return dataframe

