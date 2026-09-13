"""S2 — Market regime from BTC proxy + universe breadth (0..15). Not a hard filter."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from deterministic_layers.weights import WEIGHTS

S2_MAX = WEIGHTS["s2"]  # 15


@dataclass(frozen=True)
class RegimeConfig:
    """Configurable, deterministic regime thresholds (not claimed as ground truth)."""

    btc_lookback: int = 21
    bull_btc_return: float = 0.05
    bear_btc_return: float = -0.05
    bull_breadth: float = 0.55
    bear_breadth: float = 0.45


@dataclass(frozen=True)
class RegimeResult:
    regime: str  # BULL | NEUTRAL | BEAR | insufficient_data
    s2_score: float | None
    btc_return: float | None
    breadth: float | None


def _btc_return(btc_close: pd.Series, lookback: int) -> float | None:
    if btc_close is None or len(btc_close) <= lookback:
        return None
    a = float(btc_close.iloc[-1])
    b = float(btc_close.iloc[-(lookback + 1)])
    if b == 0 or np.isnan(a) or np.isnan(b):
        return None
    return (a / b) - 1.0


def universe_breadth(returns_5d: dict[str, float | None]) -> float | None:
    vals = [v for v in returns_5d.values() if v is not None and not np.isnan(v)]
    if not vals:
        return None
    pos = sum(1 for v in vals if v > 0)
    return pos / len(vals)


def classify_regime(
    *,
    btc_close: pd.Series | None,
    returns_5d: dict[str, float | None],
    config: RegimeConfig | None = None,
) -> RegimeResult:
    cfg = config or RegimeConfig()
    if btc_close is None or btc_close.empty:
        return RegimeResult("insufficient_data", None, None, None)

    btc_ret = _btc_return(btc_close, cfg.btc_lookback)
    breadth = universe_breadth(returns_5d)
    if btc_ret is None or breadth is None:
        return RegimeResult("insufficient_data", None, btc_ret, breadth)

    # Soft continuous score in [0, 1] then scale to S2_MAX.
    # BTC return mapped roughly from bear..bull thresholds → 0..1
    span = max(cfg.bull_btc_return - cfg.bear_btc_return, 1e-9)
    btc_component = (btc_ret - cfg.bear_btc_return) / span
    btc_component = float(np.clip(btc_component, 0.0, 1.0))
    breadth_component = float(np.clip(breadth, 0.0, 1.0))
    blended = 0.6 * btc_component + 0.4 * breadth_component
    points = blended * S2_MAX

    if btc_ret >= cfg.bull_btc_return and breadth >= cfg.bull_breadth:
        regime = "BULL"
    elif btc_ret <= cfg.bear_btc_return and breadth <= cfg.bear_breadth:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"

    return RegimeResult(regime, float(points), float(btc_ret), float(breadth))
