"""MAIN component: normalize authoritative Score4Window total_score → 0..30."""

from __future__ import annotations

import math

from deterministic_layers.weights import WEIGHTS

MAIN_MAX = WEIGHTS["main"]  # 30


def main_points_from_total_score(total_score: float | None) -> float | None:
    """
    Map Score4Window total_score in [-4, +4] → MAIN points in [0, 30].

    Formula: ((total_score + 4) / 8) * 30

    Does not recompute Score4Window — only normalizes the authoritative value.
    """
    if total_score is None:
        return None
    try:
        score = float(total_score)
    except (TypeError, ValueError):
        return None
    if math.isnan(score):
        return None
    clamped = max(-4.0, min(4.0, score))
    return ((clamped + 4.0) / 8.0) * MAIN_MAX
