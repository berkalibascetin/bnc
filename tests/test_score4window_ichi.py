"""Tests for Score4Window + Ichimoku hybrid helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
from ichi_confirm import ichimoku_leading  # noqa: E402


def _ohlcv(n: int = 150, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = [100.0]
    for _ in range(n - 1):
        close.append(close[-1] * (1.0 + 0.01 + rng.normal(0, 0.005)))
    close_a = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
            "open": close_a * 0.999,
            "high": close_a * 1.01,
            "low": close_a * 0.99,
            "close": close_a,
            "volume": np.full(n, 1_000.0),
        }
    )


def test_ichimoku_leading_is_causal_and_finite():
    df = _ohlcv()
    ichi = ichimoku_leading(df, conversion_line_period=9, base_line_periods=26, laggin_span=52)
    assert len(ichi["leading_senkou_span_a"]) == len(df)
    assert len(ichi["leading_senkou_span_b"]) == len(df)
    assert np.isfinite(ichi["leading_senkou_span_a"].iloc[-1])
    assert np.isfinite(ichi["kijun_sen"].iloc[-1])


def test_config_sw4_ichi_dryrun_safety():
    cfg = json.loads(Path("user_data/config_sw4_ichi_dryrun.json").read_text())
    assert cfg.get("dry_run") is True
    assert cfg.get("strategy") == "Score4WindowIchiStrategy"
    assert cfg.get("max_open_trades") == 1_000_000
    assert cfg.get("timeframe") == "1d"
    assert (cfg.get("exit_pricing") or {}).get("price_side") == "other"
    assert (cfg.get("entry_pricing") or {}).get("price_side") == "other"
    assert not (cfg.get("exchange") or {}).get("key")
    assert not (cfg.get("exchange") or {}).get("secret")
    assert len((cfg.get("exchange") or {}).get("pair_whitelist") or []) >= 50


def test_strategy_file_keeps_sw4_as_primary():
    text = Path("user_data/strategies/Score4WindowIchiStrategy.py").read_text()
    assert "SCORE_4WINDOW_ICHI_V1" in text
    assert "Score4WindowStrategy" in text
    assert "total_score" in text
    assert "Heikin-Ashi" in text  # documented avoidance
    assert "chikou" in text.lower()  # documented avoidance
