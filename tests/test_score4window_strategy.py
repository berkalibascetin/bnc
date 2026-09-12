"""
Unit tests for Score4WindowStrategy (SCORE_4WINDOW_V1).

Covers scoring, entry thresholds, short-disabled, warmup, lookahead safety,
and deterministic output — without AI/ML and without inventing a new engine.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from freqtrade.resolvers import StrategyResolver


USER_DATA_DIR = Path(__file__).resolve().parents[1] / "user_data"
STRATEGY_PATH = USER_DATA_DIR / "strategies"


def _base_config() -> dict:
    return {
        "strategy": "Score4WindowStrategy",
        "strategy_path": str(STRATEGY_PATH),
        "user_data_dir": USER_DATA_DIR,
        "timeframe": "1d",
        "stake_currency": "USDT",
        "dry_run": True,
        "exchange": {"name": "binance"},
    }


def _load_strategy():
    return StrategyResolver.load_strategy(_base_config())


def _make_ohlcv(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range(start=start, periods=n, freq="1D", tz="UTC")
    closes_arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes_arr,
            "high": closes_arr * 1.01,
            "low": closes_arr * 0.99,
            "close": closes_arr,
            "volume": np.full(n, 1000.0),
        }
    )


def _run_pipeline(strategy, dataframe: pd.DataFrame) -> pd.DataFrame:
    meta = {"pair": "BTC/USDT"}
    df = strategy.advise_indicators(dataframe.copy(), meta)
    df = strategy.advise_entry(df, meta)
    df = strategy.advise_exit(df, meta)
    return df


@pytest.fixture
def strategy():
    strat = _load_strategy()
    strat.bot_start()
    return strat


class TestScore4WindowScoring:
    def test_score_plus_four(self, strategy):
        """Strictly rising prices => every window +1 => total_score == +4."""
        # 50 candles: each close higher than all lookbacks
        closes = [float(i) for i in range(1, 51)]
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        last = df.iloc[-1]
        assert last["score_1w"] == 1.0
        assert last["score_2w"] == 1.0
        assert last["score_1m"] == 1.0
        assert last["score_2m"] == 1.0
        assert last["total_score"] == 4.0

    def test_score_minus_four(self, strategy):
        """Strictly falling prices => every window -1 => total_score == -4."""
        closes = [float(i) for i in range(50, 0, -1)]
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        last = df.iloc[-1]
        assert last["score_1w"] == -1.0
        assert last["score_2w"] == -1.0
        assert last["score_1m"] == -1.0
        assert last["score_2m"] == -1.0
        assert last["total_score"] == -4.0

    def test_mixed_score(self, strategy):
        """
        Craft closes so windows disagree:
        - 1w (5): up  -> +1
        - 2w (10): down -> -1
        - 1m (21): up  -> +1
        - 2m (42): down -> -1
        total = 0
        """
        n = 50
        closes = [100.0] * n
        # index -1 is current
        closes[-1] = 100.0
        closes[-1 - 5] = 90.0  # 1w lower => +1
        closes[-1 - 10] = 110.0  # 2w higher => -1
        closes[-1 - 21] = 80.0  # 1m lower => +1
        closes[-1 - 42] = 120.0  # 2m higher => -1
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        last = df.iloc[-1]
        assert last["score_1w"] == 1.0
        assert last["score_2w"] == -1.0
        assert last["score_1m"] == 1.0
        assert last["score_2m"] == -1.0
        assert last["total_score"] == 0.0

    def test_equal_price_scores_zero(self, strategy):
        """Identical closes => every window score 0."""
        closes = [42.0] * 50
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        last = df.iloc[-1]
        assert last["score_1w"] == 0.0
        assert last["score_2w"] == 0.0
        assert last["score_1m"] == 0.0
        assert last["score_2m"] == 0.0
        assert last["total_score"] == 0.0


class TestScore4WindowSignals:
    def test_insufficient_history_no_signal(self, strategy):
        """Fewer than 42 candles => total_score NaN on early rows, no entry."""
        closes = [float(i) for i in range(1, 30)]  # 29 < 42
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        # Largest window is 42; with only 29 rows every row lacks full history
        assert df["score_2m"].isna().all()
        assert df["total_score"].isna().all()
        assert (df.get("enter_long", 0).fillna(0) == 0).all()

    def test_score_ge_threshold_enters_long(self, strategy):
        closes = [float(i) for i in range(1, 51)]  # total_score == 4
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        assert df.iloc[-1]["total_score"] >= strategy.entry_score_threshold.value
        assert df.iloc[-1]["enter_long"] == 1

    def test_score_below_threshold_no_entry(self, strategy):
        closes = [42.0] * 50  # total_score == 0 < 2
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        assert df.iloc[-1]["total_score"] < strategy.entry_score_threshold.value
        assert df.iloc[-1].get("enter_long", 0) != 1

    def test_short_disabled(self, strategy):
        assert strategy.can_short is False
        closes = [float(i) for i in range(50, 0, -1)]  # strong downtrend
        df = _run_pipeline(strategy, _make_ohlcv(closes))
        assert "enter_short" not in df.columns or (df["enter_short"].fillna(0) == 0).all()


class TestScore4WindowSafety:
    def test_no_lookahead_shift(self, strategy):
        """Historical closes must come from shift(+N), matching past candles only."""
        closes = [float(i) for i in range(1, 51)]
        raw = _make_ohlcv(closes)
        df = _run_pipeline(strategy, raw)

        idx = 45
        for col, n in (
            ("score_1w", 5),
            ("score_2w", 10),
            ("score_1m", 21),
            ("score_2m", 42),
        ):
            expected = np.sign(raw.loc[idx, "close"] - raw.loc[idx - n, "close"])
            assert df.loc[idx, col] == expected

        # Mutating a future candle must not change past scores
        mutated = raw.copy()
        mutated.loc[49, "close"] = 9999.0
        df2 = _run_pipeline(strategy, mutated)
        past_idx = 45  # fully warmed-up row; candle 49 is in the future relative to it
        for col in ("score_1w", "score_2w", "score_1m", "score_2m", "total_score"):
            assert df.loc[past_idx, col] == df2.loc[past_idx, col]

    def test_deterministic_output(self, strategy):
        closes = [10, 12, 11, 15, 14, 13, 16, 18, 17, 20] * 5
        df1 = _run_pipeline(strategy, _make_ohlcv(closes))
        df2 = _run_pipeline(strategy, _make_ohlcv(closes))
        cols = ["score_1w", "score_2w", "score_1m", "score_2m", "total_score", "enter_long"]
        pd.testing.assert_frame_equal(df1[cols], df2[cols])

    def test_startup_candle_count(self, strategy):
        assert strategy.startup_candle_count >= 42
        assert strategy.startup_candle_count == max(
            strategy.window_1w.value,
            strategy.window_2w.value,
            strategy.window_1m.value,
            strategy.window_2m.value,
        )

    def test_interface_version_and_id(self, strategy):
        assert strategy.INTERFACE_VERSION == 3
        assert strategy.STRATEGY_ID == "SCORE_4WINDOW_V1"
        assert strategy.can_short is False
