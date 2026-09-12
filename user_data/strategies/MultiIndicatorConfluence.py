# pragma pylint: disable=missing-docstring, invalid-name
"""MultiIndicatorConfluence — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class MultiIndicatorConfluence(RiskSizingMixin, IStrategy):
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

    min_score = IntParameter(2, 4, default=3, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        macd = ta.MACD(dataframe)
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        dataframe["vol_ma"] = dataframe["volume"].rolling(20).mean()
        dataframe["c_ema"] = (dataframe["ema20"] > dataframe["ema50"]).astype(int)
        dataframe["c_rsi"] = (dataframe["rsi"] > 50).astype(int)
        dataframe["c_macd"] = (dataframe["macdhist"] > 0).astype(int)
        dataframe["c_vol"] = (dataframe["volume"] > dataframe["vol_ma"]).astype(int)
        dataframe["conf_score"] = dataframe["c_ema"] + dataframe["c_rsi"] + dataframe["c_macd"] + dataframe["c_vol"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        thr = int(self.min_score.value)
        cond = (dataframe["conf_score"] >= thr) & (dataframe["volume"] > 0)
        fresh = dataframe["conf_score"].shift(1) < thr
        dataframe.loc[cond & fresh, ["enter_long", "enter_tag"]] = (1, "confluence")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

