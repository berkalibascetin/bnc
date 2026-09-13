"""S1 — Cross-sectional ranking (0..20). No lookahead."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from deterministic_layers.weights import WEIGHTS

S1_MAX = WEIGHTS["s1"]  # 20


def _percentile_ranks(values: pd.Series) -> pd.Series:
    """Average percentile rank in [0, 1]; NaNs stay NaN."""
    return values.rank(method="average", pct=True)


def s1_cross_sectional_points(
    *,
    pairs: Iterable[str],
    total_scores: dict[str, float | None],
    returns_5d: dict[str, float | None],
) -> dict[str, dict[str, float | str | None]]:
    """
    Rank coins vs each other at one frozen timestamp.

    Features (equal weight):
      - Score4Window total_score relative rank
      - 5d close-to-close return relative rank

    Missing feature values → that pair marked insufficient_data (no negative fill).
    """
    pair_list = list(pairs)
    score_s = pd.Series({p: total_scores.get(p) for p in pair_list}, dtype="float64")
    ret_s = pd.Series({p: returns_5d.get(p) for p in pair_list}, dtype="float64")

    score_pct = _percentile_ranks(score_s)
    ret_pct = _percentile_ranks(ret_s)

    out: dict[str, dict[str, float | str | None]] = {}
    for p in pair_list:
        sp = score_pct.get(p)
        rp = ret_pct.get(p)
        if sp is None or rp is None or (isinstance(sp, float) and np.isnan(sp)) or (
            isinstance(rp, float) and np.isnan(rp)
        ):
            out[p] = {
                "s1_score": None,
                "status": "insufficient_data",
                "score_percentile": None if sp is None or (isinstance(sp, float) and np.isnan(sp)) else float(sp),
                "return_percentile": None if rp is None or (isinstance(rp, float) and np.isnan(rp)) else float(rp),
            }
            continue
        # Blend percentiles → 0..20
        blended = 0.5 * float(sp) + 0.5 * float(rp)
        out[p] = {
            "s1_score": float(blended * S1_MAX),
            "status": "ok",
            "score_percentile": float(sp),
            "return_percentile": float(rp),
        }
    return out


def return_nd(close: pd.Series, lookback: int = 5) -> float | None:
    """close[t]/close[t-N] - 1 using only data at/before last bar (no lookahead)."""
    if close is None or len(close) <= lookback:
        return None
    a = float(close.iloc[-1])
    b = float(close.iloc[-(lookback + 1)])
    if b == 0 or np.isnan(a) or np.isnan(b):
        return None
    return (a / b) - 1.0
