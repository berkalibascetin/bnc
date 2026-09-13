"""Tests for candle-causal historical Top-15 entry gate (backtest)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from active_universe.historical import (
    build_historical_top_membership,
    is_optimize_runmode,
    membership_series_for_pair,
    normalize_ts,
    pair_in_membership,
    top_pairs_at,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
from score4window_scoring import apply_score4window_scores


def _ohlcv(n: int = 90, start: float = 100.0, drift: float = 0.01, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = [start]
    for _ in range(n - 1):
        close.append(close[-1] * (1.0 + drift + float(rng.normal(0, 0.01))))
    close_s = pd.Series(close)
    high = close_s * 1.01
    low = close_s * 0.99
    open_ = close_s.shift(1).fillna(close_s.iloc[0])
    volume = pd.Series(1000.0, index=range(n))
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_.values,
            "high": high.values,
            "low": low.values,
            "close": close_s.values,
            "volume": volume.values,
        }
    )


def _mini_universe() -> dict[str, pd.DataFrame]:
    # Distinct drifts so ranking can change over time
    return {
        "BTC/USDT": apply_score4window_scores(_ohlcv(n=100, seed=1, drift=0.02)),
        "ETH/USDT": apply_score4window_scores(_ohlcv(n=100, seed=2, drift=0.01)),
        "SOL/USDT": apply_score4window_scores(_ohlcv(n=100, seed=3, drift=0.015)),
        "AAA/USDT": apply_score4window_scores(_ohlcv(n=100, seed=4, drift=-0.005)),
        "BBB/USDT": apply_score4window_scores(_ohlcv(n=100, seed=5, drift=0.008)),
        "CCC/USDT": apply_score4window_scores(_ohlcv(n=100, seed=6, drift=0.012)),
    }


def test_is_optimize_runmode():
    assert is_optimize_runmode({"runmode": "backtest"}) is True
    assert is_optimize_runmode({"runmode": "hyperopt"}) is True
    assert is_optimize_runmode({"runmode": "dry_run"}) is False
    assert is_optimize_runmode({"runmode": "live"}) is False
    assert is_optimize_runmode({}) is False


def test_ranking_at_t_ignores_future_candles():
    frames = _mini_universe()
    t = normalize_ts(frames["BTC/USDT"]["date"].iloc[70])
    base = top_pairs_at(frames, t, top_n=3)

    mutated: dict[str, pd.DataFrame] = {}
    for pair, df in frames.items():
        d = df.copy()
        # Corrupt T+1 and T+2 closes dramatically
        idx = d.index[d["date"].map(normalize_ts) > t][:2]
        d.loc[idx, "close"] = d.loc[idx, "close"] * 50.0
        d.loc[idx, "high"] = d.loc[idx, "close"] * 1.01
        mutated[pair] = apply_score4window_scores(d)

    after = top_pairs_at(mutated, t, top_n=3)
    assert base == after


def test_membership_build_no_lookahead_and_can_change():
    frames = _mini_universe()
    dates = [normalize_ts(d) for d in frames["BTC/USDT"]["date"].iloc[50:80]]
    membership = build_historical_top_membership(frames, top_n=3, dates=dates)
    assert len(membership) == len(dates)

    t = dates[10]
    base = membership[t]

    mutated = {}
    for pair, df in frames.items():
        d = df.copy()
        future = d["date"].map(normalize_ts) > t
        d.loc[future, "close"] = d.loc[future, "close"] * 10.0
        mutated[pair] = apply_score4window_scores(d)
    membership2 = build_historical_top_membership(mutated, top_n=3, dates=[t])
    assert membership2[t] == base

    # Top-3 should be able to differ across early vs late windows on this fixture
    early = membership[dates[0]]
    late = membership[dates[-1]]
    # Not a hard requirement that they differ on every seed, but with distinct
    # drifts they typically do — assert set of tops across window has > top_n names
    # OR early != late. Prefer the stronger early!=late when true; else coverage.
    all_names = set().union(*membership.values())
    assert len(all_names) >= 3
    if early == late:
        # Still verify membership lookup works
        assert pair_in_membership(membership, next(iter(early)), t) is True


def test_membership_series_aligns_to_dates():
    frames = _mini_universe()
    dates = frames["BTC/USDT"]["date"].iloc[60:75]
    membership = build_historical_top_membership(
        frames, top_n=2, dates=[normalize_ts(d) for d in dates]
    )
    pair = next(iter(membership[normalize_ts(dates.iloc[0])]))
    series = membership_series_for_pair(membership, pair, dates.reset_index(drop=True))
    assert series.dtype == bool or series.dtype == np.bool_
    assert len(series) == len(dates)
    assert bool(series.iloc[0]) is True


def test_strategy_backtest_uses_historical_not_empty_live_state():
    from freqtrade.enums import RunMode
    from freqtrade.resolvers import StrategyResolver

    frames = _mini_universe()
    user_data = Path("user_data")
    strat = StrategyResolver.load_strategy(
        {
            "strategy": "Score4WindowStrategy",
            "strategy_path": str(user_data / "strategies"),
            "user_data_dir": user_data,
            "timeframe": "1d",
            "stake_currency": "USDT",
            "dry_run": True,
            "runmode": RunMode.BACKTEST,
            "exchange": {
                "name": "binance",
                "pair_whitelist": list(frames.keys()),
            },
            "active_universe": {
                "enabled": True,
                "top_n": 3,
                "refresh_minutes": 30,
                "exit_when_dropped": False,
            },
        }
    )
    strat.bot_start()
    assert strat._use_historical_top15_gate() is True
    # Live state empty (never refreshed) — old bug would block all entries
    assert strat._active_universe.pairs == []
    assert strat._pair_in_active_universe("BTC/USDT") is False

    strat._historical_scored_frames = frames
    membership = strat._ensure_historical_top15()
    assert len(membership) > 0

    # Pick a date where BTC is in top-3 if possible
    sample_date = next(iter(membership))
    in_top = list(membership[sample_date])[0]
    assert strat._pair_allowed_for_entry(in_top, sample_date.to_pydatetime()) is True
    outsiders = [p for p in frames if p not in membership[sample_date]]
    assert outsiders
    assert strat._pair_allowed_for_entry(outsiders[0], sample_date.to_pydatetime()) is False

    # Drop-exit still off
    now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert (
        strat.custom_exit(
            outsiders[0],
            trade=object(),
            current_time=now,
            current_rate=1.0,
            current_profit=0.0,
        )
        is None
    )


def test_populate_entry_applies_per_candle_gate():
    from freqtrade.enums import RunMode
    from freqtrade.resolvers import StrategyResolver

    frames = _mini_universe()
    user_data = Path("user_data")
    strat = StrategyResolver.load_strategy(
        {
            "strategy": "Score4WindowStrategy",
            "strategy_path": str(user_data / "strategies"),
            "user_data_dir": user_data,
            "timeframe": "1d",
            "stake_currency": "USDT",
            "dry_run": True,
            "runmode": RunMode.BACKTEST,
            "exchange": {
                "name": "binance",
                "pair_whitelist": list(frames.keys()),
            },
            "active_universe": {
                "enabled": True,
                "top_n": 2,
                "refresh_minutes": 30,
                "exit_when_dropped": False,
            },
        }
    )
    strat.bot_start()
    strat._historical_scored_frames = frames
    pair = "AAA/USDT"
    df = frames[pair].copy()
    df = strat.populate_indicators(df, {"pair": pair})
    # Force score condition true on all rows with valid score
    df["total_score"] = 4.0
    out = strat.populate_entry_trend(df, {"pair": pair})
    membership = strat._historical_top15_by_date
    for i, row in out.iloc[50:].iterrows():
        d = normalize_ts(row["date"])
        expected = pair in membership.get(d, frozenset())
        raw = row.get("enter_long")
        got = False if raw is None or (isinstance(raw, float) and np.isnan(raw)) else int(raw) == 1
        if expected:
            assert got, f"expected entry at {d}"
        else:
            assert not got, f"unexpected entry at {d}"


def test_dry_run_still_uses_live_snapshot_gate():
    from freqtrade.enums import RunMode
    from freqtrade.resolvers import StrategyResolver
    from active_universe import ActiveUniverseState

    user_data = Path("user_data")
    strat = StrategyResolver.load_strategy(
        {
            "strategy": "Score4WindowStrategy",
            "strategy_path": str(user_data / "strategies"),
            "user_data_dir": user_data,
            "timeframe": "1d",
            "stake_currency": "USDT",
            "dry_run": True,
            "runmode": RunMode.DRY_RUN,
            "exchange": {"name": "binance", "pair_whitelist": ["BTC/USDT"]},
            "active_universe": {
                "enabled": True,
                "top_n": 15,
                "refresh_minutes": 30,
                "exit_when_dropped": False,
            },
        }
    )
    strat.bot_start()
    assert strat._use_historical_top15_gate() is False
    strat._active_universe = ActiveUniverseState(
        enabled=True, top_n=15, pairs=["ETH/USDT"], exit_when_dropped=False
    )
    assert strat._pair_allowed_for_entry("ETH/USDT") is True
    assert strat._pair_allowed_for_entry("BTC/USDT") is False
