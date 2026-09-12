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


def signal_from_score(
    total_score: float | None,
    *,
    entry_threshold: int = DEFAULT_ENTRY_SCORE_THRESHOLD,
) -> str:
    """Map score to observation signal labels (does not place orders)."""
    if total_score is None or (isinstance(total_score, float) and np.isnan(total_score)):
        return "HOLD"
    score = float(total_score)
    if score >= float(entry_threshold):
        return "BUY"
    if score > 0:
        return "WATCH"
    return "HOLD"


def min_candles_required(window_2m: int = DEFAULT_WINDOW_2M) -> int:
    """Minimum bars needed for a valid score (largest window)."""
    return int(window_2m) + 1
