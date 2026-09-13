"""Tests for pre-AI active top-N universe selection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from active_universe import (
    DEFAULT_REFRESH_MINUTES,
    DEFAULT_TOP_N,
    ActiveUniverseState,
    load_active_universe_settings,
    select_top_pairs,
    should_refresh,
)
from active_universe.manager import write_active_universe_report


def _row(pair: str, *, rank: int, final: float | None = None, score: float = 2.0, status="ok"):
    return SimpleNamespace(
        pair=pair,
        status=status,
        rank=rank,
        final_score=final,
        score=score,
    )


def test_defaults():
    assert DEFAULT_TOP_N == 15
    assert DEFAULT_REFRESH_MINUTES == 30


def test_load_settings_absent_means_disabled():
    settings = load_active_universe_settings({"dry_run": True})
    assert settings["enabled"] is False


def test_load_settings_from_config():
    settings = load_active_universe_settings(
        {
            "active_universe": {
                "enabled": True,
                "top_n": 15,
                "refresh_minutes": 30,
                "exit_when_dropped": False,
                "reports_dir": "reports",
            }
        }
    )
    assert settings["enabled"] is True
    assert settings["top_n"] == 15
    assert settings["refresh_minutes"] == 30
    assert settings["exit_when_dropped"] is False


def test_select_top_pairs_takes_first_n_by_rank():
    rows = [
        _row("Z/USDT", rank=3, final=70.0),
        _row("A/USDT", rank=1, final=90.0),
        _row("B/USDT", rank=2, final=80.0),
        _row("BAD/USDT", rank=4, final=99.0, status="error"),
        _row("C/USDT", rank=4, final=60.0),
        _row("D/USDT", rank=5, final=50.0),
    ]
    pairs, ranks, scores = select_top_pairs(rows, top_n=3)
    assert pairs == ["A/USDT", "B/USDT", "Z/USDT"]
    assert ranks["A/USDT"] == 1
    assert scores["A/USDT"] == 90.0
    assert "BAD/USDT" not in pairs
    assert "C/USDT" not in pairs


def test_select_top_pairs_falls_back_to_score():
    rows = [_row("X/USDT", rank=1, final=None, score=3.0)]
    pairs, _ranks, scores = select_top_pairs(rows, top_n=15)
    assert pairs == ["X/USDT"]
    assert scores["X/USDT"] == 3.0


def test_should_refresh_throttle():
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    state = ActiveUniverseState(refreshed_at=None)
    assert should_refresh(state, now, 30) is True

    state.refreshed_at = now.isoformat()
    assert should_refresh(state, now, 30) is False
    assert should_refresh(state, now + timedelta(minutes=29), 30) is False
    assert should_refresh(state, now + timedelta(minutes=30), 30) is True


def test_write_report(tmp_path: Path):
    state = ActiveUniverseState(
        enabled=True,
        top_n=15,
        pairs=["BTC/USDT", "ETH/USDT"],
        ranks={"BTC/USDT": 1, "ETH/USDT": 2},
        scores={"BTC/USDT": 88.0, "ETH/USDT": 77.0},
        refreshed_at="2026-09-13T12:00:00+00:00",
    )
    path = write_active_universe_report(state, tmp_path)
    assert path.name == "active_top15_latest.json"
    payload = json.loads(path.read_text())
    assert payload["pairs"] == ["BTC/USDT", "ETH/USDT"]
    assert payload["top_n"] == 15


def test_config_active_universe_and_slot_cap():
    cfg = json.loads(Path("user_data/config.json").read_text())
    assert cfg.get("max_open_trades") == 100
    assert cfg.get("stake_amount") == "unlimited"
    block = cfg.get("active_universe") or {}
    assert block.get("enabled") is True
    assert block.get("top_n") == 15
    assert block.get("refresh_minutes") == 30
    assert block.get("exit_when_dropped") is False

    uni = json.loads(Path("user_data/config_binance_universe100.json").read_text())
    assert uni.get("max_open_trades") == 100
    assert (uni.get("active_universe") or {}).get("top_n") == 15


def test_strategy_custom_exit_drop_disabled_by_default():
    from freqtrade.resolvers import StrategyResolver

    user_data = Path("user_data")
    strat = StrategyResolver.load_strategy(
        {
            "strategy": "Score4WindowStrategy",
            "strategy_path": str(user_data / "strategies"),
            "user_data_dir": user_data,
            "timeframe": "1d",
            "stake_currency": "USDT",
            "dry_run": True,
            "exchange": {"name": "binance"},
            "active_universe": {
                "enabled": True,
                "top_n": 15,
                "refresh_minutes": 30,
                "exit_when_dropped": False,
            },
        }
    )
    assert strat.use_exit_signal is True
    strat._active_universe = ActiveUniverseState(
        enabled=True,
        top_n=15,
        exit_when_dropped=False,
        pairs=["ETHFI/USDT", "NEAR/USDT"],
    )
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    # Left Top-15 but drop-exit OFF → keep trade open (ROI/SL handle exits).
    assert (
        strat.custom_exit("SOL/USDT", trade=object(), current_time=now, current_rate=1.0, current_profit=0.0)
        is None
    )
    assert (
        strat.custom_exit("NEAR/USDT", trade=object(), current_time=now, current_rate=1.0, current_profit=0.0)
        is None
    )
