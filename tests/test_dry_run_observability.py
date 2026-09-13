"""Unit tests for dry-run observability reporter."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dry_run_observability.core import (
    analyze_trades_orders,
    analyze_universe,
    build_report,
    classify_log_lines,
    classify_message,
    render_markdown,
    safety_check,
    summarize_prefix,
)


def test_pair_counting_and_duplicates():
    config = {
        "exchange": {
            "name": "binance",
            "pair_whitelist": ["BTC/USDT", "ETH/USDT", "BTC/USDT", "SOL/BTC"],
        }
    }
    uni = analyze_universe(config, None)
    assert uni["configured_pair_count"] == 4
    assert uni["unique_pair_count"] == 3
    assert uni["duplicates"] == ["BTC/USDT"]
    assert uni["non_usdt_pairs"] == ["SOL/BTC"]


def test_open_order_vs_open_trade_distinction():
    trades = [
        {
            "id": 1,
            "pair": "ETH/USDT",
            "is_open": 1,
            "amount": 0.0,
            "open_rate": 2500.0,
            "open_date": "2026-09-12 10:00:00",
            "enter_tag": None,
            "stake_amount": 10,
        }
    ]
    orders = [
        {
            "id": 1,
            "order_id": "dry_1",
            "ft_trade_id": 1,
            "ft_is_open": 1,
            "ft_pair": "ETH/USDT",
            "symbol": "ETH/USDT",
            "status": "open",
            "amount": 0.0,
            "ft_amount": 0.0,
            "filled": 0.0,
            "order_date": "2026-09-12 10:00:00",
        }
    ]
    now = datetime(2026, 9, 12, 11, 0, 0)
    result = analyze_trades_orders(trades, orders, now=now, long_open_order_minutes=30)
    assert result["trades"]["currently_open"] == 1
    assert result["orders"]["open"] == 1
    assert result["orders"]["filled"] == 0
    assert any("amount_zero" in s.get("reasons", []) for s in result["orders"]["suspicious"])
    assert any(s.get("kind") == "trade" for s in result["orders"]["suspicious"])


def test_amount_zero_long_running_order_flagged():
    orders = [
        {
            "id": 9,
            "order_id": "x",
            "ft_is_open": 1,
            "ft_pair": "SOL/USDT",
            "status": "open",
            "amount": 0,
            "filled": 0,
            "order_date": "2026-09-12 08:00:00",
        }
    ]
    now = datetime(2026, 9, 12, 10, 0, 0)
    result = analyze_trades_orders([], orders, now=now, long_open_order_minutes=30)
    sus = result["orders"]["suspicious"]
    assert len(sus) == 1
    assert "amount_zero" in sus[0]["reasons"]
    assert "open_unusually_long" in sus[0]["reasons"]


def test_network_error_classification():
    assert classify_message("NetworkError: binance GET ...").startswith("network:")
    assert classify_message("RequestTimeout while fetching").startswith("network:")
    events = classify_log_lines(
        [
            "2026-09-12 14:34:31,125 - freqtrade.exchange.common - WARNING - fetch_ticker() NetworkError for BNB/USDT",
            "2026-09-12 14:35:41,263 - freqtrade.exchange.exchange_ws - ERROR - Connection to wss://stream.binance.com timed out",
        ]
    )
    summary = summarize_prefix(events, "network:")
    assert summary["total"] >= 2


def test_strategy_exception_classification():
    assert classify_message("Traceback (most recent call last):").startswith("system:")
    events = classify_log_lines(
        [
            "2026-09-12 15:00:00,000 - freqtrade - ERROR - Traceback (most recent call last):",
            '  File "x.py", line 1, in <module>',
            "KeyError: 'close'",
            "2026-09-12 15:00:01,000 - freqtrade - INFO - continuing",
        ]
    )
    system = summarize_prefix(events, "system:")
    assert system["total"] >= 1
    assert summarize_prefix(events, "network:")["total"] == 0


def test_dry_run_safety_detection():
    ok = safety_check(
        {
            "dry_run": True,
            "exchange": {"name": "binance"},
            "timeframe": "1d",
            "max_open_trades": 5,
            "stake_amount": "unlimited",
        },
        3.0,
    )
    assert ok["dry_run"] is True
    assert ok["live_trading_disabled"] is True
    assert ok["safe_to_continue_dry_run"] is True

    bad = safety_check({"dry_run": False, "exchange": {"name": "binance"}}, 3.0)
    assert bad["dry_run"] is False
    assert bad["stop_reason"]


def test_missing_log_and_empty_db_handling(tmp_path: Path):
    cfg = {
        "dry_run": True,
        "timeframe": "1d",
        "max_open_trades": 5,
        "stake_amount": "unlimited",
        "exchange": {"name": "binance", "pair_whitelist": ["BTC/USDT", "ETH/USDT"]},
    }
    user_data = tmp_path / "user_data"
    (user_data / "strategies").mkdir(parents=True)
    (user_data / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    db = tmp_path / "tradesv3.dryrun.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, is_open INTEGER, amount REAL, pair TEXT, "
        "open_date TEXT, close_date TEXT, open_rate REAL, close_rate REAL, close_profit_abs REAL, "
        "stake_amount REAL, enter_tag TEXT, exit_reason TEXT)"
    )
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, ft_is_open INTEGER, status TEXT, amount REAL, "
        "ft_amount REAL, filled REAL, order_date TEXT, order_id TEXT, ft_pair TEXT, symbol TEXT, "
        "ft_cancel_reason TEXT)"
    )
    conn.commit()
    conn.close()

    report = build_report(tmp_path, db_path=db, config_path=user_data / "config.json")
    assert report["safety"]["dry_run"] is True
    assert report["trades"]["created"] == 0
    assert report["orders"]["created"] == 0
    assert any("log" in x.lower() for x in report["limitations"])
    md = render_markdown(report)
    assert "DRY-RUN OBSERVATION REPORT" in md


def test_incomplete_observation_period_na_metrics():
    result = analyze_trades_orders([], [])
    assert result["performance"]["realized_simulated_pnl"] is None
    assert result["performance"]["win_rate"] is None
    assert result["trades"]["average_duration_hours"] is None


def test_abort_when_dry_run_false(tmp_path: Path):
    cfg = {
        "dry_run": False,
        "exchange": {"name": "binance", "pair_whitelist": ["BTC/USDT"]},
        "timeframe": "1d",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    report = build_report(tmp_path, config_path=config_path)
    assert report["observation"]["status"] == "ABORTED"
    assert report["safety"]["dry_run"] is False
