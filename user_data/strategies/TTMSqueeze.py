# pragma pylint: disable=missing-docstring, invalid-name
"""TTMSqueeze — backtest-only candidate. Not for live."""

from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from strategy_common import RiskSizingMixin, atr_pct_series, supertrend


class TTMSqueeze(RiskSizingMixin, IStrategy):
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

    bb_period = IntParameter(10, 30, default=20, space="buy", optimize=False, load=True)
    kc_mult = DecimalParameter(1.0, 2.5, default=1.5, decimals=1, space="buy", optimize=False, load=True)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        n = int(self.bb_period.value)
        boll = ta.BBANDS(dataframe, timeperiod=n, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = boll["upperband"]
        dataframe["bb_lower"] = boll["lowerband"]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=n)
        dataframe["atr_pct"] = atr_pct_series(dataframe, dataframe["atr"])
        mid = ta.EMA(dataframe, timeperiod=n)
        m = float(self.kc_mult.value)
        dataframe["kc_upper"] = mid + m * dataframe["atr"]
        dataframe["kc_lower"] = mid - m * dataframe["atr"]
        dataframe["squeeze_on"] = (
            (dataframe["bb_lower"] > dataframe["kc_lower"]) & (dataframe["bb_upper"] < dataframe["kc_upper"])
        ).astype(int)
        # momentum proxy: close vs EMA
        dataframe["mom"] = dataframe["close"] - mid
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # squeeze release to expansion with positive momentum
        release = (dataframe["squeeze_on"] == 0) & (dataframe["squeeze_on"].shift(1) == 1)
        cond = release & (dataframe["mom"] > 0) & (dataframe["volume"] > 0)
        dataframe.loc[cond, ["enter_long", "enter_tag"]] = (1, "ttm_release")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

