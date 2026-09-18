#!/usr/bin/env python3
"""
FreqAI vs Score4WindowStrategy leaderboard backtest runner.

Runs a fixed set of popular FreqAI model/strategy combos against the
AI-less Score4Window baseline on the same Binance 5-pair / 1d setup.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
USER_DATA = ROOT / "user_data"
REPORTS = ROOT / "reports"
RESULTS_DIR = USER_DATA / "freqai_leaderboard_results"
BASE_CONFIG = USER_DATA / "config_freqai_leaderboard.json"
BASELINE_CONFIG = USER_DATA / "config_baseline_5pairs_binance.json"
DEFAULT_TIMERANGE = "20260301-20260901"
DEFAULT_TIMEFRAME = "1d"
VENV_FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
FT_BIN = str(VENV_FT if VENV_FT.exists() else "freqtrade")

# Contenders: label, strategy, freqaimodel (None for non-AI), training params
CONTESTANTS: list[dict[str, Any]] = [
    {
        "id": "baseline_score4window",
        "label": "Score4Window (AI-siz)",
        "strategy": "Score4WindowStrategy",
        "freqaimodel": None,
        "family": "baseline",
    },
    {
        "id": "catboost_multiclass_hybrid",
        "label": "CatBoost MultiClass Hybrid",
        "strategy": "Score4FreqaiClassifierHybrid",
        "freqaimodel": "CatboostClassifier",
        "family": "classifier",
        "model_training_parameters": {
            "iterations": 120,
            "learning_rate": 0.05,
            "depth": 6,
            "verbose": 0,
        },
    },
    {
        "id": "catboost_multitarget_hybrid",
        "label": "CatBoost MultiTarget Hybrid",
        "strategy": "Score4FreqaiMultiTargetHybrid",
        "freqaimodel": "CatboostClassifierMultiTarget",
        "family": "multitarget",
        "model_training_parameters": {
            "iterations": 120,
            "learning_rate": 0.05,
            "depth": 6,
            "verbose": 0,
        },
    },
    {
        "id": "lightgbm_multitarget_hybrid",
        "label": "LightGBM MultiTarget Hybrid",
        "strategy": "Score4FreqaiMultiTargetHybrid",
        "freqaimodel": "LightGBMClassifierMultiTarget",
        "family": "multitarget",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
        },
    },
    {
        "id": "lightgbm_classifier_hybrid",
        "label": "LightGBM Classifier Hybrid",
        "strategy": "Score4FreqaiClassifierHybrid",
        "freqaimodel": "LightGBMClassifier",
        "family": "classifier",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
        },
    },
    {
        "id": "xgboost_classifier_hybrid",
        "label": "XGBoost Classifier Hybrid",
        "strategy": "Score4FreqaiClassifierHybrid",
        "freqaimodel": "XGBoostClassifier",
        "family": "classifier",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "max_depth": 6,
            "verbosity": 0,
        },
    },
    {
        "id": "lightgbm_regressor",
        "label": "LightGBM Regressor (classic)",
        "strategy": "Score4FreqaiRegressor",
        "freqaimodel": "LightGBMRegressor",
        "family": "regressor",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
        },
    },
    {
        "id": "xgboost_regressor",
        "label": "XGBoost Regressor",
        "strategy": "Score4FreqaiRegressor",
        "freqaimodel": "XGBoostRegressor",
        "family": "regressor",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "max_depth": 6,
            "verbosity": 0,
        },
    },
    {
        "id": "catboost_regressor",
        "label": "CatBoost Regressor",
        "strategy": "Score4FreqaiRegressor",
        "freqaimodel": "CatboostRegressor",
        "family": "regressor",
        "model_training_parameters": {
            "iterations": 120,
            "learning_rate": 0.05,
            "depth": 6,
            "verbose": 0,
        },
    },
]


def run_cmd(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not prev else f"{ROOT}{os.pathsep}{prev}"
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)


def write_run_config(contestant: dict[str, Any], out_path: Path) -> Path:
    if contestant["freqaimodel"] is None:
        src = json.loads(BASELINE_CONFIG.read_text(encoding="utf-8"))
        out_path.write_text(json.dumps(src, indent=2) + "\n", encoding="utf-8")
        return out_path

    cfg = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    cfg["freqai"] = copy.deepcopy(cfg["freqai"])
    cfg["freqai"]["enabled"] = True
    cfg["freqai"]["identifier"] = f"lb-{contestant['id']}"
    cfg["freqai"]["model_training_parameters"] = contestant["model_training_parameters"]
    out_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return out_path


def extract_metrics(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        # Prefer the main backtest result JSON (not *_config.json)
        candidates = [
            n
            for n in zf.namelist()
            if n.endswith(".json") and "_config" not in n and not n.endswith(".meta.json")
        ]
        stats: dict[str, Any] = {}
        for name in sorted(candidates):
            payload = json.loads(zf.read(name))
            if isinstance(payload, dict) and "strategy" in payload:
                stats = payload
                break

        if not stats:
            raise ValueError(f"No strategy stats found in {zip_path.name}: {zf.namelist()}")

    if "strategy" in stats and isinstance(stats["strategy"], dict):
        strat_key = next(iter(stats["strategy"]))
        s = stats["strategy"][strat_key]
    else:
        s = stats

    def g(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in s and s[k] is not None:
                return s[k]
        return default

    # FT 2026.x: profit_total is a ratio (0.05 = 5%), profit_total_pct often absent.
    profit_ratio = g("profit_total")
    profit_pct_field = g("profit_total_pct")
    if profit_pct_field is not None:
        profit_pct = float(profit_pct_field)
    elif profit_ratio is not None:
        profit_pct = float(profit_ratio) * 100.0
    else:
        profit_pct = None

    winrate = g("winrate")
    win_rate_pct = float(winrate) * 100.0 if winrate is not None else None

    dd = g("max_drawdown_account", "max_drawdown")
    max_drawdown_pct = float(dd) * 100.0 if dd is not None else None

    return {
        "total_trades": g("total_trades", default=0),
        "win_rate_pct": round(win_rate_pct, 2) if win_rate_pct is not None else None,
        "profit_pct": round(profit_pct, 4) if profit_pct is not None else None,
        "profit_abs": g("profit_total_abs", default=None),
        "profit_factor": g("profit_factor", default=None),
        "max_drawdown_pct": round(max_drawdown_pct, 4) if max_drawdown_pct is not None else None,
        "sharpe": g("sharpe", default=None),
        "sortino": g("sortino", default=None),
        "expectancy": g("expectancy", default=None),
    }


def normalize_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    return raw


def run_backtest(contestant: dict[str, Any], timerange: str) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path = RESULTS_DIR / f"config_{contestant['id']}.json"
    write_run_config(contestant, cfg_path)

    out_dir = RESULTS_DIR / contestant["id"]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = {p.name for p in (USER_DATA / "backtest_results").glob("backtest-result-*.zip")}

    cmd = [
        FT_BIN,
        "backtesting",
        "-c",
        str(cfg_path),
        "--userdir",
        str(USER_DATA),
        "--strategy",
        contestant["strategy"],
        "--timerange",
        timerange,
        "-i",
        DEFAULT_TIMEFRAME,
        "--export",
        "trades",
        "--backtest-directory",
        str(out_dir),
        "--notes",
        contestant["id"],
        "--cache",
        "none",
        "--breakdown",
        "month",
    ]
    if contestant["freqaimodel"]:
        cmd.extend(["--freqaimodel", contestant["freqaimodel"]])

    started = datetime.now(timezone.utc)
    try:
        run_cmd(cmd)
        status = "ok"
        error = None
    except subprocess.CalledProcessError as exc:
        status = "failed"
        error = str(exc)

    ended = datetime.now(timezone.utc)
    matches = sorted(out_dir.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
    if not matches:
        # Fallback: newest zip created during this run in default dir
        after = sorted(
            (USER_DATA / "backtest_results").glob("backtest-result-*.zip"),
            key=lambda p: p.stat().st_mtime,
        )
        matches = [p for p in after if p.name not in before]
    metrics: dict[str, Any] = {}
    result_file = None
    if matches and status == "ok":
        result_file = str(matches[-1])
        try:
            metrics = normalize_metrics(extract_metrics(matches[-1]))
        except Exception as exc:  # noqa: BLE001
            status = "metrics_parse_failed"
            error = str(exc)
    elif status == "ok" and not matches:
        status = "failed"
        error = "backtest produced no result zip"

    return {
        "id": contestant["id"],
        "label": contestant["label"],
        "strategy": contestant["strategy"],
        "freqaimodel": contestant["freqaimodel"],
        "family": contestant["family"],
        "status": status,
        "error": error,
        "result_file": result_file,
        "duration_sec": round((ended - started).total_seconds(), 1),
        "metrics": metrics,
    }


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        m = r.get("metrics") or {}
        ok = 1 if r.get("status") == "ok" else 0
        return (
            ok,
            float(m.get("profit_pct") or -1e9),
            float(m.get("sharpe") or -1e9),
            float(m.get("profit_factor") or -1e9),
        )

    ranked = sorted(rows, key=key, reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i if r.get("status") == "ok" else None
    return ranked


def print_leaderboard(rows: list[dict[str, Any]]) -> None:
    print("\n=== FreqAI Leaderboard ===")
    header = (
        f"{'#':>3}  {'Strategy':<34} {'Trades':>6} {'Profit%':>8} "
        f"{'WR%':>6} {'PF':>6} {'DD%':>7} {'Sharpe':>7} {'Status'}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        m = r.get("metrics") or {}
        rank = r.get("rank") or "-"
        print(
            f"{str(rank):>3}  {r['label']:<34} "
            f"{str(m.get('total_trades', '-')):>6} "
            f"{_fmt(m.get('profit_pct')):>8} "
            f"{_fmt(m.get('win_rate_pct')):>6} "
            f"{_fmt(m.get('profit_factor')):>6} "
            f"{_fmt(m.get('max_drawdown_pct')):>7} "
            f"{_fmt(m.get('sharpe')):>7} "
            f"{r.get('status')}"
        )


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timerange", default=DEFAULT_TIMERANGE)
    parser.add_argument("--only", nargs="*", help="Contestant ids to run")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge with existing reports/freqai_leaderboard.json (keep prior ok rows).",
    )
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        run_cmd(
            [
                FT_BIN,
                "download-data",
                "-c",
                str(BASELINE_CONFIG),
                "--userdir",
                str(USER_DATA),
                "--timeframe",
                DEFAULT_TIMEFRAME,
                "--days",
                "500",
            ]
        )

    selected = CONTESTANTS
    if args.only:
        wanted = set(args.only)
        selected = [c for c in CONTESTANTS if c["id"] in wanted]
        if not selected:
            print("No matching contestants", file=sys.stderr)
            return 2

    rows: list[dict[str, Any]] = []
    for c in selected:
        print(f"\n>>> Running {c['label']} ({c['id']})", flush=True)
        rows.append(run_backtest(c, args.timerange))

    if args.merge_existing:
        out_path = REPORTS / "freqai_leaderboard.json"
        if out_path.exists():
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            by_id = {r["id"]: r for r in prev.get("leaderboard", [])}
            for r in rows:
                by_id[r["id"]] = r
            # Keep known contestant order, then any extras
            order = [c["id"] for c in CONTESTANTS]
            merged = []
            seen = set()
            for cid in order:
                if cid in by_id:
                    merged.append(by_id[cid])
                    seen.add(cid)
            for cid, r in by_id.items():
                if cid not in seen:
                    merged.append(r)
            rows = merged

    ranked = rank_rows(rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timerange": args.timerange,
        "timeframe": DEFAULT_TIMEFRAME,
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        "notes": [
            "Same ROI 10% / stoploss -10% / 1d / 5 Binance majors for all runs.",
            "FreqAI: train_period_days=120, backtest_period_days=30, label_period=5.",
            "CatBoost models vendored into user_data/freqaimodels (removed upstream in FT 2026.x).",
            "Exploratory leaderboard; daily sample size is small for ML confidence.",
        ],
        "leaderboard": ranked,
    }
    out = REPORTS / "freqai_leaderboard.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print_leaderboard(ranked)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
