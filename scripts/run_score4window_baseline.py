#!/usr/bin/env python3
"""
Score4WindowStrategy baseline runner (SCORE_4WINDOW_V1).

Compares entry_score_threshold in {1,2,3,4} without permanently changing
strategy defaults. Uses temporary Score4WindowStrategy.json overrides,
then restores prior file state (and leaves default threshold=2).

Also groups trades by enter_tag score_1..score_4 (from a threshold=1 run)
to ask whether higher scores improve quality.

No hyperopt. No Fibonacci / volatility / volume filters.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USER_DATA = ROOT / "user_data"
STRATEGY_DIR = USER_DATA / "strategies"
PARAMS_FILE = STRATEGY_DIR / "Score4WindowStrategy.json"
RESULTS_DIR = USER_DATA / "baseline_results"
REPORTS_DIR = ROOT / "reports"
DEFAULT_TIMERANGE = "20260301-20260901"
DEFAULT_TIMEFRAME = "1d"
DEFAULT_THRESHOLDS = (1, 2, 3, 4)
STRATEGY_NAME = "Score4WindowStrategy"


def write_params(threshold: int) -> None:
    payload = {
        "strategy_name": STRATEGY_NAME,
        "params": {
            "buy": {
                "window_1w": 5,
                "window_2w": 10,
                "window_1m": 21,
                "window_2m": 42,
                "entry_score_threshold": int(threshold),
            }
        },
        "ft_stratparam_v": 1,
        "export_time": datetime.now(timezone.utc).isoformat(),
    }
    PARAMS_FILE.write_text(json.dumps(payload, indent=2) + "\n")


def backup_params() -> bytes | None:
    if PARAMS_FILE.exists():
        return PARAMS_FILE.read_bytes()
    return None


def restore_params(backup: bytes | None) -> None:
    if backup is None:
        if PARAMS_FILE.exists():
            PARAMS_FILE.unlink()
    else:
        PARAMS_FILE.write_bytes(backup)


def run_cmd(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def download_data(config: Path, pairs: list[str], days: int) -> None:
    run_cmd(
        [
            "freqtrade",
            "download-data",
            "-c",
            str(config),
            "--userdir",
            str(USER_DATA),
            "--timeframe",
            DEFAULT_TIMEFRAME,
            "--days",
            str(days),
            "-p",
            *pairs,
        ]
    )


def run_backtest(
    config: Path,
    threshold: int,
    timerange: str,
    export_stem: str,
) -> Path:
    write_params(threshold)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / export_stem
    run_cmd(
        [
            "freqtrade",
            "backtesting",
            "-c",
            str(config),
            "--userdir",
            str(USER_DATA),
            "--strategy",
            STRATEGY_NAME,
            "--timerange",
            timerange,
            "-i",
            DEFAULT_TIMEFRAME,
            "--export",
            "trades",
            "--backtest-directory",
            str(RESULTS_DIR),
            "--export-filename",
            str(out),
            "--cache",
            "none",
        ]
    )
    candidates = sorted(RESULTS_DIR.glob(f"{export_stem}*"), reverse=True)
    if not candidates:
        candidates = sorted(RESULTS_DIR.glob("backtest-result-*"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No backtest result found for {export_stem}")
    return candidates[0]


def load_stats(result_path: Path) -> dict[str, Any]:
    from freqtrade.data.btanalysis import load_backtest_stats

    return load_backtest_stats(result_path)


def strategy_block(stats: dict[str, Any]) -> dict[str, Any]:
    strat = stats.get("strategy", {})
    if STRATEGY_NAME in strat:
        return strat[STRATEGY_NAME]
    if len(strat) == 1:
        return next(iter(strat.values()))
    raise KeyError(f"Strategy block not found in stats keys={list(strat)}")


def extract_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    s = strategy_block(stats)
    total_trades = int(s.get("total_trades", 0) or 0)
    wins = int(s.get("wins", 0) or 0)
    losses = int(s.get("losses", 0) or 0)
    draws = int(s.get("draws", 0) or 0)
    winrate = float(s.get("winrate", 0.0) or 0.0)
    winrate_pct = winrate * 100.0 if winrate <= 1.0 else winrate

    profit_total = float(s.get("profit_total", 0.0) or 0.0)
    profit_total_abs = float(s.get("profit_total_abs", 0.0) or 0.0)
    profit_mean = float(s.get("profit_mean", 0.0) or 0.0)
    profit_factor = float(s.get("profit_factor", 0.0) or 0.0)
    if profit_factor != profit_factor:  # NaN
        profit_factor = 0.0

    max_dd_abs = float(s.get("max_drawdown_abs", 0.0) or 0.0)
    max_dd_pct = float(s.get("max_drawdown_account", s.get("max_drawdown", 0.0)) or 0.0)
    if abs(max_dd_pct) <= 1.5:
        max_dd_pct = max_dd_pct * 100.0

    sharpe = s.get("sharpe")
    sortino = s.get("sortino")

    return {
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "draws": draws,
        "win_rate_pct": round(winrate_pct, 4),
        "total_profit_abs": round(profit_total_abs, 4),
        "profit_pct": round(profit_total * 100.0, 4),
        "average_trade_pct": round(profit_mean * 100.0, 4),
        "profit_factor": round(float(profit_factor), 4),
        "max_drawdown_abs": round(max_dd_abs, 4),
        "max_drawdown_pct": round(float(max_dd_pct), 4),
        "sharpe": None if sharpe is None else round(float(sharpe), 4),
        "sortino": None if sortino is None else round(float(sortino), 4),
    }


def analyze_score_tags(stats: dict[str, Any]) -> dict[str, Any]:
    s = strategy_block(stats)
    trades = s.get("trades") or []
    buckets: dict[str, list[float]] = {f"score_{i}": [] for i in range(1, 5)}
    for t in trades:
        tag = str(t.get("enter_tag") or t.get("buy_tag") or "")
        profit = float(t.get("profit_ratio", 0.0) or 0.0)
        if tag in buckets:
            buckets[tag].append(profit)
        elif tag.startswith("score_"):
            buckets.setdefault(tag, []).append(profit)

    out: dict[str, Any] = {}
    for tag, profits in sorted(buckets.items()):
        n = len(profits)
        if n == 0:
            out[tag] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": None,
                "avg_profit_pct": None,
                "total_profit_pct": None,
            }
            continue
        wins = sum(1 for p in profits if p > 0)
        losses = sum(1 for p in profits if p < 0)
        out[tag] = {
            "trades": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(100.0 * wins / n, 4),
            "avg_profit_pct": round(100.0 * sum(profits) / n, 4),
            "total_profit_pct": round(100.0 * sum(profits), 4),
        }
    return out


def significance_note(total_trades: int) -> str:
    if total_trades < 20:
        return (
            "INSUFFICIENT_SAMPLE: trade count too low for statistical confidence; "
            "treat metrics as exploratory only."
        )
    if total_trades < 50:
        return "LOW_SAMPLE: directional at best; do not claim robustness."
    return "MODERATE_SAMPLE: still limited; out-of-sample / walk-forward required next."


def decide_verdict(
    threshold_rows: list[dict[str, Any]],
    score_dist: dict[str, Any] | None,
    multi_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    richest_btc = max((r["total_trades"] for r in threshold_rows), default=0)
    multi_th1 = next((r["total_trades"] for r in multi_rows if r["threshold"] == 1), 0)
    sample_proxy = max(richest_btc, multi_th1)

    monotone = None
    if score_dist:
        avgs = []
        for i in range(1, 5):
            cell = score_dist.get(f"score_{i}") or {}
            if cell.get("trades"):
                avgs.append((i, cell.get("avg_profit_pct"), cell.get("trades")))
        if len(avgs) >= 2:
            monotone = (
                avgs[-1][1] is not None
                and avgs[0][1] is not None
                and avgs[-1][1] > avgs[0][1]
            )

    if sample_proxy < 30:
        decision = "data_insufficient"
        rationale = (
            f"Only ~{sample_proxy} trades in the richest comparable run; "
            "cannot claim the 4-window score system works or fails."
        )
    elif monotone is True:
        decision = "promising_but_unproven"
        rationale = (
            "Higher enter_tag scores show better average profit in-sample, "
            "but sample size is still limited — needs longer history / OOS."
        )
    elif monotone is False:
        decision = "weak_in_sample"
        rationale = (
            "Higher scores do not clearly outperform lower scores in-sample; "
            "score system looks weak on this window."
        )
    else:
        decision = "data_insufficient"
        rationale = "Not enough tagged trades per score bucket to judge quality gradient."

    return {
        "decision": decision,
        "rationale": rationale,
        "sample_proxy_trades": sample_proxy,
        "higher_score_better_in_sample": monotone,
    }


def print_summary(report: dict[str, Any]) -> None:
    print("\n=== Threshold comparison (BTC/USDT) ===")
    for row in report["threshold_comparison_btc"]:
        print(
            f"th={row['threshold']}: trades={row['total_trades']} "
            f"win%={row['win_rate_pct']} profit%={row['profit_pct']} "
            f"PF={row['profit_factor']} DD%={row['max_drawdown_pct']} "
            f"Sharpe={row['sharpe']} Sortino={row['sortino']}"
        )
    print("\n=== Score distribution (BTC, threshold=1 entries) ===")
    print(json.dumps(report.get("score_distribution_btc_threshold1"), indent=2))
    print("\n=== Multi-pair ===")
    for row in report["multi_pair_results"]:
        print(
            f"th={row['threshold']}: trades={row['total_trades']} "
            f"win%={row['win_rate_pct']} profit%={row['profit_pct']} "
            f"PF={row['profit_factor']} DD%={row['max_drawdown_pct']}"
        )
    print("\n=== Verdict ===")
    print(json.dumps(report["verdict"], indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=USER_DATA / "config_baseline.json",
    )
    parser.add_argument(
        "--btc-config",
        type=Path,
        default=USER_DATA / "config.json",
    )
    parser.add_argument("--timerange", default=DEFAULT_TIMERANGE)
    parser.add_argument("--days", type=int, default=220)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--thresholds",
        type=int,
        nargs="+",
        default=list(DEFAULT_THRESHOLDS),
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    backup = backup_params()

    try:
        btc_pairs = ["BTC/USDT"]
        multi_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]

        if not args.skip_download:
            download_data(args.btc_config, btc_pairs, args.days)
            download_data(args.config, multi_pairs, args.days)

        threshold_rows: list[dict[str, Any]] = []
        score_dist: dict[str, Any] | None = None
        result_files: dict[str, str] = {}

        for th in args.thresholds:
            stem = f"baseline_btc_th{th}"
            result_path = run_backtest(args.btc_config, th, args.timerange, stem)
            result_files[f"btc_th{th}"] = str(result_path)
            stats = load_stats(result_path)
            metrics = extract_metrics(stats)
            row = {"threshold": th, "universe": "BTC/USDT", **metrics}
            row["significance"] = significance_note(metrics["total_trades"])
            threshold_rows.append(row)
            if th == 1:
                score_dist = analyze_score_tags(stats)

        multi_rows: list[dict[str, Any]] = []
        multi_score_dist: dict[str, Any] | None = None
        for th in (1, 2):
            stem = f"baseline_multi_th{th}"
            result_path = run_backtest(args.config, th, args.timerange, stem)
            result_files[f"multi_th{th}"] = str(result_path)
            stats = load_stats(result_path)
            metrics = extract_metrics(stats)
            row = {
                "threshold": th,
                "universe": ",".join(multi_pairs),
                **metrics,
            }
            row["significance"] = significance_note(metrics["total_trades"])
            multi_rows.append(row)
            if th == 1:
                multi_score_dist = analyze_score_tags(stats)

        # Leave defaults at threshold=2 for normal use
        write_params(2)

        verdict = decide_verdict(threshold_rows, score_dist, multi_rows)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timerange": args.timerange,
            "timeframe": DEFAULT_TIMEFRAME,
            "strategy": STRATEGY_NAME,
            "strategy_id": "SCORE_4WINDOW_V1",
            "result_files": result_files,
            "threshold_comparison_btc": threshold_rows,
            "score_distribution_btc_threshold1": score_dist,
            "multi_pair_results": multi_rows,
            "score_distribution_multi_threshold1": multi_score_dist,
            "verdict": verdict,
            "notes": [
                "Default strategy threshold remains 2 after this run.",
                "No hyperopt, Fibonacci, volatility, volume, VWAP, or news filters.",
                "Lookahead: strategy uses only shift(+N).",
            ],
        }
        out_json = REPORTS_DIR / "score4window_baseline_report.json"
        out_json.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"Wrote {out_json}")
        print_summary(report)
        return 0
    finally:
        if backup is not None and not PARAMS_FILE.exists():
            restore_params(backup)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with {exc.returncode}", file=sys.stderr)
        raise
