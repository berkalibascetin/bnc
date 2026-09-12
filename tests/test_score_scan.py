"""Tests for observation-only score_scan layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from freqtrade.resolvers import StrategyResolver

from score_scan import normalize_mode
from score_scan.cli_patch import (
    apply_freqtrade_cli_patch,
    inject_score_scan_into_config,
)
from score_scan.engine import (
    assert_dry_run_safe,
    reset_hourly_state_for_tests,
    run_score_scan,
)
from score_scan.reporting import render_markdown

USER_DATA = Path(__file__).resolve().parents[1] / "user_data"
STRAT_PATH = USER_DATA / "strategies"


def _config(score_scan: str = "off", dry_run: bool = True, pairs: list[str] | None = None) -> dict:
    return {
        "strategy": "Score4WindowStrategy",
        "strategy_path": str(STRAT_PATH),
        "user_data_dir": USER_DATA,
        "datadir": USER_DATA / "data" / "binance",
        "timeframe": "1d",
        "stake_currency": "USDT",
        "dry_run": dry_run,
        "score_scan": score_scan,
        "exchange": {
            "name": "binance",
            "key": "",
            "secret": "",
            "pair_whitelist": pairs
            or ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        },
    }


def _load_strategy(cfg: dict | None = None):
    cfg = cfg or _config()
    strat = StrategyResolver.load_strategy(cfg)
    strat.config = cfg
    # bot_start sets score-scan pending flags; safe (no orders)
    strat.bot_start()
    return strat


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC"),
            "open": arr,
            "high": arr * 1.01,
            "low": arr * 0.99,
            "close": arr,
            "volume": np.full(n, 1000.0),
        }
    )


@pytest.fixture(autouse=True)
def _reset_scan_state():
    reset_hourly_state_for_tests()
    yield
    reset_hourly_state_for_tests()


class TestNormalizeMode:
    def test_valid(self):
        assert normalize_mode(None) == "off"
        assert normalize_mode("FORCE") == "force"
        assert normalize_mode("hourly") == "hourly"

    def test_invalid(self):
        with pytest.raises(ValueError):
            normalize_mode("daily")


class TestDryRunSafety:
    def test_requires_true(self):
        with pytest.raises(RuntimeError):
            assert_dry_run_safe({"dry_run": False})

    def test_scan_noop_when_live(self, tmp_path):
        strat = _load_strategy(_config(dry_run=True))
        cfg = _config(score_scan="force", dry_run=False)
        out = run_score_scan(
            strat, cfg, mode="force", reports_dir=tmp_path, print_table=False
        )
        assert out is None


class TestCliPatch:
    def test_registers_option(self):
        apply_freqtrade_cli_patch()
        from freqtrade.commands.arguments import ARGS_TRADE
        from freqtrade.commands.cli_options import AVAILABLE_CLI_OPTIONS

        assert "score_scan" in AVAILABLE_CLI_OPTIONS
        assert "--score-scan" in AVAILABLE_CLI_OPTIONS["score_scan"].cli
        assert "score_scan" in ARGS_TRADE

    def test_inject_preserves_dry_run(self):
        cfg = {"dry_run": True}
        inject_score_scan_into_config(cfg, {"score_scan": "force"})
        assert cfg["score_scan"] == "force"
        assert cfg["dry_run"] is True


class TestScanner:
    def test_off_skips(self, tmp_path):
        strat = _load_strategy(_config("off"))
        assert (
            run_score_scan(strat, strat.config, mode="off", reports_dir=tmp_path) is None
        )
        assert not (tmp_path / "score_scan_latest.json").exists()

    def test_force_writes_reports(self, tmp_path, monkeypatch):
        pairs = ["BTC/USDT", "ETH/USDT", "AAA/USDT"]
        cfg = _config("force", pairs=pairs)
        strat = _load_strategy(cfg)

        def fake_load(strategy, pair, timeframe):
            if pair == "AAA/USDT":
                return _ohlcv([1.0] * 10)
            return _ohlcv([float(i) for i in range(1, 80)])

        monkeypatch.setattr("score_scan.engine._load_ohlcv_for_pair", fake_load)
        report = run_score_scan(
            strat, cfg, mode="force", reports_dir=tmp_path, print_table=False
        )
        assert report is not None
        assert report.pair_count == 3
        assert (tmp_path / "score_scan_latest.json").exists()
        assert (tmp_path / "score_scan_latest.md").exists()
        payload = json.loads((tmp_path / "score_scan_latest.json").read_text())
        assert payload["mode"] == "force"
        assert len(payload["results"]) == 3
        insuff = [r for r in payload["results"] if r["status"] == "insufficient_data"]
        assert len(insuff) == 1
        assert insuff[0]["score"] is None  # never negative-score missing data
        ok = [r for r in payload["results"] if r["status"] == "ok"]
        assert ok[0]["rank"] == 1
        assert ok[0]["score"] == 4.0
        assert ok[0]["signal"] == "BUY"

    def test_hourly_same_hour_skipped(self, tmp_path, monkeypatch):
        cfg = _config("hourly", pairs=["BTC/USDT"])
        strat = _load_strategy(cfg)
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair",
            lambda *a, **k: _ohlcv([float(i) for i in range(1, 80)]),
        )
        now = datetime(2026, 9, 12, 15, 10, tzinfo=timezone.utc)
        r1 = run_score_scan(
            strat, cfg, mode="hourly", reports_dir=tmp_path, print_table=False, now=now
        )
        r2 = run_score_scan(
            strat,
            cfg,
            mode="hourly",
            reports_dir=tmp_path,
            print_table=False,
            now=datetime(2026, 9, 12, 15, 55, tzinfo=timezone.utc),
        )
        assert r1 is not None
        assert r2 is None

    def test_matches_strategy_populate(self, tmp_path, monkeypatch):
        cfg = _config("force", pairs=["BTC/USDT"])
        strat = _load_strategy(cfg)
        df = _ohlcv([float(i) for i in range(1, 80)])
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair", lambda *a, **k: df.copy()
        )
        report = run_score_scan(
            strat, cfg, mode="force", reports_dir=tmp_path, print_table=False
        )
        expected = float(
            strat.populate_indicators(df.copy(), {"pair": "BTC/USDT"}).iloc[-1][
                "total_score"
            ]
        )
        assert report.results[0].score == expected

    def test_no_orders(self, tmp_path, monkeypatch):
        cfg = _config("force", pairs=["BTC/USDT"])
        strat = _load_strategy(cfg)
        strat.exchange = MagicMock()
        strat.exchange.create_order.side_effect = AssertionError("no orders")
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair",
            lambda *a, **k: _ohlcv([float(i) for i in range(1, 80)]),
        )
        run_score_scan(strat, cfg, mode="force", reports_dir=tmp_path, print_table=False)
        strat.exchange.create_order.assert_not_called()

    def test_all_pairs_represented(self, tmp_path, monkeypatch):
        pairs = [f"P{i}/USDT" for i in range(10)]
        cfg = _config("force", pairs=pairs)
        strat = _load_strategy(cfg)
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair",
            lambda *a, **k: _ohlcv([float(i) for i in range(1, 80)]),
        )
        report = run_score_scan(
            strat, cfg, mode="force", reports_dir=tmp_path, print_table=False
        )
        assert {r.pair for r in report.results} == set(pairs)

    def test_concurrent_lock_skips(self, tmp_path, monkeypatch):
        import score_scan.engine as eng

        cfg = _config("force", pairs=["BTC/USDT"])
        strat = _load_strategy(cfg)
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair",
            lambda *a, **k: _ohlcv([float(i) for i in range(1, 80)]),
        )
        assert eng._SCAN_LOCK.acquire(blocking=False)
        try:
            assert (
                run_score_scan(
                    strat, cfg, mode="force", reports_dir=tmp_path, print_table=False
                )
                is None
            )
        finally:
            eng._SCAN_LOCK.release()

    def test_markdown(self):
        md = render_markdown(
            {
                "mode": "force",
                "timestamp": "t",
                "timeframe": "1d",
                "pair_count": 1,
                "dry_run": True,
                "entry_score_threshold": 2,
                "summary": {
                    "scored": 1,
                    "insufficient_data": 0,
                    "error": 0,
                    "max_score": 4,
                    "score_distribution": {"4": 1},
                    "buy_signals": ["BTC/USDT"],
                    "watch_candidates": [],
                },
                "results": [
                    {
                        "rank": 1,
                        "pair": "BTC/USDT",
                        "score": 4,
                        "signal": "BUY",
                        "candle_timestamp": "x",
                        "status": "ok",
                        "reason": None,
                    }
                ],
            }
        )
        assert "BTC/USDT" in md
        assert "Score Scan" in md


class TestStrategyHooks:
    def test_off_no_pending(self):
        strat = _load_strategy(_config("off"))
        assert strat._score_scan_force_pending is False

    def test_force_pending(self):
        strat = _load_strategy(_config("force"))
        assert strat._score_scan_force_pending is True

    def test_bot_loop_clears_force(self, tmp_path, monkeypatch):
        cfg = _config("force", pairs=["BTC/USDT"])
        strat = _load_strategy(cfg)
        monkeypatch.setattr(
            "score_scan.engine._load_ohlcv_for_pair",
            lambda *a, **k: _ohlcv([float(i) for i in range(1, 80)]),
        )

        real = run_score_scan

        def wrapped(strategy, config, **kwargs):
            kwargs.setdefault("reports_dir", tmp_path)
            kwargs.setdefault("print_table", False)
            return real(strategy, config, **kwargs)

        monkeypatch.setattr("score_scan.engine.run_score_scan", wrapped)
        strat.bot_loop_start(datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc))
        assert strat._score_scan_force_pending is False
