"""
Pair-local deterministic feature helpers for FreqAI Phase A.

Reuses existing MAIN / S3 / S4 / S7 math without rewriting scoring.
S1 / S2 / rank / top15 membership are intentionally excluded (Phase B).

All series are causal: bar i uses only data available at or before bar i.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from deterministic_layers.main import MAIN_MAX, main_points_from_total_score
from deterministic_layers.s3_lead_lag import s3_lead_lag_points
from deterministic_layers.s4_onchain import S4_NEUTRAL
from deterministic_layers.s7_volatility import s7_volatility_points
from deterministic_layers.weights import WEIGHTS

# Phase A placeholders so final_score stays on the 0–100 scale without
# cross-sectional S1/S2 (those arrive in Phase B).
S1_NEUTRAL = WEIGHTS["s1"] / 2.0
S2_NEUTRAL = WEIGHTS["s2"] / 2.0


def main_points_series(total_score: pd.Series) -> pd.Series:
    """Vectorized MAIN points from authoritative total_score (same formula)."""
    out = total_score.astype(float).map(main_points_from_total_score)
    return out.astype(float)


def s4_points_series(index: pd.Index) -> pd.Series:
    """S4 unavailable → neutral contribution (no fake on-chain data)."""
    return pd.Series(float(S4_NEUTRAL), index=index, dtype=float)


def s7_points_series(dataframe: pd.DataFrame, total_score: pd.Series) -> pd.Series:
    """Causal S7 by evaluating existing helper on prefixes (no lookahead)."""
    values: list[float] = []
    for i in range(len(dataframe)):
        window = dataframe.iloc[: i + 1]
        ts = total_score.iloc[i]
        ts_f = float(ts) if ts is not None and not pd.isna(ts) else None
        res = s7_volatility_points(window, total_score=ts_f)
        score = res.get("s7_score")
        values.append(float(score) if score is not None else float("nan"))
    return pd.Series(values, index=dataframe.index, dtype=float)


def s3_points_series(
    pair_close: pd.Series,
    leader_closes: dict[str, pd.Series] | None,
    *,
    lookback: int = 30,
    min_bars: int = 40,
) -> pd.Series:
    """
    Causal S3 using existing lead/lag helper on prefixes.

    If leaders are missing, returns neutral midpoints (S3_MAX/2) so the model
    still receives a stable feature without inventing correlations.
    """
    s3_neutral = WEIGHTS["s3"] / 2.0
    if not leader_closes:
        return pd.Series(s3_neutral, index=pair_close.index, dtype=float)

    # Align leaders onto pair index (asof / reindex forward-fill of past only).
    aligned: dict[str, pd.Series] = {}
    for name, series in leader_closes.items():
        if series is None or series.empty:
            continue
        s = series.copy()
        if not isinstance(s.index, type(pair_close.index)):
            # Fall back to positional align when indexes differ.
            continue
        aligned[name] = s.reindex(pair_close.index).ffill()

    if not aligned:
        # Positional fallback: truncate/pad to pair length.
        for name, series in leader_closes.items():
            if series is None or series.empty:
                continue
            s = series.reset_index(drop=True)
            if len(s) < len(pair_close):
                pad = pd.Series([np.nan] * (len(pair_close) - len(s)))
                s = pd.concat([pad, s], ignore_index=True)
            aligned[name] = pd.Series(s.iloc[-len(pair_close) :].to_numpy(), index=pair_close.index)

    if not aligned:
        return pd.Series(s3_neutral, index=pair_close.index, dtype=float)

    values: list[float] = []
    close = pair_close.astype(float)
    for i in range(len(close)):
        if i + 1 < min_bars:
            values.append(float("nan"))
            continue
        leaders_i = {k: v.iloc[: i + 1] for k, v in aligned.items()}
        res = s3_lead_lag_points(
            pair_close=close.iloc[: i + 1],
            leader_closes=leaders_i,
            lookback=lookback,
        )
        score = res.get("s3_score")
        values.append(float(score) if score is not None else s3_neutral)
    return pd.Series(values, index=pair_close.index, dtype=float)


def final_score_phase_a(
    main: pd.Series,
    s3: pd.Series,
    s4: pd.Series,
    s7: pd.Series,
) -> pd.Series:
    """
    Phase A final_score = MAIN + S3 + S4 + S7 + neutral(S1) + neutral(S2).

    Does not recompute Score4Window. S1/S2 stay neutral until Phase B.
    """
    return (
        main.fillna(0.0)
        + float(S1_NEUTRAL)
        + float(S2_NEUTRAL)
        + s3.fillna(float(WEIGHTS["s3"] / 2.0))
        + s4.fillna(float(S4_NEUTRAL))
        + s7.fillna(float(WEIGHTS["s7"] / 2.0))
    ).clip(lower=0.0, upper=100.0)


def attach_phase_a_deterministic_columns(
    dataframe: pd.DataFrame,
    *,
    total_score_col: str = "total_score",
    leader_closes: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Add non-% helper columns used before FreqAI %-prefixing."""
    if total_score_col not in dataframe.columns:
        raise KeyError(f"missing {total_score_col}")
    total = dataframe[total_score_col]
    dataframe["dl_main"] = main_points_series(total)
    dataframe["dl_s3"] = s3_points_series(dataframe["close"], leader_closes)
    dataframe["dl_s4"] = s4_points_series(dataframe.index)
    dataframe["dl_s7"] = s7_points_series(dataframe, total)
    dataframe["dl_final_score"] = final_score_phase_a(
        dataframe["dl_main"],
        dataframe["dl_s3"],
        dataframe["dl_s4"],
        dataframe["dl_s7"],
    )
    return dataframe


__all__ = [
    "MAIN_MAX",
    "S1_NEUTRAL",
    "S2_NEUTRAL",
    "attach_phase_a_deterministic_columns",
    "final_score_phase_a",
    "main_points_series",
    "s3_points_series",
    "s4_points_series",
    "s7_points_series",
]
