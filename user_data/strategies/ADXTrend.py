# pragma pylint: disable=missing-docstring, invalid-name
"""ADXTrend — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class ADXTrend(RiskSizingMixin, IStrategy):
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

    adx_min = IntParameter(15, 40, default=25, space="buy", optimize=False, load=True)
    ema_len = IntParameter(20, 100, default=50, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe)
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=int(self.ema_len.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (
            (dataframe["adx"] > int(self.adx_min.value))
            & (dataframe["plus_di"] > dataframe["minus_di"])
            & (dataframe["close"] > dataframe["ema"])
            & (dataframe["volume"] > 0)
        )
        # enter on fresh ADX/DI confirmation (cross into regime)
        fresh = (dataframe["plus_di"].shift(1) <= dataframe["minus_di"].shift(1)) | (
            dataframe["adx"].shift(1) <= int(self.adx_min.value)
        )
        dataframe.loc[cond & fresh, ["enter_long", "enter_tag"]] = (1, "adx_trend")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

