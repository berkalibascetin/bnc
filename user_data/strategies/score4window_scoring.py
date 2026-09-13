"""
Authoritative Score4Window scoring helpers.

Used by Score4WindowStrategy and the observation-only score_scan layer.
Do not invent a second scoring system — keep this math identical.
"""

from __future__ import annotations

import numpy as np
from pandas import DataFrame, Series

# Defaults must match Score4WindowStrategy class constants.
DEFAULT_WINDOW_1W = 5
DEFAULT_WINDOW_2W = 10
DEFAULT_WINDOW_1M = 21
DEFAULT_WINDOW_2M = 42
DEFAULT_ENTRY_SCORE_THRESHOLD = 2


def window_score(close: Series, lookback: int) -> Series:
    """sign(close - close.shift(lookback)) — no lookahead."""
    historical = close.shift(int(lookback))
    return np.sign(close - historical)


def apply_score4window_scores(
    dataframe: DataFrame,
    *,
    window_1w: int = DEFAULT_WINDOW_1W,
    window_2w: int = DEFAULT_WINDOW_2W,
    window_1m: int = DEFAULT_WINDOW_1M,
    window_2m: int = DEFAULT_WINDOW_2M,
) -> DataFrame:
    """
    Add score_1w/2w/1m/2m and total_score columns.

    total_score is the sum of the four window signs (typically in [-4, +4]).
    """
    out = dataframe
    out["score_1w"] = window_score(out["close"], window_1w)
    out["score_2w"] = window_score(out["close"], window_2w)
    out["score_1m"] = window_score(out["close"], window_1m)
    out["score_2m"] = window_score(out["close"], window_2m)
    out["total_score"] = (
        out["score_1w"] + out["score_2w"] + out["score_1m"] + out["score_2m"]
    )
    return out


# Observation-only labels (scan/report). Strategy entry still uses ENTRY_SCORE_THRESHOLD.
SIGNAL_STRONG_BUY = "güçlü alım"  # score +4
SIGNAL_BUY = "alım"  # score +2 (+3)
SIGNAL_HOLD = "hold"  # score 0 (±1)
SIGNAL_SELL = "sell"  # score -2 (-3)
SIGNAL_STRONG_SELL = "hızlıca sell"  # score -4


def signal_from_score(
    total_score: float | None,
    *,
    entry_threshold: int = DEFAULT_ENTRY_SCORE_THRESHOLD,  # noqa: ARG001 — kept for call-site compat
) -> str:
    """
    Map score → observation signal (does not place orders).

    +4 güçlü alım | +2 alım | 0 hold | -2 sell | -4 hızlıca sell
    Odd scores (±1/±3) snap to the nearest band of the same sign.
    """
    if total_score is None or (isinstance(total_score, float) and np.isnan(total_score)):
        return SIGNAL_HOLD
    score = float(total_score)
    if score >= 4:
        return SIGNAL_STRONG_BUY
    if score >= 2:
        return SIGNAL_BUY
    if score <= -4:
        return SIGNAL_STRONG_SELL
    if score <= -2:
        return SIGNAL_SELL
    return SIGNAL_HOLD


def min_candles_required(window_2m: int = DEFAULT_WINDOW_2M) -> int:
    """Minimum bars needed for a valid score (largest window)."""
    return int(window_2m) + 1
