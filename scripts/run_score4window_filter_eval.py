#!/usr/bin/env python3
"""
A/B filter evaluation for Score4WindowStrategy.

Compares baseline (all filters OFF) vs each filter enabled alone.
Does not permanently change strategy defaults (threshold=2, filters off).

Periods:
  - full:    20240912-20260912
  - period1: 20240912-20250912
  - period2: 20250912-20260912

Universe: BTC/ETH/SOL/BNB/XRP on Gate.io (1d).
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
RESULTS_DIR = USER_DATA / "filter_results"
REPORTS_DIR = ROOT / "reports"
STRATEGY_NAME = "Score4WindowStrategy"
CONFIG = USER_DATA / "config_baseline.json"
TIMEFRAME = "1d"

FILTER_MODES: dict[str, dict[str, Any]] = {
    "baseline": {},
    "volume": {"enable_volume_filter": 1},
    "momentum": {"enable_momentum_filter": 1},
    "breakout": {"enable_breakout_filter": 1},
    "retest": {"enable_retest_filter": 1},
    "volatility": {"enable_volatility_filter": 1},
    "fibonacci": {"enable_fibonacci_filter": 1},
}

PERIODS: dict[str, str] = {
    "full": "20240912-20260912",
    "period1": "20240912-20250912",
    "period2": "20250912-20260912",
}

BASE_BUY_PARAMS: dict[str, Any] = {
    "window_1w": 5,
    "window_2w": 10,
    "window_1m": 21,
    "window_2m": 42,
    "entry_score_threshold": 2,
    "enable_volume_filter": 0,
    "enable_momentum_filter": 0,
    "enable_breakout_filter": 0,
    "enable_retest_filter": 0,
    "enable_volatility_filter": 0,
    "enable_fibonacci_filter": 0,
    "volume_ma_period": 20,
    "volume_mult": 1.5,
    "rsi_period": 14,
    "rsi_min": 50,
    "breakout_lookback": 20,
    "retest_lookback": 20,
    "retest_tol_pct": 1.0,
    "atr_period": 14,
    "atr_min_pct": 1.0,
    "fib_lookback": 55,
}

METRIC_KEYS = (
    "total_trades",
    "win_rate_pct",
    "profit_pct",
    "average_trade_pct",
    "profit_factor",
    "max_drawdown_pct",
)


def set_params(overrides: dict[str, Any]) -> None:
    buy = dict(BASE_BUY_PARAMS)
    buy.update(overrides)
    payload = {
        "strategy_name": STRATEGY_NAME,
        "params": {"buy": buy},
        "ft_stratparam_v": 1,
        "export_time": datetime.now(timezone.utc).isoformat(),
    }
    PARAMS_FILE.write_text(json.dumps(payload, indent=2) + "\n")


def backup_params() -> bytes | None:
    return PARAMS_FILE.read_bytes() if PARAMS_FILE.exists() else None


def restore_params(backup: bytes | None) -> None:
    if backup is None:
        if PARAMS_FILE.exists():
            PARAMS_FILE.unlink()
    else:
        PARAMS_FILE.write_bytes(backup)


def run_cmd(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def run_backtest(label: str, timerange: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"filter_{label}_{timerange.replace('-', '_')}"
    out = RESULTS_DIR / stem
    run_cmd(
        [
            "freqtrade",
            "backtesting",
            "-c",
            str(CONFIG),
            "--userdir",
            str(USER_DATA),
            "--strategy",
            STRATEGY_NAME,
            "--timerange",
            timerange,
            "-i",
            TIMEFRAME,
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
    candidates = sorted(RESULTS_DIR.glob(f"{stem}*"), reverse=True)
    if not candidates:
        candidates = sorted(RESULTS_DIR.glob("backtest-result-*"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No result for {stem}")
    return candidates[0]


def load_stats(path: Path) -> dict[str, Any]:
    from freqtrade.data.btanalysis import load_backtest_stats

    return load_backtest_stats(path)


def strategy_block(stats: dict[str, Any]) -> dict[str, Any]:
    strat = stats.get("strategy", {})
    if STRATEGY_NAME in strat:
        return strat[STRATEGY_NAME]
    if len(strat) == 1:
        return next(iter(strat.values()))
    raise KeyError(list(strat))


def extract_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    s = strategy_block(stats)
    total = int(s.get("total_trades", 0) or 0)
    wins = int(s.get("wins", 0) or 0)
    losses = int(s.get("losses", 0) or 0)
    winrate = float(s.get("winrate", 0.0) or 0.0)
    winrate_pct = winrate * 100.0 if winrate <= 1.0 else winrate
    profit_total = float(s.get("profit_total", 0.0) or 0.0)
    profit_abs = float(s.get("profit_total_abs", 0.0) or 0.0)
    profit_mean = float(s.get("profit_mean", 0.0) or 0.0)
    pf = float(s.get("profit_factor", 0.0) or 0.0)
    if pf != pf:
        pf = 0.0
    dd_abs = float(s.get("max_drawdown_abs", 0.0) or 0.0)
    dd_pct = float(s.get("max_drawdown_account", s.get("max_drawdown", 0.0)) or 0.0)
    if abs(dd_pct) <= 1.5:
        dd_pct *= 100.0
    sharpe = s.get("sharpe")
    sortino = s.get("sortino")
    return {
        "total_trades": total,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate_pct": round(winrate_pct, 4),
        "profit_pct": round(profit_total * 100.0, 4),
        "total_profit_abs": round(profit_abs, 4),
        "average_trade_pct": round(profit_mean * 100.0, 4),
        "profit_factor": round(float(pf), 4),
        "max_drawdown_abs": round(dd_abs, 4),
        "max_drawdown_pct": round(float(dd_pct), 4),
        "sharpe": None if sharpe is None else round(float(sharpe), 4),
        "sortino": None if sortino is None else round(float(sortino), 4),
    }


def compare_to_baseline(base: dict[str, Any], filt: dict[str, Any]) -> dict[str, Any]:
    base_n = base["total_trades"]
    filt_n = filt["total_trades"]
    removed = max(base_n - filt_n, 0)
    return {
        "trades_removed": removed,
        "trade_retention_pct": None if base_n == 0 else round(100.0 * filt_n / base_n, 2),
        "win_rate_delta_pp": round(filt["win_rate_pct"] - base["win_rate_pct"], 4),
        "profit_pct_delta": round(filt["profit_pct"] - base["profit_pct"], 4),
        "avg_trade_delta_pp": round(filt["average_trade_pct"] - base["average_trade_pct"], 4),
        "profit_factor_delta": round(filt["profit_factor"] - base["profit_factor"], 4),
        "max_drawdown_pct_delta": round(
            filt["max_drawdown_pct"] - base["max_drawdown_pct"], 4
        ),
    }


def score_filter(
    base: dict[str, Any], filt: dict[str, Any], delta: dict[str, Any]
) -> dict[str, Any]:
    reasons: list[str] = []
    keep = False

    if base["total_trades"] < 20:
        reasons.append("baseline_sample_too_small")
    if filt["total_trades"] < max(8, int(0.25 * max(base["total_trades"], 1))):
        reasons.append("filter_collapses_sample")

    profit_up = delta["profit_pct_delta"] > 0
    pf_up = delta["profit_factor_delta"] > 0
    wr_up = delta["win_rate_delta_pp"] > 0
    dd_ok = delta["max_drawdown_pct_delta"] <= 0.5

    if "filter_collapses_sample" in reasons or "baseline_sample_too_small" in reasons:
        reasons.append("rejected_due_to_sample")
    elif profit_up and pf_up and dd_ok:
        keep = True
        reasons.append("profit_and_pf_improved_dd_ok")
    elif profit_up and wr_up and dd_ok and filt["total_trades"] >= 15:
        keep = True
        reasons.append("profit_wr_improved_with_adequate_sample")
    else:
        reasons.append("no_clear_risk_adjusted_improvement")

    return {"keep_candidate": keep, "reasons": reasons}


def print_summary(results: dict[str, Any]) -> None:
    for period_name, period in results["periods"].items():
        print(f"\n=== {period_name} ({period['timerange']}) ===")
        base = period["runs"].get("baseline", {})
        print(
            f"baseline: trades={base.get('total_trades')} "
            f"win%={base.get('win_rate_pct')} profit%={base.get('profit_pct')} "
            f"PF={base.get('profit_factor')} DD%={base.get('max_drawdown_pct')}"
        )
        for fname, row in period["runs"].items():
            if fname == "baseline":
                continue
            vs = row.get("vs_baseline", {})
            verd = row.get("verdict", {})
            print(
                f"{fname}: trades={row['total_trades']} "
                f"(removed={vs.get('trades_removed')}) "
                f"win%={row['win_rate_pct']} profit%={row['profit_pct']} "
                f"PF={row['profit_factor']} DD%={row['max_drawdown_pct']} "
                f"keep={verd.get('keep_candidate')} reasons={verd.get('reasons')}"
            )
    print("\n=== Summary ===")
    print(json.dumps(results["summary"], indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filters", nargs="+", default=list(FILTER_MODES.keys()))
    parser.add_argument("--periods", nargs="+", default=list(PERIODS.keys()))
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    backup = backup_params()

    try:
        results: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "timeframe": TIMEFRAME,
            "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
            "periods": {},
            "summary": {},
        }

        for period_name in args.periods:
            timerange = PERIODS[period_name]
            period_out: dict[str, Any] = {"timerange": timerange, "runs": {}}
            ordered = ["baseline"] + [f for f in args.filters if f != "baseline"]
            baseline_metrics: dict[str, Any] | None = None

            for filt_name in ordered:
                if filt_name not in FILTER_MODES:
                    raise SystemExit(f"Unknown filter: {filt_name}")
                set_params(FILTER_MODES[filt_name])
                path = run_backtest(f"{period_name}_{filt_name}", timerange)
                metrics = extract_metrics(load_stats(path))
                row: dict[str, Any] = {
                    "filter": filt_name,
                    "result_file": str(path),
                    **metrics,
                }
                if filt_name == "baseline":
                    baseline_metrics = {k: metrics[k] for k in METRIC_KEYS}
                elif baseline_metrics is not None:
                    delta = compare_to_baseline(baseline_metrics, metrics)
                    row["vs_baseline"] = delta
                    row["verdict"] = score_filter(baseline_metrics, metrics, delta)
                period_out["runs"][filt_name] = row

            results["periods"][period_name] = period_out

        keep_votes: dict[str, list[bool]] = {
            k: [] for k in FILTER_MODES if k != "baseline"
        }
        for period in results["periods"].values():
            for fname, row in period["runs"].items():
                if fname == "baseline":
                    continue
                verdict = row.get("verdict") or {}
                keep_votes.setdefault(fname, []).append(
                    bool(verdict.get("keep_candidate"))
                )

        recommended: list[str] = []
        rejected: list[str] = []
        for fname, votes in keep_votes.items():
            if votes and all(votes):
                recommended.append(fname)
            else:
                rejected.append(fname)

        results["summary"] = {
            "recommended_filters": recommended,
            "rejected_filters": rejected,
            "keep_votes": keep_votes,
            "decision": (
                "Use baseline only — no single filter proved robust improvement "
                "across evaluated periods."
                if not recommended
                else f"Candidate filters with consistent improvement: {recommended}"
            ),
            "notes": [
                "Baseline scoring logic unchanged; filters default OFF.",
                "A filter must not collapse sample and must improve risk-adjusted results.",
                "Win-rate-only improvements with large trade drop are rejected.",
                "No hyperopt; fixed filter parameters for first-pass evidence.",
                "Require keep=True on ALL evaluated periods to recommend.",
            ],
        }

        set_params({})
        out = REPORTS_DIR / "score4window_filter_evaluation.json"
        out.write_text(json.dumps(results, indent=2, default=str) + "\n")
        print(f"Wrote {out}")
        print_summary(results)
        return 0
    finally:
        if backup is not None and not PARAMS_FILE.exists():
            restore_params(backup)
        set_params({})


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc.returncode}", file=sys.stderr)
        raise
