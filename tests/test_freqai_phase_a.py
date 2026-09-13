"""Phase A FreqAI + Top-15 policy tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from active_universe import ActiveUniverseState, load_active_universe_settings
from deterministic_layers.pair_local_features import attach_phase_a_deterministic_columns
from score4window_scoring import apply_score4window_scores


def test_config_exit_when_dropped_default_off():
    cfg = json.loads(Path("user_data/config.json").read_text())
    assert cfg["active_universe"]["exit_when_dropped"] is False
    uni = json.loads(Path("user_data/config_binance_universe100.json").read_text())
    assert uni["active_universe"]["exit_when_dropped"] is False
    freq = json.loads(Path("user_data/config_freqai_dryrun.json").read_text())
    assert freq["dry_run"] is True
    assert freq["freqai"]["enabled"] is True
    assert freq["active_universe"]["exit_when_dropped"] is False
    assert freq["freqai"]["feature_parameters"]["label_period_candles"] == 1


def test_settings_default_exit_when_dropped_false():
    settings = load_active_universe_settings({"active_universe": {"enabled": True}})
    assert settings["exit_when_dropped"] is False


def test_drop_from_top15_does_not_exit_when_flag_off():
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
    strat._active_universe = ActiveUniverseState(
        enabled=True,
        top_n=15,
        exit_when_dropped=False,
        pairs=["ETHFI/USDT", "NEAR/USDT"],
    )
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    assert (
        strat.custom_exit(
            "SOL/USDT",
            trade=object(),
            current_time=now,
            current_rate=1.0,
            current_profit=0.0,
        )
        is None
    )


def test_top15_entry_gate_blocks_outside_allows_inside():
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
    strat._active_universe = ActiveUniverseState(
        enabled=True,
        top_n=15,
        exit_when_dropped=False,
        pairs=["NEAR/USDT", "ETHFI/USDT"],
    )
    assert strat._pair_in_active_universe("NEAR/USDT") is True
    assert strat._pair_in_active_universe("SOL/USDT") is False


def test_phase_a_features_are_causal_and_complete():
    n = 90
    close = np.linspace(100, 150, n) + np.random.RandomState(0).randn(n)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000.0),
        }
    )
    df = apply_score4window_scores(df)
    out = attach_phase_a_deterministic_columns(df)
    for col in ("dl_main", "dl_s3", "dl_s4", "dl_s7", "dl_final_score"):
        assert col in out.columns
        assert not pd.isna(out[col].iloc[-1])
    assert "dl_s1" not in out.columns
    assert "dl_s2" not in out.columns
    assert "dl_rank" not in out.columns
    assert 0.0 <= float(out["dl_final_score"].iloc[-1]) <= 100.0


def test_freqai_target_shift_only_on_label():
    from Score4WindowFreqaiStrategy import Score4WindowFreqaiStrategy

    strat = object.__new__(Score4WindowFreqaiStrategy)
    strat.config = {"freqai": {"feature_parameters": {"label_period_candles": 1}}}
    strat.freqai_info = {"feature_parameters": {"label_period_candles": 1}}
    n = 30
    close = np.arange(100, 100 + n, dtype=float)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": np.ones(n),
        }
    )
    out = Score4WindowFreqaiStrategy.set_freqai_targets(strat, df.copy(), {"pair": "BTC/USDT"})
    assert "&-s_close" in out.columns
    assert pd.isna(out["&-s_close"].iloc[-1])
    expected = close[1] / close[0] - 1.0
    assert abs(float(out["&-s_close"].iloc[0]) - expected) < 1e-12


def test_opt_in_drop_exit_still_works_if_explicitly_enabled():
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
                "exit_when_dropped": True,
            },
        }
    )
    strat._active_universe = ActiveUniverseState(
        enabled=True,
        top_n=15,
        exit_when_dropped=True,
        pairs=["NEAR/USDT"],
    )
    now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
    assert (
        strat.custom_exit(
            "SOL/USDT",
            trade=object(),
            current_time=now,
            current_rate=1.0,
            current_profit=0.0,
        )
        == "dropped_from_top15"
    )
