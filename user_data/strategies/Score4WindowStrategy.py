# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
"""
Score4WindowStrategy (SCORE_4WINDOW_V1)

Deterministic price-only scoring strategy for Freqtrade.
Compares the current close to closes at four historical windows and sums
per-window scores of +1 / -1 / 0 into a total score in [-4, +4].
"""

from pandas import DataFrame, Series
import numpy as np

from freqtrade.strategy import IStrategy, IntParameter


class Score4WindowStrategy(IStrategy):
    """
    Strategy ID: SCORE_4WINDOW_V1

    For each candle, score four lookback windows (default 5/10/21/42 candles):
      current_close > historical_close  -> +1
      current_close < historical_close  -> -1
      current_close == historical_close ->  0

    Enter long when total_score >= ENTRY_SCORE_THRESHOLD (default 2).
    Shorts are disabled. Exits rely on Freqtrade ROI / stoploss.
    """

    STRATEGY_ID = "SCORE_4WINDOW_V1"

    INTERFACE_VERSION = 3

    can_short: bool = False

    # Defaults mirror trading-session approximations:
    # 1W≈5, 2W≈10, 1M≈21, 2M≈42 daily candles (also valid as generic lookbacks).
    WINDOW_1W = 5
    WINDOW_2W = 10
    WINDOW_1M = 21
    WINDOW_2M = 42
    ENTRY_SCORE_THRESHOLD = 2

    # Hyperopt-ready parameters (optimize=False for V1 — do not auto-tune yet).
    window_1w = IntParameter(
        1, 30, default=WINDOW_1W, space="buy", optimize=False, load=True
    )
    window_2w = IntParameter(
        2, 60, default=WINDOW_2W, space="buy", optimize=False, load=True
    )
    window_1m = IntParameter(
        5, 90, default=WINDOW_1M, space="buy", optimize=False, load=True
    )
    window_2m = IntParameter(
        10, 120, default=WINDOW_2M, space="buy", optimize=False, load=True
    )
    entry_score_threshold = IntParameter(
        1, 4, default=ENTRY_SCORE_THRESHOLD, space="buy", optimize=False, load=True
    )

    # Exit via Freqtrade ROI / stoploss — no custom exit invention.
    minimal_roi = {
        "0": 0.10,
    }
    stoploss = -0.10
    trailing_stop = False

    timeframe = "1d"

    process_only_new_candles = True

    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Minimum history = largest default lookback (2M). bot_start keeps this in sync.
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
        """Keep startup_candle_count aligned with the largest configured window."""
        self.startup_candle_count = max(
            int(self.window_1w.value),
            int(self.window_2w.value),
            int(self.window_1m.value),
            int(self.window_2m.value),
        )

    @staticmethod
    def _window_score(dataframe: DataFrame, lookback: int) -> Series:
        """
        Compare current close to close `lookback` candles ago.

        Uses shift(+N) only — never negative shifts — to avoid lookahead bias.
        """
        historical = dataframe["close"].shift(lookback)
        # np.sign: +1 / -1 / 0; NaN where history is insufficient
        return np.sign(dataframe["close"] - historical)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        threshold = int(self.entry_score_threshold.value)

        dataframe.loc[
            (
                (dataframe["total_score"] >= threshold)
                & (dataframe["total_score"].notna())
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No custom exit signals — ROI / stoploss handle exits.
        dataframe.loc[:, "exit_long"] = 0
        return dataframe
