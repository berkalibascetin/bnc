"""
Score scan engine — observation / reporting only.

Uses Score4WindowStrategy.populate_indicators (authoritative) so scanner scores
match live strategy calculations. Never sends orders.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from score_scan import normalize_mode
from score_scan.reporting import write_reports

logger = logging.getLogger(__name__)

# Process-wide lock: at most one scan at a time.
_SCAN_LOCK = threading.Lock()
_LAST_HOURLY_KEY: str | None = None


@dataclass
class ScanResultRow:
    pair: str
    status: str = "ok"  # ok | insufficient_data | error
    rank: int | None = None
    score: float | None = None
    signal: str | None = None
    candle_timestamp: str | None = None
    score_1w: float | None = None
    score_2w: float | None = None
    score_1m: float | None = None
    score_2m: float | None = None
    reason: str | None = None


@dataclass
class ScanReport:
    mode: str
    timeframe: str
    timestamp: str
    pair_count: int
    results: list[ScanResultRow] = field(default_factory=list)
    dry_run: bool = True
    entry_score_threshold: int = 2
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        ok = [r for r in self.results if r.status == "ok"]
        insuff = [r for r in self.results if r.status == "insufficient_data"]
        errs = [r for r in self.results if r.status == "error"]
        scores = [float(r.score) for r in ok if r.score is not None]
        dist: dict[str, int] = {}
        for s in scores:
            key = str(int(s)) if float(s).is_integer() else str(s)
            dist[key] = dist.get(key, 0) + 1
        from score4window_scoring import (
            SIGNAL_BUY,
            SIGNAL_HOLD,
            SIGNAL_SELL,
            SIGNAL_STRONG_BUY,
            SIGNAL_STRONG_SELL,
        )

        def _pairs(label: str) -> list[str]:
            return [r.pair for r in ok if r.signal == label]

        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "timeframe": self.timeframe,
            "pair_count": self.pair_count,
            "dry_run": self.dry_run,
            "entry_score_threshold": self.entry_score_threshold,
            "summary": {
                "scored": len(ok),
                "insufficient_data": len(insuff),
                "error": len(errs),
                "max_score": max(scores) if scores else None,
                "min_score": min(scores) if scores else None,
                "score_distribution": dist,
                "strong_buy_signals": _pairs(SIGNAL_STRONG_BUY),
                "buy_signals": _pairs(SIGNAL_BUY),
                "hold_signals": _pairs(SIGNAL_HOLD),
                "sell_signals": _pairs(SIGNAL_SELL),
                "strong_sell_signals": _pairs(SIGNAL_STRONG_SELL),
            },
            "results": [
                {
                    "rank": r.rank,
                    "pair": r.pair,
                    "score": r.score,
                    "signal": r.signal,
                    "candle_timestamp": r.candle_timestamp,
                    "score_1w": r.score_1w,
                    "score_2w": r.score_2w,
                    "score_1m": r.score_1m,
                    "score_2m": r.score_2m,
                    "status": r.status,
                    "reason": r.reason,
                }
                for r in self.results
            ],
            "errors": self.errors,
        }


def assert_dry_run_safe(config: dict[str, Any]) -> None:
    """Refuse to operate if config would allow live trading."""
    if config.get("dry_run") is not True:
        raise RuntimeError(
            "score_scan safety abort: dry_run must be true (got "
            f"{config.get('dry_run')!r}). Scanner will not run."
        )


def _hour_key(now: datetime | None = None) -> str:
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y%m%d%H")


def _load_ohlcv_for_pair(strategy: Any, pair: str, timeframe: str) -> pd.DataFrame | None:
    """Prefer DataProvider; fall back to local datadir feathers."""
    dp = getattr(strategy, "dp", None)
    if dp is not None:
        try:
            df = dp.get_pair_dataframe(pair, timeframe)
            if df is not None and not df.empty:
                return df.copy()
        except Exception as exc:  # noqa: BLE001
            logger.warning("score_scan: dp load failed for %s: %s", pair, exc)

    # Disk fallback (same OHLCV the bot uses offline)
    try:
        config = getattr(strategy, "config", {}) or {}
        datadir = config.get("datadir")
        if datadir is None:
            userdir = config.get("user_data_dir")
            exchange = (config.get("exchange") or {}).get("name") or "binance"
            if userdir:
                datadir = Path(userdir) / "data" / exchange
        if datadir is None:
            return None
        datadir = Path(datadir)
        # Freqtrade feather naming: BTC_USDT-1d.feather
        stem = pair.replace("/", "_").replace(":", "_")
        path = datadir / f"{stem}-{timeframe}.feather"
        if not path.exists():
            # alternate hyphen style
            path = datadir / f"{pair.replace('/', '_')}-{timeframe}.feather"
        if not path.exists():
            return None
        df = pd.read_feather(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=True)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("score_scan: disk load failed for %s: %s", pair, exc)
        return None


def _score_one(
    strategy: Any,
    pair: str,
    dataframe: pd.DataFrame | None,
    *,
    entry_threshold: int,
    min_candles: int,
) -> ScanResultRow:
    import sys
    from pathlib import Path as _Path
    _strat_dir = str(_Path(__file__).resolve().parents[1] / "user_data" / "strategies")
    if _strat_dir not in sys.path:
        sys.path.insert(0, _strat_dir)
    from score4window_scoring import signal_from_score

    if dataframe is None or dataframe.empty:
        return ScanResultRow(
            pair=pair,
            status="insufficient_data",
            reason="no_ohlcv",
        )
    if len(dataframe) < min_candles:
        return ScanResultRow(
            pair=pair,
            status="insufficient_data",
            reason=f"need>={min_candles}_candles_have_{len(dataframe)}",
        )
    try:
        meta = {"pair": pair}
        scored = strategy.populate_indicators(dataframe.copy(), meta)
        last = scored.iloc[-1]
        total = last.get("total_score")
        if total is None or (isinstance(total, float) and pd.isna(total)):
            return ScanResultRow(
                pair=pair,
                status="insufficient_data",
                reason="total_score_nan",
            )
        score_f = float(total)
        candle_ts = last.get("date")
        if hasattr(candle_ts, "isoformat"):
            candle_ts = candle_ts.isoformat()
        else:
            candle_ts = str(candle_ts) if candle_ts is not None else None

        def _comp(name: str) -> float | None:
            v = last.get(name)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            return float(v)

        return ScanResultRow(
            pair=pair,
            status="ok",
            score=score_f,
            signal=signal_from_score(score_f, entry_threshold=entry_threshold),
            candle_timestamp=candle_ts,
            score_1w=_comp("score_1w"),
            score_2w=_comp("score_2w"),
            score_1m=_comp("score_1m"),
            score_2m=_comp("score_2m"),
        )
    except Exception as exc:  # noqa: BLE001
        return ScanResultRow(pair=pair, status="error", reason=str(exc))


def run_score_scan(
    strategy: Any,
    config: dict[str, Any],
    *,
    mode: str,
    pairs: list[str] | None = None,
    reports_dir: Path | None = None,
    print_table: bool = True,
    now: datetime | None = None,
) -> ScanReport | None:
    """
    Run one observation scan. Returns None if skipped (hourly already done / lock busy).
    Never raises into the bot loop for per-pair failures.
    """
    global _LAST_HOURLY_KEY

    mode = normalize_mode(mode)
    if mode == "off":
        return None

    try:
        assert_dry_run_safe(config)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return None

    if mode == "hourly":
        key = _hour_key(now)
        if _LAST_HOURLY_KEY == key:
            logger.info("score_scan hourly: already ran for hour %s — skip", key)
            return None

    # Non-blocking: if a scan is already running, skip.
    acquired = _SCAN_LOCK.acquire(blocking=False)
    if not acquired:
        logger.warning("score_scan: another scan in progress — skip")
        return None

    try:
        if mode == "hourly":
            key = _hour_key(now)
            if _LAST_HOURLY_KEY == key:
                return None

        timeframe = str(config.get("timeframe") or getattr(strategy, "timeframe", "1d"))
        pair_list = list(pairs or config.get("exchange", {}).get("pair_whitelist") or config.get("exchange", {}).get("pair_whitelist") or [])
        if not pair_list and hasattr(strategy, "dp") and strategy.dp is not None:
            try:
                pair_list = list(strategy.dp.current_whitelist())
            except Exception:  # noqa: BLE001
                pair_list = []

        entry_threshold = int(getattr(strategy.entry_score_threshold, "value", 2))
        window_2m = int(getattr(strategy.window_2m, "value", 42))
        min_candles = window_2m + 1

        ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        report = ScanReport(
            mode=mode,
            timeframe=timeframe,
            timestamp=ts,
            pair_count=len(pair_list),
            dry_run=bool(config.get("dry_run")),
            entry_score_threshold=entry_threshold,
        )

        rows: list[ScanResultRow] = []
        for pair in pair_list:
            df = _load_ohlcv_for_pair(strategy, pair, timeframe)
            rows.append(
                _score_one(
                    strategy,
                    pair,
                    df,
                    entry_threshold=entry_threshold,
                    min_candles=min_candles,
                )
            )

        # Sort: ok rows by score desc, then insufficient/error at end (stable by pair)
        ok_rows = [r for r in rows if r.status == "ok"]
        other_rows = [r for r in rows if r.status != "ok"]
        ok_rows.sort(key=lambda r: (-(r.score or -999), r.pair))
        for i, r in enumerate(ok_rows, start=1):
            r.rank = i
        report.results = ok_rows + other_rows

        # Guarantee every whitelist pair is represented
        seen = {r.pair for r in report.results}
        for pair in pair_list:
            if pair not in seen:
                report.results.append(
                    ScanResultRow(pair=pair, status="error", reason="missing_from_results")
                )

        out_dir = Path(reports_dir) if reports_dir else Path("reports")
        try:
            write_reports(report, out_dir)
        except Exception as exc:
            report.errors.append(f"report_write_failed: {exc}")
            logger.exception("score_scan: failed writing reports")

        if print_table:
            _print_terminal(report)

        if mode == "hourly":
            _LAST_HOURLY_KEY = _hour_key(now)

        return report
    except Exception:
        logger.exception("score_scan: scan failed (bot continues)")
        return None
    finally:
        _SCAN_LOCK.release()


def reset_hourly_state_for_tests() -> None:
    """Test helper — clear hourly dedupe + do not touch strategy state."""
    global _LAST_HOURLY_KEY
    _LAST_HOURLY_KEY = None


def _print_terminal(report: ScanReport) -> None:
    title = "FORCE" if report.mode == "force" else report.mode.upper()
    lines = [
        "",
        "==================================================",
        f"SCORE SCAN — {title}",
        f"Timestamp: {report.timestamp}",
        f"Pairs scanned: {report.pair_count}",
        f"dry_run: {report.dry_run}",
        "==================================================",
        "",
        f"{'Rank':<5} {'Pair':<14} {'Score':>6}  {'Signal':<14} Status",
    ]
    for r in report.results:
        if r.status == "ok":
            lines.append(
                f"{(r.rank or '-'):<5} {r.pair:<14} {r.score:>6.0f}  {(r.signal or ''):<14} ok"
            )
        else:
            lines.append(
                f"{'-':<5} {r.pair:<14} {'n/a':>6}  {'-':<14} {r.status}"
                + (f" ({r.reason})" if r.reason else "")
            )
    summary = report.to_dict()["summary"]
    lines.extend(
        [
            "",
            (
                f"scored={summary['scored']} insufficient={summary['insufficient_data']} "
                f"error={summary['error']} max_score={summary['max_score']} "
                f"min_score={summary['min_score']}"
            ),
            f"güçlü alım(+4)={summary['strong_buy_signals']}",
            f"alım(+2)={summary['buy_signals']}",
            f"sell(-2)={summary['sell_signals']}",
            f"hızlıca sell(-4)={summary['strong_sell_signals']}",
            "",
        ]
    )
    print("\n".join(lines), flush=True)
