"""
Historical (backtest/hyperopt) Top-N membership — candle-causal ranking.

Live / dry-run continue to use bot_loop_start refresh + ActiveUniverseState.
This module only builds a date → top-N map using score_universe(..., as_of=T)
so each timestamp T uses data with date <= T (no lookahead).

Does not change Score4Window, composite, or S1 math.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_ts(value: Any) -> pd.Timestamp:
    """UTC-normalized timestamp key for membership lookup."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def is_optimize_runmode(config: dict[str, Any] | None) -> bool:
    """True for backtest / hyperopt (historical candle replay)."""
    if not config:
        return False
    rm = config.get("runmode")
    if rm is None:
        return False
    value = getattr(rm, "value", rm)
    return str(value).lower() in ("backtest", "hyperopt")


def _pair_feather_path(datadir: Path, pair: str, timeframe: str) -> Path | None:
    stem = pair.replace("/", "_").replace(":", "_")
    candidates = [
        datadir / f"{stem}-{timeframe}.feather",
        datadir / f"{pair.replace('/', '_')}-{timeframe}.feather",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def resolve_datadir(config: dict[str, Any] | None) -> Path | None:
    if not config:
        return None
    datadir = config.get("datadir")
    if datadir is not None:
        return Path(datadir)
    userdir = config.get("user_data_dir")
    exchange = (config.get("exchange") or {}).get("name") or "binance"
    if userdir:
        return Path(userdir) / "data" / exchange
    return None


def load_ohlcv_disk(datadir: Path, pair: str, timeframe: str) -> pd.DataFrame | None:
    """Load full OHLCV from disk (no DP date slicing — safe for precompute)."""
    path = _pair_feather_path(datadir, pair, timeframe)
    if path is None:
        return None
    df = pd.read_feather(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def load_scored_universe_frames(
    *,
    pairs: Sequence[str],
    timeframe: str,
    datadir: Path,
    scored_frames: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Return pair → scored OHLCV (Score4Window columns).

    If `scored_frames` is provided (tests), it is returned as-is after ensuring
    Score4Window columns exist.
    """
    strat_dir = str(Path(__file__).resolve().parents[1] / "user_data" / "strategies")
    if strat_dir not in sys.path:
        sys.path.insert(0, strat_dir)
    from score4window_scoring import apply_score4window_scores

    if scored_frames is not None:
        out: dict[str, pd.DataFrame] = {}
        for pair, df in scored_frames.items():
            if df is None or df.empty:
                continue
            if "total_score" not in df.columns:
                out[pair] = apply_score4window_scores(df.copy())
            else:
                out[pair] = df
        return out

    out = {}
    for pair in pairs:
        raw = load_ohlcv_disk(datadir, pair, timeframe)
        if raw is None or raw.empty:
            continue
        out[pair] = apply_score4window_scores(raw.copy())
    return out


def collect_ranking_dates(
    scored_frames: dict[str, pd.DataFrame],
    *,
    min_candles: int = 43,
) -> list[pd.Timestamp]:
    """Union of candle dates where at least one pair has enough history."""
    dates: set[pd.Timestamp] = set()
    for df in scored_frames.values():
        if df is None or df.empty or "date" not in df.columns:
            continue
        if len(df) < min_candles:
            continue
        usable = df["date"].iloc[min_candles - 1 :]
        for d in usable:
            dates.add(normalize_ts(d))
    return sorted(dates)


def top_pairs_at(
    scored_frames: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    *,
    top_n: int,
) -> frozenset[str]:
    """Causal Top-N at timestamp `as_of` via existing score_universe math."""
    from active_universe.manager import select_top_pairs
    from deterministic_layers.composite import score_universe

    as_of_n = normalize_ts(as_of)
    ranked = score_universe(scored_frames, as_of=as_of_n)
    pairs, _ranks, _scores = select_top_pairs(ranked, top_n=top_n)
    return frozenset(pairs)


def build_historical_top_membership(
    scored_frames: dict[str, pd.DataFrame],
    *,
    top_n: int = 15,
    dates: Iterable[pd.Timestamp] | None = None,
    min_candles: int = 43,
) -> dict[pd.Timestamp, frozenset[str]]:
    """
    Build date → frozenset(top-N pairs) using only data <= each date.

    Ranking math is unchanged (score_universe + select_top_pairs).
    """
    if not scored_frames:
        return {}

    if dates is None:
        date_list = collect_ranking_dates(scored_frames, min_candles=min_candles)
    else:
        date_list = [normalize_ts(d) for d in dates]

    membership: dict[pd.Timestamp, frozenset[str]] = {}
    total = len(date_list)
    log_every = max(1, total // 10) if total else 1
    for i, as_of in enumerate(date_list):
        membership[as_of] = top_pairs_at(scored_frames, as_of, top_n=top_n)
        if i == 0 or (i + 1) % log_every == 0 or i + 1 == total:
            logger.info(
                "historical_top15: ranked %s/%s dates (top_n=%s, as_of=%s, size=%s)",
                i + 1,
                total,
                top_n,
                as_of,
                len(membership[as_of]),
            )
    return membership


def pair_in_membership(
    membership: dict[pd.Timestamp, frozenset[str]],
    pair: str,
    when: Any,
) -> bool:
    """Lookup whether pair is in Top-N at `when`. Missing date → False (block)."""
    if not membership:
        return False
    key = normalize_ts(when)
    top = membership.get(key)
    if top is None:
        # Fallback: last ranking at or before `when` (handles intra-candle callbacks)
        prior = [d for d in membership if d <= key]
        if not prior:
            return False
        top = membership[max(prior)]
    return pair in top


def membership_series_for_pair(
    membership: dict[pd.Timestamp, frozenset[str]],
    pair: str,
    dates: pd.Series,
) -> pd.Series:
    """Boolean Series aligned to `dates` — True when pair is in historical Top-N."""
    if not membership:
        return pd.Series(False, index=dates.index)
    keys = [normalize_ts(d) for d in dates]
    # Build sorted date index for asof fallback
    sorted_keys = sorted(membership.keys())
    if not sorted_keys:
        return pd.Series(False, index=dates.index)

    values: list[bool] = []
    # Pointer scan for speed on sorted candle dates
    j = -1
    n = len(sorted_keys)
    for key in keys:
        while j + 1 < n and sorted_keys[j + 1] <= key:
            j += 1
        if j < 0:
            values.append(False)
        else:
            values.append(pair in membership[sorted_keys[j]])
    return pd.Series(values, index=dates.index)
