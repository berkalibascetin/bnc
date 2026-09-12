# pragma pylint: disable=missing-docstring, invalid-name
"""ZScoreMeanReversion — backtest-only candidate. Not for live."""

from pandas import DataFrame
import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class ZScoreMeanReversion(RiskSizingMixin, IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 60
    process_only_new_candles = True
    use_exit_signal = True
    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    risk_pct = DecimalParameter(0.5, 10.0, default=3.0, decimals=1, space="buy", optimize=False, load=True)
    max_position_pct = DecimalParameter(1.0, 100.0, default=25.0, decimals=1, space="buy", optimize=False, load=True)
    min_atr_pct = DecimalParameter(0.05, 1.0, default=0.1, decimals=2, space="buy", optimize=False, load=True)

    z_len = IntParameter(20, 100, default=40, space="buy", optimize=False, load=True)
    z_entry = DecimalParameter(1.0, 3.0, default=2.0, decimals=1, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = int(self.z_len.value)
        ma = dataframe["close"].rolling(n).mean()
        sd = dataframe["close"].rolling(n).std()
        dataframe["zscore"] = (dataframe["close"] - ma) / sd.replace(0, np.nan)
        dataframe["ma"] = ma
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        z = float(self.z_entry.value)
        cond = (dataframe["zscore"] < -z) & (dataframe["zscore"].shift(1) >= -z) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "z_mr")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = dataframe["zscore"] >= 0
        dataframe.loc[cond, ["exit_long", "exit_tag"]] = (1, "z_mean")
        return dataframe

