"""Tests for deterministic MAIN/S1/S2/S3/S4/S7 layers (no AI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from deterministic_layers.composite import score_universe
from deterministic_layers.main import main_points_from_total_score
from deterministic_layers.s1_cross_section import return_nd, s1_cross_sectional_points
from deterministic_layers.s2_regime import classify_regime
from deterministic_layers.s3_lead_lag import s3_lead_lag_points
from deterministic_layers.s4_onchain import (
    S4_NEUTRAL,
    UnavailableOnchainProvider,
    s4_contribution_for_final,
    s4_points,
)
from deterministic_layers.s7_volatility import s7_volatility_points
from deterministic_layers.safety import (
    assert_dry_run_true,
    assert_max_open_trades_research_safe,
    validate_research_trading_config,
)
from deterministic_layers.weights import WEIGHTS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
from score4window_scoring import apply_score4window_scores, window_score


def _ohlcv(n: int = 90, start: float = 100.0, drift: float = 0.01, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = [start]
    for _ in range(n - 1):
        close.append(close[-1] * (1 + drift + rng.normal(0, 0.01)))
    close_a = np.asarray(close, dtype=float)
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "open": close_a,
            "high": close_a * 1.01,
            "low": close_a * 0.99,
            "close": close_a,
            "volume": np.full(n, 1_000.0),
        }
    )


def test_weights_sum_100():
    assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9


@pytest.mark.parametrize(
    ("total", "expected"),
    [(-4, 0.0), (0, 15.0), (4, 30.0), (2, 22.5)],
)
def test_main_normalization(total, expected):
    assert main_points_from_total_score(total) == pytest.approx(expected)


def test_main_matches_score4window_semantics():
    df = apply_score4window_scores(_ohlcv(seed=7, drift=0.02))
    total = float(df["total_score"].iloc[-1])
    close = df["close"]
    manual = float(
        window_score(close, 5).iloc[-1]
        + window_score(close, 10).iloc[-1]
        + window_score(close, 21).iloc[-1]
        + window_score(close, 42).iloc[-1]
    )
    assert total == pytest.approx(manual)
    assert main_points_from_total_score(total) == pytest.approx(((manual + 4) / 8) * 30)


def test_s1_ranking_deterministic_and_complete():
    pairs = ["A/USDT", "B/USDT", "C/USDT"]
    totals = {"A/USDT": 4.0, "B/USDT": 0.0, "C/USDT": -4.0}
    rets = {"A/USDT": 0.2, "B/USDT": 0.0, "C/USDT": -0.2}
    out1 = s1_cross_sectional_points(pairs=pairs, total_scores=totals, returns_5d=rets)
    out2 = s1_cross_sectional_points(pairs=pairs, total_scores=totals, returns_5d=rets)
    assert out1 == out2
    assert out1["A/USDT"]["s1_score"] > out1["C/USDT"]["s1_score"]
    out3 = s1_cross_sectional_points(
        pairs=pairs,
        total_scores={"A/USDT": 4.0, "B/USDT": None, "C/USDT": -2.0},
        returns_5d={"A/USDT": 0.1, "B/USDT": 0.0, "C/USDT": -0.1},
    )
    assert out3["B/USDT"]["status"] == "insufficient_data"
    assert out3["B/USDT"]["s1_score"] is None


def test_s1_no_future_leak_via_return_nd():
    df = _ohlcv(n=30, seed=1)
    base = return_nd(df["close"], 5)
    future = df.iloc[[-1]].copy()
    future["date"] = df["date"].iloc[-1] + pd.Timedelta(days=1)
    future["close"] = df["close"].iloc[-1] * 10
    extended = pd.concat([df, future], ignore_index=True)
    as_of = return_nd(extended.iloc[:-1]["close"], 5)
    assert base == pytest.approx(as_of)


def test_s2_regime_deterministic():
    btc = _ohlcv(n=80, drift=0.03, seed=2)["close"]
    rets = {f"P{i}/USDT": 0.05 for i in range(10)}
    a = classify_regime(btc_close=btc, returns_5d=rets)
    b = classify_regime(btc_close=btc, returns_5d=rets)
    assert a == b
    assert a.s2_score is not None
    assert 0 <= a.s2_score <= 15
    assert a.regime in {"BULL", "NEUTRAL", "BEAR", "insufficient_data"}


def test_s3_lagged_no_lookahead():
    pair = _ohlcv(n=80, drift=0.02, seed=3)["close"]
    btc = _ohlcv(n=80, drift=0.015, seed=4)["close"]
    out1 = s3_lead_lag_points(pair_close=pair, leader_closes={"BTC/USDT": btc})
    pair_ext = pd.concat([pair, pd.Series([pair.iloc[-1] * 5])], ignore_index=True)
    btc_ext = pd.concat([btc, pd.Series([btc.iloc[-1] * 5])], ignore_index=True)
    out2 = s3_lead_lag_points(
        pair_close=pair_ext.iloc[:-1],
        leader_closes={"BTC/USDT": btc_ext.iloc[:-1]},
    )
    assert out1["s3_score"] == pytest.approx(out2["s3_score"])
    assert out1["status"] == "ok"


def test_s4_unavailable_not_punitive():
    res = s4_points("BTC/USDT", UnavailableOnchainProvider())
    assert res.status == "unavailable"
    assert res.s4_score is None
    assert s4_contribution_for_final(res) == pytest.approx(S4_NEUTRAL)


def test_s7_volatility_deterministic():
    df = _ohlcv(n=100, seed=5, drift=0.01)
    a = s7_volatility_points(df, total_score=2.0)
    b = s7_volatility_points(df, total_score=2.0)
    assert a == b
    assert a["status"] == "ok"
    assert 0 <= a["s7_score"] <= 10


def test_final_score_bounds_and_sum():
    frames = {
        "BTC/USDT": apply_score4window_scores(_ohlcv(seed=1, drift=0.02)),
        "ETH/USDT": apply_score4window_scores(_ohlcv(seed=2, drift=0.015)),
        "SOL/USDT": apply_score4window_scores(_ohlcv(seed=3, drift=0.025)),
        "AAA/USDT": apply_score4window_scores(_ohlcv(seed=4, drift=-0.01)),
    }
    rows = score_universe(frames)
    ok = [r for r in rows if r.status == "ok"]
    assert ok
    assert len({r.pair for r in rows}) == len(rows)
    for r in ok:
        assert 0 <= r.final_score <= 100
        expected = (
            r.main_score
            + r.s1_score
            + r.s2_score
            + r.s3_score
            + S4_NEUTRAL
            + r.s7_score
        )
        assert r.final_score == pytest.approx(min(100.0, expected))
        assert r.s4_status == "unavailable"


def test_replay_as_of_ignores_future_candles():
    frames = {
        "BTC/USDT": apply_score4window_scores(_ohlcv(n=100, seed=1, drift=0.02)),
        "ETH/USDT": apply_score4window_scores(_ohlcv(n=100, seed=2, drift=0.01)),
        "SOL/USDT": apply_score4window_scores(_ohlcv(n=100, seed=3, drift=0.015)),
    }
    as_of = frames["BTC/USDT"]["date"].iloc[-10]
    base = {
        r.pair: r.final_score
        for r in score_universe(frames, as_of=as_of)
        if r.status == "ok"
    }
    mutated = {}
    for p, df in frames.items():
        d = df.copy()
        mask = d["date"] > as_of
        d.loc[mask, "close"] = d.loc[mask, "close"] * 3
        mutated[p] = apply_score4window_scores(d)
    after = {
        r.pair: r.final_score
        for r in score_universe(mutated, as_of=as_of)
        if r.status == "ok"
    }
    assert base == after


def test_dry_run_and_max_open_trades_safety():
    validate_research_trading_config(
        {"dry_run": True, "max_open_trades": 1000, "stake_amount": "unlimited"}
    )
    with pytest.raises(RuntimeError):
        assert_dry_run_true({"dry_run": False})
    # Both unlimited → forbidden (Freqtrade rule)
    with pytest.raises(RuntimeError):
        assert_max_open_trades_research_safe(
            {"dry_run": True, "max_open_trades": -1, "stake_amount": "unlimited"}
        )
    # -1 only OK with fixed stake + dry_run
    assert_max_open_trades_research_safe(
        {"dry_run": True, "max_open_trades": -1, "stake_amount": 100}
    )
    with pytest.raises(RuntimeError):
        assert_max_open_trades_research_safe(
            {"dry_run": False, "max_open_trades": -1, "stake_amount": 100}
        )


def test_config_dry_run_true_and_research_slot_cap():
    cfg = json.loads(Path("user_data/config.json").read_text())
    assert cfg.get("dry_run") is True
    assert cfg.get("max_open_trades") == 100
    assert cfg.get("stake_amount") == "unlimited"
    validate_research_trading_config(cfg)


def test_mode_aliases():
    from score_scan import normalize_mode

    assert normalize_mode("force") == "force"
    assert normalize_mode("hourly") == "hourly"
    assert normalize_mode("force") == "force"
    assert normalize_mode("hourly") == "hourly"
