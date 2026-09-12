#!/usr/bin/env python3
"""
Backtest suite: Score4Window baseline + 20 candidate strategies.

No live trading. No hyperopt. Uses Freqtrade backtesting only.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USER_DATA = ROOT / "user_data"
STRAT_DIR = USER_DATA / "strategies"
RESULTS_DIR = USER_DATA / "suite_results"
REPORTS = ROOT / "reports"
CONFIG = USER_DATA / "config_suite_binance5_cloudmirror.json"

STRATEGIES = [
    "Score4WindowStrategy",
    "EMATrendCrossover",
    "MACDMomentum",
    "RSIMomentum",
    "SupertrendStrategy",
    "ADXTrend",
    "TimeSeriesMomentum",
    "DonchianBreakout",
    "ATRVolatilityBreakout",
    "VolumeConfirmedBreakout",
    "BollingerBreakout",
    "TTMSqueeze",
    "TrendPullbackRetest",
    "VWAPPullback",
    "BollingerMeanReversion",
    "RSIMeanReversion",
    "ZScoreMeanReversion",
    "KeltnerChannel",
    "TrendVolume",
    "TrendMomVol",
    "MultiIndicatorConfluence",
]

# End date inclusive of available data (2026-09-12)
PERIODS: dict[str, tuple[str, str]] = {
    "A_1m": ("20260812", "20260912"),
    "B_6m": ("20260312", "20260912"),
    "C_1y": ("20250912", "20260912"),
    "D_13m": ("20250812", "20260912"),
    "E_2y": ("20240912", "20260912"),
    # F_2.5y (20240312-20260912): SKIPPED — local data starts ~2024-07-05
}

MIN_TRADES_FAIL = 5
MIN_TRADES_ACTIVE = 15
MAX_DD_FAIL = 35.0
MIN_PF_FAIL = 0.9


def period_days(period: str) -> int:
    start, end = PERIODS[period]
    return max(
        (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days,
        1,
    )


def set_risk_param(strategy: str, risk: float) -> bytes | None:
    """Write risk_pct into strategy JSON (Freqtrade load=True params)."""
    path = STRAT_DIR / f"{strategy}.json"
    backup = path.read_bytes() if path.exists() else None
    payload: dict[str, Any]
    if backup:
        try:
            payload = json.loads(backup.decode())
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {"strategy_name": strategy, "params": {}}

    # Normalize to {"params": {"buy": {...}}} while preserving other keys
    params = payload.setdefault("params", {})
    if not isinstance(params, dict):
        params = {}
        payload["params"] = params
    buy = params.setdefault("buy", {})
    if not isinstance(buy, dict):
        buy = {}
        params["buy"] = buy
    buy["risk_pct"] = float(risk)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return backup


def restore_risk_param(strategy: str, backup: bytes | None) -> None:
    path = STRAT_DIR / f"{strategy}.json"
    if backup is None:
        if path.exists():
            # Remove only files we created for candidates (Score4Window had a prior file)
            try:
                data = json.loads(path.read_text())
            except Exception:
                return
            buy = (data.get("params") or {}).get("buy") or {}
            # if file only has risk_pct, remove it
            if set(buy.keys()) <= {"risk_pct"} and len(data.get("params") or {}) <= 2:
                # keep Score4Window file always if it had more content originally
                if strategy != "Score4WindowStrategy":
                    path.unlink(missing_ok=True)
        return
    path.write_bytes(backup)


def run_backtest(strategy: str, timeframe: str, period: str, risk: float) -> dict[str, Any]:
    start, end = PERIODS[period]
    timerange = f"{start}-{end}"
    # Per-strategy result dir avoids parallel races on .last_result.json
    out_dir = RESULTS_DIR / strategy
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{strategy}__{timeframe}__{period}__r{str(risk).replace('.', 'p')}"
    note = stem

    backup = set_risk_param(strategy, risk)
    cmd = [
        "freqtrade",
        "backtesting",
        "-c",
        str(CONFIG),
        "--userdir",
        str(USER_DATA),
        "--strategy",
        strategy,
        "--timerange",
        timerange,
        "-i",
        timeframe,
        "--export",
        "trades",
        "--backtest-directory",
        str(out_dir),
        "--notes",
        note,
        "--cache",
        "none",
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        elapsed = round(time.time() - t0, 2)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-800:]
            return _error_row(strategy, timeframe, period, risk, err, elapsed)

        last = out_dir / ".last_result.json"
        if not last.exists():
            return _error_row(strategy, timeframe, period, risk, "missing .last_result.json", elapsed)
        latest_name = json.loads(last.read_text()).get("latest_backtest")
        if not latest_name:
            return _error_row(strategy, timeframe, period, risk, "empty latest_backtest", elapsed)
        result_path = out_dir / latest_name
        if not result_path.exists():
            return _error_row(strategy, timeframe, period, risk, f"missing {latest_name}", elapsed)

        # Keep original zip for load_backtest_stats; also leave a stem pointer file
        pointer = out_dir / f"{stem}.path"
        pointer.write_text(str(result_path.name) + "\n")

        return extract_metrics(result_path, strategy, timeframe, period, risk, elapsed)
    except Exception as exc:  # noqa: BLE001
        return _error_row(strategy, timeframe, period, risk, str(exc), round(time.time() - t0, 2))
    finally:
        restore_risk_param(strategy, backup)


def _error_row(strategy, timeframe, period, risk, err, elapsed) -> dict[str, Any]:
    return {
        "Strategy": strategy,
        "Timeframe": timeframe,
        "Period": period,
        "Risk": risk,
        "Trades": 0,
        "TradesPerDay": 0.0,
        "Return": 0.0,
        "MaxDrawdown": 0.0,
        "ProfitFactor": 0.0,
        "WinRate": 0.0,
        "Expectancy": 0.0,
        "Sharpe": None,
        "Sortino": None,
        "Fees": None,
        "AvgTrade": 0.0,
        "AvgDuration": "",
        "Status": "ERROR",
        "Error": err,
        "Elapsed": elapsed,
    }


def extract_metrics(
    result_path: Path,
    strategy: str,
    timeframe: str,
    period: str,
    risk: float,
    elapsed: float,
) -> dict[str, Any]:
    from freqtrade.data.btanalysis import load_backtest_stats

    stats = load_backtest_stats(result_path)
    block = stats.get("strategy", {})
    if strategy in block:
        s = block[strategy]
    elif len(block) == 1:
        s = next(iter(block.values()))
    else:
        raise KeyError(f"strategy missing in {result_path}: {list(block)}")

    trades = int(s.get("total_trades", 0) or 0)
    days = period_days(period)
    tpd = trades / days
    winrate = float(s.get("winrate", 0.0) or 0.0)
    winrate_pct = winrate * 100.0 if winrate <= 1.0 else winrate
    profit_total = float(s.get("profit_total", 0.0) or 0.0)
    profit_mean = float(s.get("profit_mean", 0.0) or 0.0)
    pf = float(s.get("profit_factor", 0.0) or 0.0)
    if pf != pf:
        pf = 0.0
    max_dd = float(s.get("max_drawdown_account", s.get("max_drawdown", 0.0)) or 0.0)
    if abs(max_dd) <= 1.5:
        max_dd *= 100.0
    sharpe = s.get("sharpe")
    sortino = s.get("sortino")
    fees = s.get("fee_total")
    if fees is None:
        fees = s.get("total_volume")  # placeholder not ideal
        fees = s.get("fee_open_avg")
    # Prefer explicit fields if present
    for key in ("fee_total", "fees", "total_fees"):
        if s.get(key) is not None:
            fees = s.get(key)
            break
    holding = s.get("holding_avg") or s.get("holding_avg_s") or ""

    row = {
        "Strategy": strategy,
        "Timeframe": timeframe,
        "Period": period,
        "Risk": risk,
        "Trades": trades,
        "TradesPerDay": round(tpd, 4),
        "Return": round(profit_total * 100.0, 4),
        "MaxDrawdown": round(float(max_dd), 4),
        "ProfitFactor": round(float(pf), 4),
        "WinRate": round(winrate_pct, 4),
        "Expectancy": round(profit_mean * 100.0, 4),
        "Sharpe": None if sharpe is None else round(float(sharpe), 4),
        "Sortino": None if sortino is None else round(float(sortino), 4),
        "Fees": None if fees is None else round(float(fees), 6),
        "AvgTrade": round(profit_mean * 100.0, 4),
        "AvgDuration": str(holding),
        "Status": "",
        "Elapsed": elapsed,
        "ResultFile": str(result_path),
    }
    row["Status"] = classify(row)
    return row


def classify(row: dict[str, Any]) -> str:
    trades = int(row["Trades"])
    exp = float(row["Expectancy"])
    pf = float(row["ProfitFactor"])
    dd = abs(float(row["MaxDrawdown"]))
    if trades < MIN_TRADES_FAIL:
        return "FAIL"
    if exp < 0 or pf < MIN_PF_FAIL or dd > MAX_DD_FAIL:
        return "FAIL"
    if trades < MIN_TRADES_ACTIVE:
        return "LOW_ACTIVITY" if exp > 0 and pf >= 1.0 else "FAIL"
    if exp > 0 and pf >= 1.1 and dd <= 25.0:
        return "ACTIVE_CANDIDATE"
    if exp > 0 and pf >= 1.0:
        return "WATCH"
    return "FAIL"


def detect_overfit(rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("Status") in ("ERROR",):
            continue
        if float(r["Risk"]) != 3.0:
            continue
        groups[(r["Strategy"], r["Timeframe"])].append(r)
    for items in groups.values():
        if len(items) < 3:
            continue
        rets = [float(x["Return"]) for x in items]
        if max(rets) > 10 and min(rets) < -5:
            for x in items:
                if x["Status"] in ("ACTIVE_CANDIDATE", "WATCH", "LOW_ACTIVITY", "STRONG_CANDIDATE"):
                    x["Status"] = "OVERFIT_RISK"


def promote_strong(rows: list[dict[str, Any]]) -> None:
    counts: Counter[str] = Counter()
    for r in rows:
        if (
            r.get("Timeframe") == "1d"
            and float(r["Risk"]) == 3.0
            and r.get("Status") == "ACTIVE_CANDIDATE"
        ):
            counts[r["Strategy"]] += 1
    strong = {s for s, n in counts.items() if n >= 3}
    for r in rows:
        if (
            r["Strategy"] in strong
            and r.get("Timeframe") == "1d"
            and float(r["Risk"]) == 3.0
            and r.get("Status") == "ACTIVE_CANDIDATE"
        ):
            r["Status"] = "STRONG_CANDIDATE"


def build_jobs(mode: str) -> list[tuple[str, str, str, float]]:
    jobs: list[tuple[str, str, str, float]] = []
    if mode == "smoke":
        for s in STRATEGIES[:2]:
            jobs.append((s, "1d", "B_6m", 3.0))
        return jobs

    # primary: all strategies × all periods × 1d × risk 3
    if mode in ("primary", "full"):
        for s in STRATEGIES:
            for p in PERIODS:
                jobs.append((s, "1d", p, 3.0))

    # risk sweep on 1y / 1d
    if mode in ("risk", "full"):
        for s in STRATEGIES:
            for risk in (2.0, 5.0):
                jobs.append((s, "1d", "C_1y", risk))
            if mode == "risk":
                jobs.append((s, "1d", "C_1y", 3.0))

    # timeframe sweep risk=3 on B/C/E
    if mode in ("tf", "full"):
        for s in STRATEGIES:
            for p in ("B_6m", "C_1y", "E_2y"):
                for tf in ("4h", "1h"):
                    jobs.append((s, tf, p, 3.0))
            if mode == "tf":
                jobs.append((s, "1d", "C_1y", 3.0))

    # dedupe
    seen: set[tuple] = set()
    out: list[tuple[str, str, str, float]] = []
    for j in jobs:
        if j not in seen:
            seen.add(j)
            out.append(j)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.get("Status") != "ERROR":
            by[r["Strategy"]].append(r)
    out = []
    for strat, items in by.items():
        core = [x for x in items if x["Timeframe"] == "1d" and float(x["Risk"]) == 3.0]
        use = core or items

        def avg(key: str) -> float:
            vals = [float(x[key]) for x in use if x.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else 0.0

        statuses = [x["Status"] for x in use]
        status = "FAIL"
        for pref in (
            "STRONG_CANDIDATE",
            "ACTIVE_CANDIDATE",
            "WATCH",
            "LOW_ACTIVITY",
            "OVERFIT_RISK",
            "FAIL",
        ):
            if pref in statuses:
                status = pref
                break
        tf_rows = [x for x in items if float(x["Risk"]) == 3.0]
        best_tf = ""
        if tf_rows:
            best_tf = max(
                tf_rows,
                key=lambda x: (float(x["Sharpe"] or -999), float(x["ProfitFactor"] or 0)),
            )["Timeframe"]
        out.append(
            {
                "Strategy": strat,
                "Status": status,
                "AvgReturn_1d_r3": avg("Return"),
                "AvgMaxDD_1d_r3": avg("MaxDrawdown"),
                "AvgPF_1d_r3": avg("ProfitFactor"),
                "AvgExpectancy_1d_r3": avg("Expectancy"),
                "AvgTrades_1d_r3": avg("Trades"),
                "AvgTradesPerDay_1d_r3": avg("TradesPerDay"),
                "AvgSharpe_1d_r3": avg("Sharpe"),
                "AvgSortino_1d_r3": avg("Sortino"),
                "BestTimeframe": best_tf,
                "NRuns": len(items),
            }
        )
    out.sort(
        key=lambda x: (
            x["Status"] != "STRONG_CANDIDATE",
            x["Status"] != "ACTIVE_CANDIDATE",
            -float(x["AvgSharpe_1d_r3"]),
        )
    )
    return out


def _best(items: list[dict[str, Any]], key: str, higher: bool = True):
    items = [x for x in items if int(x.get("Trades") or 0) >= MIN_TRADES_FAIL]
    if not items:
        return None
    return (max if higher else min)(items, key=lambda x: float(x.get(key) or 0))


def composite(r: dict[str, Any]) -> float:
    return (
        float(r.get("Sharpe") or 0)
        + 0.3 * float(r.get("ProfitFactor") or 0)
        - 0.03 * abs(float(r.get("MaxDrawdown") or 0))
        + 0.05 * float(r.get("Expectancy") or 0)
        + 0.02 * min(float(r.get("TradesPerDay") or 0) * 10, 3)
    )


def rankings(rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> dict[str, Any]:
    core = [
        r
        for r in rows
        if r.get("Timeframe") == "1d" and float(r["Risk"]) == 3.0 and r.get("Status") != "ERROR"
    ]
    by_period = {p: [r for r in core if r["Period"] == p] for p in PERIODS}
    c_1y = by_period.get("C_1y", [])

    qa = [
        x
        for x in core
        if float(x.get("Expectancy") or 0) > 0
        and float(x.get("ProfitFactor") or 0) >= 1.0
        and int(x.get("Trades") or 0) >= MIN_TRADES_ACTIVE
    ]
    most_active = max(qa, key=lambda x: float(x["TradesPerDay"])) if qa else None

    baseline = [r for r in c_1y if r["Strategy"] == "Score4WindowStrategy"]
    alts = [r for r in c_1y if r["Strategy"] != "Score4WindowStrategy"]
    best_alt = max(alts, key=composite) if alts else None

    strong_counts: Counter[str] = Counter()
    for r in core:
        if r.get("Status") in ("ACTIVE_CANDIDATE", "STRONG_CANDIDATE"):
            strong_counts[r["Strategy"]] += 1

    return {
        "BEST_OVERALL": max(c_1y, key=composite) if c_1y else None,
        "BEST_SHORT_TERM": _best(by_period.get("A_1m", []), "Sharpe"),
        "BEST_MEDIUM_TERM": _best(by_period.get("B_6m", []) + by_period.get("C_1y", []), "Sharpe"),
        "BEST_LONG_TERM": _best(by_period.get("E_2y", []), "Sharpe"),
        "MOST_ACTIVE_QUALITY": most_active,
        "LOWEST_DRAWDOWN": _best(c_1y, "MaxDrawdown", higher=False),
        "BEST_PROFIT_FACTOR": _best(c_1y, "ProfitFactor"),
        "BEST_RISK_REWARD": _best(c_1y, "Sortino"),
        "BEST_ROBUSTNESS": [{"Strategy": s, "ActivePeriods": n} for s, n in strong_counts.most_common(5)],
        "SCORE4WINDOW_VS_BEST_ALT": {
            "baseline": baseline[0] if baseline else None,
            "best_alt": best_alt,
        },
        "summaries_top": summaries[:10],
        "notes": {
            "period_F_skipped": "Local Binance OHLCV starts ~2024-07-05; F(2024-03-12) insufficient",
            "timeframes_5m_15m": "Not present locally; downloaded/tested 1h + 4h + existing 1d",
            "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
            "risk_model": "size_pct=risk_pct/atr_pct (Score4Window multiplies by score); ROI10%/SL-10%",
            "hyperopt": "not run in this phase",
        },
    }


def run_strat_jobs(jobs: list[tuple[str, str, str, float]]) -> list[dict[str, Any]]:
    out = []
    for strategy, tf, period, risk in jobs:
        print(f"  -> {strategy} {tf} {period} r={risk}", flush=True)
        out.append(run_backtest(strategy, tf, period, risk))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="primary", choices=["smoke", "primary", "risk", "tf", "full"])
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    if not CONFIG.exists():
        print("Missing", CONFIG)
        return 1

    jobs = build_jobs(args.mode)
    print(f"Jobs={len(jobs)} mode={args.mode} workers={args.workers}")

    # Group by strategy so param JSON is not raced
    by_strat: dict[str, list[tuple]] = defaultdict(list)
    for j in jobs:
        by_strat[j[0]].append(j)

    rows: list[dict[str, Any]] = []
    strat_items = list(by_strat.items())
    if args.workers <= 1:
        for strat, js in strat_items:
            print(f"=== {strat} ({len(js)}) ===", flush=True)
            rows.extend(run_strat_jobs(js))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_strat_jobs, js): strat for strat, js in strat_items}
            done = 0
            for fut in as_completed(futs):
                strat = futs[fut]
                part = fut.result()
                rows.extend(part)
                done += 1
                print(f"done {done}/{len(futs)} ({strat})", flush=True)

    detect_overfit(rows)
    promote_strong(rows)

    fields = [
        "Strategy",
        "Timeframe",
        "Period",
        "Risk",
        "Trades",
        "TradesPerDay",
        "Return",
        "MaxDrawdown",
        "ProfitFactor",
        "WinRate",
        "Expectancy",
        "Sharpe",
        "Sortino",
        "Fees",
        "AvgTrade",
        "AvgDuration",
        "Status",
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv(REPORTS / "strategy_backtest_results.csv", rows, fields)

    summaries = summarize(rows)
    write_csv(
        REPORTS / "strategy_summary.csv",
        summaries,
        list(summaries[0].keys()) if summaries else ["Strategy"],
    )

    # also user-requested names
    write_csv(REPORTS / "strategy_backtest_results.csv", rows, fields)
    write_csv(ROOT / "strategy_backtest_results.csv", rows, fields)
    write_csv(ROOT / "strategy_summary.csv", summaries, list(summaries[0].keys()) if summaries else ["Strategy"])

    rank = rankings(rows, summaries)

    def scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        return obj

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "n_jobs": len(jobs),
        "n_ok": sum(1 for r in rows if r.get("Status") != "ERROR"),
        "n_error": sum(1 for r in rows if r.get("Status") == "ERROR"),
        "rankings": scrub(rank),
        "decisions": {
            "period_F": "SKIPPED_INSUFFICIENT_DATA",
            "pairs": 5,
            "config": CONFIG.name,
            "timeframes_tested": sorted({r.get("Timeframe") for r in rows}),
        },
    }
    (REPORTS / "strategy_suite_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")

    lines = [
        "# Strategy Suite Report",
        "",
        f"Jobs: {len(jobs)} | OK: {report['n_ok']} | ERR: {report['n_error']}",
        "",
    ]
    for key in [
        "BEST_OVERALL",
        "BEST_SHORT_TERM",
        "BEST_MEDIUM_TERM",
        "BEST_LONG_TERM",
        "MOST_ACTIVE_QUALITY",
        "LOWEST_DRAWDOWN",
        "BEST_PROFIT_FACTOR",
        "BEST_RISK_REWARD",
    ]:
        row = rank.get(key)
        lines.append(f"## {key}")
        if not row:
            lines.append("n/a")
        else:
            lines.append(
                f"- {row.get('Strategy')} | TF={row.get('Timeframe')} | {row.get('Period')} | "
                f"Ret={row.get('Return')} DD={row.get('MaxDrawdown')} PF={row.get('ProfitFactor')} "
                f"Exp={row.get('Expectancy')} Sharpe={row.get('Sharpe')} Trades={row.get('Trades')} "
                f"Status={row.get('Status')}"
            )
        lines.append("")
    lines.append("## SCORE4WINDOW VS BEST ALT (C_1y 1d r3)")
    vs = rank.get("SCORE4WINDOW_VS_BEST_ALT") or {}
    for label in ("baseline", "best_alt"):
        row = vs.get(label)
        if row:
            lines.append(
                f"- {label}: {row.get('Strategy')} Ret={row.get('Return')} DD={row.get('MaxDrawdown')} "
                f"PF={row.get('ProfitFactor')} Sharpe={row.get('Sharpe')} Trades={row.get('Trades')}"
            )
    lines.append("")
    lines.append("## Robustness")
    for item in rank.get("BEST_ROBUSTNESS") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Notes")
    for k, v in (rank.get("notes") or {}).items():
        lines.append(f"- **{k}**: {v}")
    (REPORTS / "strategy_suite_report.md").write_text("\n".join(lines) + "\n")

    print("Wrote reports to", REPORTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
