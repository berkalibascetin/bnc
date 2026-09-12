#!/usr/bin/env python3
"""
Download 1d OHLCV for the Binance universe via data-api.binance.vision.

Writes Freqtrade-compatible feather files under user_data/data/binance/.
Does not delete existing files for pairs outside the current download set.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://data-api.binance.vision"
DEFAULT_PAIRS = ROOT / "user_data/universes/binance_spot_usdt_top100_pairs.txt"
DEFAULT_OUT = ROOT / "user_data/data/binance"


def http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "bnc-universe-data/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def fetch_klines(api: str, symbol: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    out: list[list[Any]] = []
    cursor = start_ms
    while cursor < end_ms:
        qs = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": "1d",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
        )
        batch = http_get_json(f"{api}/api/v3/klines?{qs}")
        if not batch:
            break
        out.extend(batch)
        last_open = int(batch[-1][0])
        nxt = last_open + 86_400_000
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.05)
    return out


def klines_to_df(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )
    df = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().drop_duplicates(subset=["date"]).sort_values("date")
    return df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def pair_to_symbol(pair: str) -> str:
    return pair.replace("/", "")


def feather_name(pair: str) -> str:
    return pair.replace("/", "_") + "-1d.feather"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--pairs-file", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--days", type=int, default=800)
    parser.add_argument("--min-candles", type=int, default=60)
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs_file.read_text().splitlines() if p.strip()]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    end = datetime.now(timezone.utc)
    start = end - pd.Timedelta(days=args.days)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    report: list[dict[str, Any]] = []
    for i, pair in enumerate(pairs, 1):
        symbol = pair_to_symbol(pair)
        path = args.out_dir / feather_name(pair)
        status: dict[str, Any] = {
            "pair": pair,
            "symbol": symbol,
            "quote": "USDT",
            "market_type": "spot",
            "feather_path": str(path.relative_to(ROOT)),
        }
        try:
            rows = fetch_klines(args.api, symbol, start_ms, end_ms)
            df = klines_to_df(rows)
            if df.empty:
                status.update(
                    {
                        "active": False,
                        "historical_data_available": False,
                        "candle_count": 0,
                        "oldest_candle": None,
                        "newest_candle": None,
                        "missing_data_status": "no_klines_returned",
                        "included": False,
                        "exclusion_reason": "no_historical_klines",
                    }
                )
            else:
                df.to_feather(path)
                status.update(
                    {
                        "active": True,
                        "historical_data_available": len(df) >= args.min_candles,
                        "candle_count": int(len(df)),
                        "oldest_candle": df["date"].iloc[0].isoformat(),
                        "newest_candle": df["date"].iloc[-1].isoformat(),
                        "missing_data_status": (
                            "ok" if len(df) >= args.min_candles else "insufficient_history"
                        ),
                        "included": len(df) >= args.min_candles,
                        "exclusion_reason": (
                            None
                            if len(df) >= args.min_candles
                            else f"fewer_than_{args.min_candles}_daily_candles"
                        ),
                    }
                )
            print(
                f"[{i}/{len(pairs)}] {pair}: candles={status.get('candle_count', 0)} "
                f"status={status.get('missing_data_status')}"
            )
        except Exception as exc:  # noqa: BLE001 - collect per-pair failures
            status.update(
                {
                    "active": False,
                    "historical_data_available": False,
                    "candle_count": 0,
                    "oldest_candle": None,
                    "newest_candle": None,
                    "missing_data_status": f"download_error: {type(exc).__name__}: {exc}",
                    "included": False,
                    "exclusion_reason": "download_error",
                }
            )
            print(f"[{i}/{len(pairs)}] {pair}: ERROR {exc}")
        report.append(status)

    out_json = ROOT / "docs" / "binance_universe_data_availability.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_api": args.api,
        "timeframe": "1d",
        "days_requested": args.days,
        "min_candles": args.min_candles,
        "pair_count": len(pairs),
        "available_count": sum(1 for r in report if r.get("historical_data_available")),
        "rows": report,
    }
    out_json.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {out_json}")
    print(
        f"available={payload['available_count']}/{payload['pair_count']} "
        f"min_candles={args.min_candles}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
