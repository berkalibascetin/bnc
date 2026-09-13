"""S7 — Volatility regime from ATR / realized vol (0..10)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from deterministic_layers.weights import WEIGHTS

S7_MAX = WEIGHTS["s7"]  # 10


def _atr_pct_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-like ATR% using pandas only (no talib dependency in this layer)."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return (atr / close) * 100.0


def s7_volatility_points(
    df: pd.DataFrame,
    *,
    atr_period: int = 14,
    median_lookback: int = 60,
    total_score: float | None = None,
) -> dict[str, float | str | None]:
    """
    Compare current ATR% to its trailing median → expansion / normal / contraction.

    Points are deterministic and mild: neither high nor low vol is auto-good.
    Slight bonus when Score4Window momentum (total_score>0) coexists with
    non-extreme vol (prefer normal/ mild expansion over chaos).
    """
    need = max(atr_period, median_lookback) + 2
    if df is None or len(df) < need:
        return {"s7_score": None, "status": "insufficient_data", "regime": None}

    atr_pct = _atr_pct_series(df, atr_period)
    cur = float(atr_pct.iloc[-1])
    hist = atr_pct.iloc[-(median_lookback + 1) : -1]
    if hist.isna().all() or np.isnan(cur):
        return {"s7_score": None, "status": "insufficient_data", "regime": None}
    med = float(hist.median())
    if med <= 0 or np.isnan(med):
        return {"s7_score": None, "status": "insufficient_data", "regime": None}

    ratio = cur / med
    if ratio >= 1.35:
        regime = "expansion"
        base = 0.45
    elif ratio <= 0.75:
        regime = "contraction"
        base = 0.55
    else:
        regime = "normal"
        base = 0.75

    # Mild interaction with MAIN momentum sign (optional context, not a veto).
    if total_score is not None and not np.isnan(total_score):
        if float(total_score) > 0 and regime in {"normal", "contraction"}:
            base += 0.15
        elif float(total_score) > 0 and regime == "expansion":
            base += 0.05
        elif float(total_score) < 0 and regime == "expansion":
            base -= 0.10

    points = float(np.clip(base, 0.0, 1.0) * S7_MAX)
    return {
        "s7_score": points,
        "status": "ok",
        "regime": regime,
        "atr_pct": cur,
        "atr_pct_median": med,
        "atr_ratio": ratio,
    }
