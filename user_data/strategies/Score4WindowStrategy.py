# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
"""
Score4WindowStrategy (SCORE_4WINDOW_V1)

Core: deterministic 4-window price score (unchanged).
Optional confirmation filters are OFF by default so baseline behavior is preserved.
Enable exactly one filter at a time via Score4WindowStrategy.json for A/B tests.
"""

from pandas import DataFrame, Series
import numpy as np
import talib.abstract as ta

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter


class Score4WindowStrategy(IStrategy):
    """
    Strategy ID: SCORE_4WINDOW_V1

    Core entry (always required):
      total_score >= entry_score_threshold (default 2)

    Optional filters (all default OFF — baseline identical to V1):
      volume / momentum / breakout / retest / volatility / fibonacci
    """

    STRATEGY_ID = "SCORE_4WINDOW_V1"

    INTERFACE_VERSION = 3

    can_short: bool = False

    WINDOW_1W = 5
    WINDOW_2W = 10
    WINDOW_1M = 21
    WINDOW_2M = 42
    ENTRY_SCORE_THRESHOLD = 2

    window_1w = IntParameter(1, 30, default=WINDOW_1W, space="buy", optimize=False, load=True)
    window_2w = IntParameter(2, 60, default=WINDOW_2W, space="buy", optimize=False, load=True)
    window_1m = IntParameter(5, 90, default=WINDOW_1M, space="buy", optimize=False, load=True)
    window_2m = IntParameter(10, 120, default=WINDOW_2M, space="buy", optimize=False, load=True)
    entry_score_threshold = IntParameter(
        1, 4, default=ENTRY_SCORE_THRESHOLD, space="buy", optimize=False, load=True
    )

    # --- Optional filters: 0=off (baseline), 1=on. Enable one at a time for A/B. ---
    enable_volume_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)
    enable_momentum_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)
    enable_breakout_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)
    enable_retest_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)
    enable_volatility_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)
    enable_fibonacci_filter = IntParameter(0, 1, default=0, space="buy", optimize=False, load=True)

    # Filter parameters (only applied when the matching enable_*=1)
    volume_ma_period = IntParameter(10, 40, default=20, space="buy", optimize=False, load=True)
    volume_mult = DecimalParameter(
        1.0, 3.0, default=1.5, decimals=1, space="buy", optimize=False, load=True
    )
    rsi_period = IntParameter(7, 21, default=14, space="buy", optimize=False, load=True)
    rsi_min = IntParameter(45, 60, default=50, space="buy", optimize=False, load=True)
    breakout_lookback = IntParameter(10, 40, default=20, space="buy", optimize=False, load=True)
    retest_lookback = IntParameter(10, 40, default=20, space="buy", optimize=False, load=True)
    retest_tol_pct = DecimalParameter(
        0.2, 3.0, default=1.0, decimals=1, space="buy", optimize=False, load=True
    )
    atr_period = IntParameter(7, 21, default=14, space="buy", optimize=False, load=True)
    atr_min_pct = DecimalParameter(
        0.3, 5.0, default=1.0, decimals=1, space="buy", optimize=False, load=True
    )
    fib_lookback = IntParameter(20, 100, default=55, space="buy", optimize=False, load=True)

    minimal_roi = {"0": 0.10}
    stoploss = -0.10
    trailing_stop = False

    timeframe = "1d"
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = WINDOW_2M

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    plot_config = {
        "main_plot": {},
        "subplots": {
            "score": {
                "total_score": {"color": "blue"},
                "score_1w": {"color": "green"},
                "score_2w": {"color": "orange"},
                "score_1m": {"color": "purple"},
                "score_2m": {"color": "red"},
            },
        },
    }

    def bot_start(self, **kwargs) -> None:
        """Align startup history with score windows and any enabled filter lookbacks."""
        needed = [
            int(self.window_1w.value),
            int(self.window_2w.value),
            int(self.window_1m.value),
            int(self.window_2m.value),
        ]
        if int(self.enable_volume_filter.value) == 1:
            needed.append(int(self.volume_ma_period.value))
        if int(self.enable_momentum_filter.value) == 1:
            needed.append(int(self.rsi_period.value) + 1)
        if int(self.enable_breakout_filter.value) == 1:
            needed.append(int(self.breakout_lookback.value) + 1)
        if int(self.enable_retest_filter.value) == 1:
            needed.append(int(self.retest_lookback.value) + 1)
        if int(self.enable_volatility_filter.value) == 1:
            needed.append(int(self.atr_period.value) + 1)
        if int(self.enable_fibonacci_filter.value) == 1:
            needed.append(int(self.fib_lookback.value) + 1)
        self.startup_candle_count = max(needed)

    @staticmethod
    def _window_score(dataframe: DataFrame, lookback: int) -> Series:
        """Compare current close to close `lookback` ago using shift(+N) only."""
        historical = dataframe["close"].shift(lookback)
        return np.sign(dataframe["close"] - historical)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- Core 4-window score (unchanged) ---
        w1 = int(self.window_1w.value)
        w2 = int(self.window_2w.value)
        w3 = int(self.window_1m.value)
        w4 = int(self.window_2m.value)

        dataframe["score_1w"] = self._window_score(dataframe, w1)
        dataframe["score_2w"] = self._window_score(dataframe, w2)
        dataframe["score_1m"] = self._window_score(dataframe, w3)
        dataframe["score_2m"] = self._window_score(dataframe, w4)
        dataframe["total_score"] = (
            dataframe["score_1w"]
            + dataframe["score_2w"]
            + dataframe["score_1m"]
            + dataframe["score_2m"]
        )

        # --- Optional filter columns (computed for analysis; applied only if enabled) ---
        # All use past data only (shift(+N) / rolling on shifted series).

        vol_n = int(self.volume_ma_period.value)
        dataframe["volume_ma"] = dataframe["volume"].rolling(vol_n).mean()
        dataframe["filt_volume"] = (
            dataframe["volume"] > (dataframe["volume_ma"] * float(self.volume_mult.value))
        ).astype(int)

        rsi_n = int(self.rsi_period.value)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=rsi_n)
        dataframe["filt_momentum"] = (dataframe["rsi"] > int(self.rsi_min.value)).astype(int)

        br_n = int(self.breakout_lookback.value)
        # Prior N highs excluding current candle — no lookahead.
        dataframe["prior_high"] = dataframe["high"].shift(1).rolling(br_n).max()
        dataframe["filt_breakout"] = (dataframe["close"] > dataframe["prior_high"]).astype(int)

        rt_n = int(self.retest_lookback.value)
        tol = float(self.retest_tol_pct.value) / 100.0
        prior_high_rt = dataframe["high"].shift(1).rolling(rt_n).max()
        # Retest: touched/near prior breakout level this candle, closed back above it.
        near_level = dataframe["low"] <= (prior_high_rt * (1.0 + tol))
        reclaimed = dataframe["close"] > prior_high_rt
        dataframe["filt_retest"] = (near_level & reclaimed).astype(int)

        atr_n = int(self.atr_period.value)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_n)
        dataframe["atr_pct"] = (dataframe["atr"] / dataframe["close"]) * 100.0
        dataframe["filt_volatility"] = (
            dataframe["atr_pct"] >= float(self.atr_min_pct.value)
        ).astype(int)

        fib_n = int(self.fib_lookback.value)
        swing_high = dataframe["high"].shift(1).rolling(fib_n).max()
        swing_low = dataframe["low"].shift(1).rolling(fib_n).min()
        fib_range = (swing_high - swing_low).replace(0, np.nan)
        # Bullish confirmation: price in upper half of recent range (>= 0.5 fib).
        dataframe["fib_50"] = swing_low + 0.5 * fib_range
        dataframe["filt_fibonacci"] = (dataframe["close"] >= dataframe["fib_50"]).astype(int)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        threshold = int(self.entry_score_threshold.value)

        score_cond = (
            (dataframe["total_score"] >= threshold)
            & (dataframe["total_score"].notna())
            & (dataframe["volume"] > 0)
        )

        entry_cond = score_cond
        active_filters: list[str] = []

        if int(self.enable_volume_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_volume"] == 1)
            active_filters.append("vol")
        if int(self.enable_momentum_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_momentum"] == 1)
            active_filters.append("mom")
        if int(self.enable_breakout_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_breakout"] == 1)
            active_filters.append("bo")
        if int(self.enable_retest_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_retest"] == 1)
            active_filters.append("rt")
        if int(self.enable_volatility_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_volatility"] == 1)
            active_filters.append("atr")
        if int(self.enable_fibonacci_filter.value) == 1:
            entry_cond = entry_cond & (dataframe["filt_fibonacci"] == 1)
            active_filters.append("fib")

        dataframe.loc[entry_cond, "enter_long"] = 1
        tag_base = "score_" + dataframe["total_score"].fillna(0).astype(int).astype(str)
        if active_filters:
            tag_base = tag_base + "|" + "|".join(active_filters)
        dataframe.loc[entry_cond, "enter_tag"] = tag_base[entry_cond]

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe
