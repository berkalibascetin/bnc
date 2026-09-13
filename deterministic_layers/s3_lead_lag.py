"""S3 — Cross-crypto lead/lag vs BTC/ETH/SOL (0..15). Lagged only — no same-bar leakage."""

from __future__ import annotations

import numpy as np
import pandas as pd

from deterministic_layers.weights import WEIGHTS

S3_MAX = WEIGHTS["s3"]  # 15
DEFAULT_LEADERS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def _log_returns(close: pd.Series) -> pd.Series:
    return np.log(close.astype(float)).diff()


def s3_lead_lag_points(
    *,
    pair_close: pd.Series,
    leader_closes: dict[str, pd.Series],
    lookback: int = 30,
) -> dict[str, float | str | None]:
    """
    Score alignment of pair returns with *lagged* leader returns.

    For each leader L: corr(pair_ret[t], L_ret[t-1]) over trailing `lookback`.
    Also reward sign agreement between pair_ret[t] and mean(L_ret[t-1]).

    Uses only past/current bars present in the provided series (caller must
    truncate to as-of). Leader returns are shifted by +1 bar → no same-candle leak.
    """
    if pair_close is None or len(pair_close) < lookback + 5:
        return {"s3_score": None, "status": "insufficient_data", "detail": "pair_short"}

    pair_ret = _log_returns(pair_close)
    corrs: list[float] = []
    lagged_leader_stack: list[pd.Series] = []

    for close in leader_closes.values():
        if close is None or len(close) < lookback + 5:
            continue
        # Align on intersection of timestamps if both have a DatetimeIndex / RangeIndex
        leader_ret = _log_returns(close).shift(1)  # lag: leader at t-1
        aligned = pd.concat([pair_ret, leader_ret], axis=1, join="inner").dropna()
        if len(aligned) < lookback:
            continue
        window = aligned.iloc[-lookback:]
        c = float(window.iloc[:, 0].corr(window.iloc[:, 1]))
        if np.isnan(c):
            continue
        corrs.append(c)
        lagged_leader_stack.append(window.iloc[:, 1])

    if not corrs:
        return {"s3_score": None, "status": "insufficient_data", "detail": "no_leaders"}

    mean_corr = float(np.mean(corrs))
    # Map corr from [-1,1] → [0,1]
    corr_component = (mean_corr + 1.0) / 2.0

    # Direction agreement on last bar
    last_pair = float(pair_ret.iloc[-1]) if not np.isnan(pair_ret.iloc[-1]) else 0.0
    last_leaders = [float(s.iloc[-1]) for s in lagged_leader_stack if len(s)]
    if last_leaders:
        mean_leader = float(np.mean(last_leaders))
        agree = 1.0 if (last_pair == 0 and mean_leader == 0) or (last_pair * mean_leader > 0) else 0.0
        if last_pair == 0 or mean_leader == 0:
            agree = 0.5
    else:
        agree = 0.5

    blended = 0.7 * corr_component + 0.3 * agree
    return {
        "s3_score": float(np.clip(blended, 0.0, 1.0) * S3_MAX),
        "status": "ok",
        "mean_lagged_corr": mean_corr,
        "direction_agree": agree,
    }
