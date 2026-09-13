"""Combine MAIN+S1+S2+S3+S4+S7 into final_score (0..100). Observation only."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from deterministic_layers.main import main_points_from_total_score
from deterministic_layers.s1_cross_section import return_nd, s1_cross_sectional_points
from deterministic_layers.s2_regime import RegimeConfig, classify_regime
from deterministic_layers.s3_lead_lag import s3_lead_lag_points
from deterministic_layers.s4_onchain import (
    OnchainProvider,
    s4_contribution_for_final,
    s4_points,
)
from deterministic_layers.s7_volatility import s7_volatility_points
from deterministic_layers.weights import WEIGHTS

# Leader pair names as used in Freqtrade configs (Binance spot).
DEFAULT_LEADERS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


@dataclass
class ComponentScores:
    pair: str
    status: str  # ok | insufficient_data | error
    rank: int | None = None
    final_score: float | None = None
    main_score: float | None = None
    s1_score: float | None = None
    s2_score: float | None = None
    s3_score: float | None = None
    s4_score: float | None = None
    s7_score: float | None = None
    total_score: float | None = None  # authoritative Score4Window [-4,+4]
    regime: str | None = None
    s4_status: str | None = None
    candle_timestamp: str | None = None
    reason: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _last_total_score(df: pd.DataFrame) -> float | None:
    if df is None or df.empty or "total_score" not in df.columns:
        return None
    v = df["total_score"].iloc[-1]
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v)


def _candle_ts(df: pd.DataFrame) -> str | None:
    if df is None or df.empty:
        return None
    if "date" in df.columns:
        val = df["date"].iloc[-1]
        return val.isoformat() if hasattr(val, "isoformat") else str(val)
    return None


def _truncate_as_of(df: pd.DataFrame, as_of: pd.Timestamp | None) -> pd.DataFrame:
    if as_of is None or df is None or df.empty or "date" not in df.columns:
        return df
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        # Compare tz-naive to tz-aware carefully
        dates = pd.to_datetime(df["date"])
        if getattr(dates.dt, "tz", None) is not None:
            as_of = as_of.tz_localize("UTC")
    mask = pd.to_datetime(df["date"]) <= as_of
    return df.loc[mask].copy()


def score_universe(
    scored_frames: dict[str, pd.DataFrame],
    *,
    as_of: pd.Timestamp | None = None,
    leaders: tuple[str, ...] = DEFAULT_LEADERS,
    onchain_provider: OnchainProvider | None = None,
    regime_config: RegimeConfig | None = None,
) -> list[ComponentScores]:
    """
    Score all pairs with deterministic layers.

    `scored_frames` values must already include Score4Window columns from
    `apply_score4window_scores` (authoritative). This function does not
    reimplement Score4Window math.
    """
    frames: dict[str, pd.DataFrame] = {}
    for pair, df in scored_frames.items():
        if df is None or df.empty:
            frames[pair] = df
            continue
        frames[pair] = _truncate_as_of(df, as_of)

    # Per-pair MAIN inputs
    total_scores: dict[str, float | None] = {}
    returns_5d: dict[str, float | None] = {}
    for pair, df in frames.items():
        if df is None or df.empty:
            total_scores[pair] = None
            returns_5d[pair] = None
            continue
        total_scores[pair] = _last_total_score(df)
        returns_5d[pair] = return_nd(df["close"], 5) if "close" in df.columns else None

    s1_map = s1_cross_sectional_points(
        pairs=frames.keys(),
        total_scores=total_scores,
        returns_5d=returns_5d,
    )

    btc_df = frames.get("BTC/USDT")
    btc_close = btc_df["close"] if btc_df is not None and not btc_df.empty else None
    regime = classify_regime(
        btc_close=btc_close,
        returns_5d=returns_5d,
        config=regime_config,
    )
    s2_points = regime.s2_score

    leader_closes: dict[str, pd.Series] = {}
    for lp in leaders:
        ldf = frames.get(lp)
        if ldf is not None and not ldf.empty and "close" in ldf.columns:
            leader_closes[lp] = ldf["close"]

    results: list[ComponentScores] = []
    for pair, df in frames.items():
        try:
            if df is None or df.empty:
                results.append(
                    ComponentScores(
                        pair=pair,
                        status="insufficient_data",
                        reason="no_ohlcv",
                        s4_status="unavailable",
                    )
                )
                continue

            total = total_scores.get(pair)
            main = main_points_from_total_score(total)
            if main is None:
                results.append(
                    ComponentScores(
                        pair=pair,
                        status="insufficient_data",
                        reason="total_score_missing",
                        candle_timestamp=_candle_ts(df),
                        s4_status="unavailable",
                    )
                )
                continue

            s1_info = s1_map.get(pair) or {}
            s1 = s1_info.get("s1_score")
            if s1 is None:
                results.append(
                    ComponentScores(
                        pair=pair,
                        status="insufficient_data",
                        reason="s1_insufficient_data",
                        main_score=main,
                        total_score=total,
                        candle_timestamp=_candle_ts(df),
                        s4_status="unavailable",
                        regime=regime.regime,
                        s2_score=s2_points,
                    )
                )
                continue

            if s2_points is None:
                results.append(
                    ComponentScores(
                        pair=pair,
                        status="insufficient_data",
                        reason="s2_insufficient_data",
                        main_score=main,
                        s1_score=float(s1),
                        total_score=total,
                        candle_timestamp=_candle_ts(df),
                        s4_status="unavailable",
                        regime=regime.regime,
                    )
                )
                continue

            s3_info = s3_lead_lag_points(
                pair_close=df["close"],
                leader_closes=leader_closes,
            )
            s3 = s3_info.get("s3_score")
            if s3 is None:
                results.append(
                    ComponentScores(
                        pair=pair,
                        status="insufficient_data",
                        reason="s3_insufficient_data",
                        main_score=main,
                        s1_score=float(s1),
                        s2_score=float(s2_points),
                        total_score=total,
                        candle_timestamp=_candle_ts(df),
                        s4_status="unavailable",
                        regime=regime.regime,
                    )
                )
                continue

            s4_res = s4_points(pair, onchain_provider)
            s4_contrib = s4_contribution_for_final(s4_res)
            # Report neutral midpoint when unavailable (transparent).
            s4_reported = (
                None if s4_res.status == "unavailable" else s4_res.s4_score
            )

            s7_info = s7_volatility_points(df, total_score=total)
            s7 = s7_info.get("s7_score")
            # Like S4: missing vol history → neutral midpoint (not a penalty).
            from deterministic_layers.weights import WEIGHTS as _W

            s7_neutral = float(_W["s7"]) / 2.0
            s7_contrib = float(s7) if s7 is not None else s7_neutral
            s7_reported = float(s7) if s7 is not None else s7_neutral

            final = (
                float(main)
                + float(s1)
                + float(s2_points)
                + float(s3)
                + float(s4_contrib)
                + float(s7_contrib)
            )
            # Bound to [0, 100]
            final = max(0.0, min(100.0, final))

            results.append(
                ComponentScores(
                    pair=pair,
                    status="ok",
                    final_score=final,
                    main_score=float(main),
                    s1_score=float(s1),
                    s2_score=float(s2_points),
                    s3_score=float(s3),
                    s4_score=s4_reported if s4_reported is not None else s4_contrib,
                    s7_score=float(s7_reported),
                    total_score=total,
                    regime=regime.regime,
                    s4_status=s4_res.status,
                    candle_timestamp=_candle_ts(df),
                    extras={
                        "weights": dict(WEIGHTS),
                        "s4_contribution": s4_contrib,
                        "s7_contribution": s7_contrib,
                        "s7_status": s7_info.get("status"),
                        "s1": {k: v for k, v in s1_info.items() if k != "s1_score"},
                        "s3": {k: v for k, v in s3_info.items() if k != "s3_score"},
                        "s7": {k: v for k, v in s7_info.items() if k != "s7_score"},
                        "regime_btc_return": regime.btc_return,
                        "regime_breadth": regime.breadth,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                ComponentScores(
                    pair=pair,
                    status="error",
                    reason=str(exc),
                )
            )

    ok = [r for r in results if r.status == "ok" and r.final_score is not None]
    other = [r for r in results if r not in ok]
    ok.sort(key=lambda r: (-(r.final_score or -1.0), r.pair))
    for i, r in enumerate(ok, start=1):
        r.rank = i
    return ok + other
