#!/usr/bin/env python3
"""
Short-term FreqAI research leaderboard (1h / 4h).

Reuses the same contestant set and backtest plumbing style as
scripts/run_freqai_leaderboard.py, without modifying Score4WindowStrategy
or the 1d leaderboard strategies.

Architecture note (this research universe):
  Pairlist is the existing 5 Binance majors. Top-15 active_universe is absent
  in these configs → gate OFF / drop-exit OFF. With only 5 pairs, Top-15 would
  be a no-op anyway. Documented for future 100+ coin runs.
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
RESULTS_DIR = USER_DATA / "freqai_shortterm_results"
BASE_CONFIG = USER_DATA / "config_freqai_shortterm.json"
BASELINE_CONFIG = USER_DATA / "config_baseline_5pairs_binance.json"
DEFAULT_TIMERANGE = "20260301-20260901"
SUBPERIODS = [
    ("p1_mar_apr", "20260301-20260501"),
    ("p2_may_jun", "20260501-20260701"),
    ("p3_jul_aug", "20260701-20260901"),
]
PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
VENV_FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
FT_BIN = str(VENV_FT if VENV_FT.exists() else "freqtrade")

# Primary ≈24h label horizons (classifier / regressor label_period_candles)
LABEL_PERIOD_BY_TF = {"1h": 24, "4h": 6}

CONTESTANTS: list[dict[str, Any]] = [
    {
        "id": "baseline_score4window",
        "label": "Score4Window (AI-siz)",
        "strategy": "Score4WindowStrategy",
        "freqaimodel": None,
        "family": "baseline",
    },
    {
        "id": "lightgbm_multitarget_hybrid",
        "label": "LightGBM MultiTarget Hybrid",
        "strategy": "Score4FreqaiShortMultiTargetHybrid",
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
        "strategy": "Score4FreqaiShortClassifierHybrid",
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
        "strategy": "Score4FreqaiShortClassifierHybrid",
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
        "id": "catboost_multiclass_hybrid",
        "label": "CatBoost MultiClass Hybrid",
        "strategy": "Score4FreqaiShortClassifierHybrid",
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
        "strategy": "Score4FreqaiShortMultiTargetHybrid",
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
        "id": "catboost_regressor",
        "label": "CatBoost Regressor",
        "strategy": "Score4FreqaiShortRegressor",
        "freqaimodel": "CatboostRegressor",
        "family": "regressor",
        "model_training_parameters": {
            "iterations": 120,
            "learning_rate": 0.05,
            "depth": 6,
            "verbose": 0,
        },
    },
    {
        "id": "xgboost_regressor",
        "label": "XGBoost Regressor",
        "strategy": "Score4FreqaiShortRegressor",
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
        "id": "lightgbm_regressor",
        "label": "LightGBM Regressor",
        "strategy": "Score4FreqaiShortRegressor",
        "freqaimodel": "LightGBMRegressor",
        "family": "regressor",
        "model_training_parameters": {
            "n_estimators": 120,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
        },
    },
]


def run_cmd(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not prev else f"{ROOT}{os.pathsep}{prev}"
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)


def write_run_config(
    contestant: dict[str, Any],
    timeframe: str,
    out_path: Path,
) -> Path:
    if contestant["freqaimodel"] is None:
        src = json.loads(BASELINE_CONFIG.read_text(encoding="utf-8"))
        src["timeframe"] = timeframe
        out_path.write_text(json.dumps(src, indent=2) + "\n", encoding="utf-8")
        return out_path

    cfg = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    cfg["timeframe"] = timeframe
    cfg["freqai"] = copy.deepcopy(cfg["freqai"])
    cfg["freqai"]["enabled"] = True
    cfg["freqai"]["identifier"] = f"st-{timeframe}-{contestant['id']}"
    cfg["freqai"]["feature_parameters"]["include_timeframes"] = [timeframe]
    cfg["freqai"]["feature_parameters"]["label_period_candles"] = LABEL_PERIOD_BY_TF[timeframe]
    cfg["freqai"]["model_training_parameters"] = contestant["model_training_parameters"]
    out_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return out_path


def extract_metrics(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
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
            raise ValueError(f"No strategy stats in {zip_path.name}")

    s = stats["strategy"][next(iter(stats["strategy"]))]

    def g(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in s and s[k] is not None:
                return s[k]
        return default

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

    avg_profit = g("profit_mean")
    avg_trade_pct = float(avg_profit) * 100.0 if avg_profit is not None else None

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
        "avg_trade_pct": round(avg_trade_pct, 4) if avg_trade_pct is not None else None,
        "avg_duration": g("holding_avg", "trade_duration_average", default=None),
        "fees_abs": g("total_fee_abs", "fee_sum", "fees", default=None),
    }


def delta_vs_baseline(row: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline or baseline.get("status") != "ok" or row.get("status") != "ok":
        return {}
    bm = baseline.get("metrics") or {}
    m = row.get("metrics") or {}

    def d(key: str) -> float | None:
        a, b = m.get(key), bm.get(key)
        if a is None or b is None:
            return None
        return round(float(a) - float(b), 4)

    return {
        "profit_pct_vs_baseline": d("profit_pct"),
        "dd_pct_vs_baseline": d("max_drawdown_pct"),
        "pf_vs_baseline": d("profit_factor"),
        "sharpe_vs_baseline": d("sharpe"),
        "trades_vs_baseline": d("total_trades"),
    }


def run_backtest(
    contestant: dict[str, Any],
    timeframe: str,
    timerange: str,
    run_tag: str,
) -> dict[str, Any]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{timeframe}_{run_tag}_{contestant['id']}"
    cfg_path = RESULTS_DIR / f"config_{run_id}.json"
    write_run_config(contestant, timeframe, cfg_path)

    out_dir = RESULTS_DIR / run_id
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
        timeframe,
        "--export",
        "trades",
        "--backtest-directory",
        str(out_dir),
        "--notes",
        run_id,
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
            metrics = extract_metrics(matches[-1])
        except Exception as exc:  # noqa: BLE001
            status = "metrics_parse_failed"
            error = str(exc)
    elif status == "ok":
        status = "failed"
        error = "backtest produced no result zip"

    return {
        "id": contestant["id"],
        "label": contestant["label"],
        "strategy": contestant["strategy"],
        "freqaimodel": contestant["freqaimodel"],
        "family": contestant["family"],
        "timeframe": timeframe,
        "timerange": timerange,
        "run_tag": run_tag,
        "status": status,
        "error": error,
        "result_file": result_file,
        "duration_sec": round((ended - started).total_seconds(), 1),
        "metrics": metrics,
    }


def rank_rows(rows: list[dict[str, Any]], *, mutate: bool = True) -> list[dict[str, Any]]:
    """Composite rank: ok first, then sharpe, then lower DD, then profit (not profit-only)."""

    def key(r: dict[str, Any]) -> tuple:
        m = r.get("metrics") or {}
        ok = 1 if r.get("status") == "ok" else 0
        sharpe = float(m.get("sharpe") or -1e9)
        dd = float(m.get("max_drawdown_pct") if m.get("max_drawdown_pct") is not None else 1e9)
        profit = float(m.get("profit_pct") or -1e9)
        pf = float(m.get("profit_factor") or -1e9)
        return (ok, sharpe, -dd, profit, pf)

    ranked = sorted(rows, key=key, reverse=True)
    if mutate:
        for i, r in enumerate(ranked, start=1):
            r["rank"] = i if r.get("status") == "ok" else None
    return ranked


def attach_baseline_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((r for r in rows if r.get("family") == "baseline"), None)
    for r in rows:
        r["vs_baseline"] = delta_vs_baseline(r, baseline)
    return rows


def pick_best_ai(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    ai_ok = [r for r in rows if r.get("family") != "baseline" and r.get("status") == "ok"]
    if not ai_ok:
        return None
    return rank_rows(ai_ok, mutate=False)[0]


def classify_verdict(baseline: dict[str, Any] | None, best_ai: dict[str, Any] | None) -> str:
    if not baseline or baseline.get("status") != "ok":
        return "Baseline failed; no decision."
    if not best_ai:
        return "AI bu testte deterministic baseline'ı geçemedi."

    bm = baseline["metrics"]
    am = best_ai["metrics"]
    bp = float(bm.get("profit_pct") or 0)
    ap = float(am.get("profit_pct") or 0)
    bd = float(bm.get("max_drawdown_pct") or 0)
    ad = float(am.get("max_drawdown_pct") or 0)
    bs = float(bm.get("sharpe") or 0)
    as_ = float(am.get("sharpe") or 0)

    profit_better = ap > bp
    risk_better = ad < bd and as_ >= bs

    if profit_better and risk_better:
        return "Bu model ileri test için aday."
    if (not profit_better) and risk_better:
        return "AI profit artırmadı fakat risk filtresi olarak potansiyel gösterdi."
    if profit_better and ad > bd * 1.5:
        return (
            "AI profit artırdı fakat drawdown belirgin şekilde kötüleşti; "
            "otomatik olarak daha iyi kabul edilmedi."
        )
    if ap <= bp and as_ <= bs:
        return "AI bu testte deterministic baseline'ı geçemedi."
    return "AI karışık sinyal verdi; production adayı değil."


def fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def render_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# FreqAI Short-Term Leaderboard")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Full timerange: `{report['timerange']}`")
    lines.append(f"- Pairs: {', '.join(report['pairs'])}")
    lines.append("- ROI 10% / SL -10% / max_open_trades 5 / stake unlimited")
    lines.append("- FreqAI train_period_days=120, backtest_period_days=30 (unchanged from 1d LB)")
    lines.append("- Classifier labels: existing `up`/`down` (not BUY/HOLD/SELL)")
    lines.append(
        "- AI entries require Score4Window `total_score >= 2` confirmation "
        "(AI is filter, not replacement)"
    )
    lines.append(
        "- Top-15 / drop-exit: OFF in this research config; universe is 5 majors only"
    )
    lines.append("")
    for note in report.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")

    for tf in report["timeframes"]:
        block = report["results_by_timeframe"][tf]
        lines.append(f"## {tf} results")
        lines.append("")
        lines.append(
            "| # | Strategy | TF | Trades | Profit% | WR% | PF | DD% | Sharpe | Sortino |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for r in block["leaderboard"]:
            m = r.get("metrics") or {}
            lines.append(
                f"| {r.get('rank') or '-'} | {r['label']} | {tf} | "
                f"{fmt(m.get('total_trades'), 0)} | {fmt(m.get('profit_pct'))} | "
                f"{fmt(m.get('win_rate_pct'))} | {fmt(m.get('profit_factor'))} | "
                f"{fmt(m.get('max_drawdown_pct'))} | {fmt(m.get('sharpe'))} | "
                f"{fmt(m.get('sortino'))} |"
            )
        lines.append("")
        lines.append("### vs Score4Window baseline")
        lines.append("")
        lines.append(
            "| Strategy | ΔProfit% | ΔDD% | ΔPF | ΔSharpe | ΔTrades |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|")
        for r in block["leaderboard"]:
            if r.get("family") == "baseline":
                continue
            d = r.get("vs_baseline") or {}
            lines.append(
                f"| {r['label']} | {fmt(d.get('profit_pct_vs_baseline'))} | "
                f"{fmt(d.get('dd_pct_vs_baseline'))} | {fmt(d.get('pf_vs_baseline'))} | "
                f"{fmt(d.get('sharpe_vs_baseline'))} | {fmt(d.get('trades_vs_baseline'), 0)} |"
            )
        lines.append("")

        if block.get("subperiods"):
            lines.append("### Subperiod robustness")
            lines.append("")
            for sp_name, sp in block["subperiods"].items():
                lines.append(f"#### {sp_name} (`{sp['timerange']}`)")
                lines.append("")
                lines.append(
                    "| # | Strategy | Trades | Profit% | DD% | Sharpe |"
                )
                lines.append("|---|---|---:|---:|---:|---:|")
                for r in sp["leaderboard"]:
                    m = r.get("metrics") or {}
                    lines.append(
                        f"| {r.get('rank') or '-'} | {r['label']} | "
                        f"{fmt(m.get('total_trades'), 0)} | {fmt(m.get('profit_pct'))} | "
                        f"{fmt(m.get('max_drawdown_pct'))} | {fmt(m.get('sharpe'))} |"
                    )
                lines.append("")

    lines.append("## BEST AI vs BASELINE")
    lines.append("")
    lines.append("| Timeframe | Baseline | Best AI | AI Advantage (Profit%) | DD Difference | Verdict |")
    lines.append("|---|---|---|---:|---:|---|")
    for row in report["best_ai_vs_baseline"]:
        lines.append(
            f"| {row['timeframe']} | {row['baseline_label']} ({fmt(row['baseline_profit_pct'])}%) | "
            f"{row['best_ai_label']} ({fmt(row['best_ai_profit_pct'])}%) | "
            f"{fmt(row['ai_advantage_profit_pct'])} | {fmt(row['dd_difference_pct'])} | "
            f"{row['verdict']} |"
        )
    lines.append("")
    lines.append("## Answers")
    lines.append("")
    for q, a in report.get("answers", {}).items():
        lines.append(f"**{q}**")
        lines.append("")
        lines.append(a)
        lines.append("")
    lines.append("## Decision")
    lines.append("")
    lines.append(report.get("final_decision", ""))
    lines.append("")
    lines.append("No model promoted to production.")
    lines.append("")
    return "\n".join(lines)


def build_answers(report: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    by_tf = report["results_by_timeframe"]
    available = list(report.get("timeframes") or by_tf.keys())

    def beats(tf: str) -> str:
        if tf not in by_tf:
            return f"{tf}: bu koşuda çalıştırılmadı."
        block = by_tf[tf]
        b = next((r for r in block["leaderboard"] if r["family"] == "baseline"), None)
        best = block.get("best_ai")
        if not b or b.get("status") != "ok":
            return f"{tf}: baseline sonuç vermedi."
        if not best:
            return f"Hayır — {tf}'de geçerli AI sonucu yok."
        bm, am = b["metrics"], best["metrics"]
        profit_ok = float(am.get("profit_pct") or -1e9) > float(bm.get("profit_pct") or 0)
        risk_ok = float(am.get("max_drawdown_pct") or 1e9) <= float(
            bm.get("max_drawdown_pct") or 0
        )
        if profit_ok and risk_ok:
            return f"Evet — {best['label']} hem profit hem risk açısından baseline üstü."
        if profit_ok:
            return (
                f"Kısmen — {best['label']} profit'te önde ama DD/risk iyileşmedi "
                f"(otomatik galip sayılmadı)."
            )
        if float(am.get("max_drawdown_pct") or 1e9) < float(bm.get("max_drawdown_pct") or 0):
            return f"Hayır (profit) — {best['label']} riskte daha iyi olabilir ama profit geçmedi."
        return f"Hayır — {tf}'de AI, Score4Window'u geçemedi."

    answers["1. 1H'de AI, Score4Window'u geçiyor mu?"] = beats("1h")
    answers["2. 4H'de AI, Score4Window'u geçiyor mu?"] = beats("4h")

    # Best overall AI by composite rank across available TFs
    all_ai = []
    for tf in available:
        block = by_tf.get(tf) or {}
        for r in block.get("leaderboard", []):
            if r.get("family") != "baseline" and r.get("status") == "ok":
                all_ai.append(r)
    best = rank_rows(all_ai, mutate=False)[0] if all_ai else None
    answers["3. Hangi model en iyi?"] = (
        f"{best['label']} on {best['timeframe']} "
        f"(profit {fmt((best.get('metrics') or {}).get('profit_pct'))}%, "
        f"DD {fmt((best.get('metrics') or {}).get('max_drawdown_pct'))}%, "
        f"Sharpe {fmt((best.get('metrics') or {}).get('sharpe'))})"
        if best
        else "Geçerli AI sonucu yok."
    )

    def family_avg(family: str) -> float | None:
        vals = [
            float((r.get("metrics") or {}).get("sharpe"))
            for r in all_ai
            if r.get("family") == family and (r.get("metrics") or {}).get("sharpe") is not None
        ]
        return sum(vals) / len(vals) if vals else None

    mt, clf, reg = family_avg("multitarget"), family_avg("classifier"), family_avg("regressor")
    answers["4. MultiTarget gerçekten classifier/regressor modellerinden daha iyi mi?"] = (
        f"Ortalama Sharpe — MultiTarget: {fmt(mt)}, Classifier: {fmt(clf)}, Regressor: {fmt(reg)}."
    )

    def brand_avg(prefix: str) -> float | None:
        vals = [
            float((r.get("metrics") or {}).get("sharpe"))
            for r in all_ai
            if prefix in r["id"] and (r.get("metrics") or {}).get("sharpe") is not None
        ]
        return sum(vals) / len(vals) if vals else None

    answers["5. CatBoost mu LightGBM mi daha iyi?"] = (
        f"Ortalama Sharpe — CatBoost: {fmt(brand_avg('catboost'))}, "
        f"LightGBM: {fmt(brand_avg('lightgbm'))}."
    )

    tf_scores = {}
    for tf in available:
        block = by_tf.get(tf) or {}
        b = next((r for r in block.get("leaderboard", []) if r["family"] == "baseline"), None)
        best_tf = block.get("best_ai")
        if not b or b.get("status") != "ok":
            continue
        score = float((b.get("metrics") or {}).get("sharpe") or 0)
        if best_tf:
            score += 0.5 * float((best_tf.get("metrics") or {}).get("sharpe") or 0)
            score -= 0.01 * float((best_tf.get("metrics") or {}).get("max_drawdown_pct") or 0)
        tf_scores[tf] = score
    preferred = max(tf_scores, key=tf_scores.get) if tf_scores else None
    answers["6. 1H mi 4H mi bizim kısa vadeli hedefimize daha uygun görünüyor?"] = (
        f"{preferred} (composite Sharpe/DD proxy)." if preferred else "Belirsiz / eksik TF."
    )

    bits = []
    for tf in available:
        block = by_tf.get(tf) or {}
        b = next((r for r in block.get("leaderboard", []) if r["family"] == "baseline"), None)
        best_tf = block.get("best_ai")
        if not b or not best_tf:
            continue
        d = best_tf.get("vs_baseline") or {}
        bits.append(
            f"{tf}: Δprofit={fmt(d.get('profit_pct_vs_baseline'))}, "
            f"ΔDD={fmt(d.get('dd_pct_vs_baseline'))}"
        )
    answers["7. AI yalnızca profit artırıyor mu, yoksa DD'yi de iyileştiriyor mu?"] = (
        "; ".join(bits) if bits else "Karşılaştırma yok."
    )

    trade_counts = [(r["label"], (r.get("metrics") or {}).get("total_trades")) for r in all_ai]
    answers["8. AI'ın eklenmesi istatistiksel olarak anlamlı görünüyor mu?"] = (
        "Trade sayıları: "
        + (", ".join(f"{n}={t}" for n, t in trade_counts[:8]) if trade_counts else "yok")
        + ". 1h/4h'de örneklem 1d'den daha zengin (120g train ≈612@4h / ≈2448@1h), "
        "ama tek dönem + sabit hiperparametre → keşifsel; production iddiası yok."
    )

    dep_notes = []
    for tf in available:
        block = by_tf.get(tf) or {}
        sps = block.get("subperiods") or {}
        if not sps:
            dep_notes.append(f"{tf}: subperiod çalıştırılmadı.")
            continue
        winners = []
        for sp_name, sp in sps.items():
            top = next((r for r in sp["leaderboard"] if r.get("rank") == 1), None)
            winners.append(f"{sp_name}→{(top or {}).get('label', '?')}")
        dep_notes.append(f"{tf}: " + "; ".join(winners))
    answers["9. Sonuçlar tek bir döneme bağımlı mı?"] = (
        " | ".join(dep_notes) if dep_notes else "Subperiod yok."
    )

    return answers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timerange", default=DEFAULT_TIMERANGE)
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h"])
    parser.add_argument("--only", nargs="*", help="Contestant ids")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-subperiods", action="store_true")
    parser.add_argument(
        "--subperiods-only-baseline-and-best",
        action="store_true",
        help="After full run, re-run subperiods only for baseline + best AI per TF.",
    )
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    selected = CONTESTANTS
    if args.only:
        wanted = set(args.only)
        selected = [c for c in CONTESTANTS if c["id"] in wanted]
        if not selected:
            print("No matching contestants", file=sys.stderr)
            return 2

    if not args.skip_download:
        for tf in args.timeframes:
            # Need ~120d train before Mar 2026 → download generously
            run_cmd(
                [
                    FT_BIN,
                    "download-data",
                    "-c",
                    str(BASELINE_CONFIG),
                    "--userdir",
                    str(USER_DATA),
                    "--timeframe",
                    tf,
                    "--days",
                    "500",
                ]
            )

    results_by_tf: dict[str, Any] = {}
    best_vs_rows: list[dict[str, Any]] = []

    for tf in args.timeframes:
        print(f"\n======== TIMEFRAME {tf} ========", flush=True)
        rows: list[dict[str, Any]] = []
        for c in selected:
            print(f"\n>>> [{tf}/full] {c['label']}", flush=True)
            rows.append(run_backtest(c, tf, args.timerange, "full"))

        rows = attach_baseline_deltas(rank_rows(rows))
        baseline = next((r for r in rows if r["family"] == "baseline"), None)
        best_ai = pick_best_ai(rows)
        verdict = classify_verdict(baseline, best_ai)

        subperiods: dict[str, Any] = {}
        if not args.skip_subperiods:
            # Full subperiod grid is expensive; default to baseline + best AI only
            # unless user asked otherwise via omitting the flag (we always do best+baseline
            # for robustness unless --skip-subperiods).
            sub_contestants = [c for c in selected if c["family"] == "baseline"]
            if best_ai:
                match = next((c for c in selected if c["id"] == best_ai["id"]), None)
                if match:
                    sub_contestants.append(match)
            # If user wants all models in subperiods, pass all selected when flag false
            # and env SHORTTERM_SUBPERIODS_ALL=1
            if os.environ.get("SHORTTERM_SUBPERIODS_ALL") == "1":
                sub_contestants = selected

            for sp_id, sp_range in SUBPERIODS:
                print(f"\n--- [{tf}/{sp_id}] ---", flush=True)
                sp_rows = []
                for c in sub_contestants:
                    print(f">>> [{tf}/{sp_id}] {c['label']}", flush=True)
                    sp_rows.append(run_backtest(c, tf, sp_range, sp_id))
                sp_rows = attach_baseline_deltas(rank_rows(sp_rows))
                subperiods[sp_id] = {
                    "timerange": sp_range,
                    "leaderboard": sp_rows,
                }

        results_by_tf[tf] = {
            "leaderboard": rows,
            "best_ai": best_ai,
            "verdict": verdict,
            "subperiods": subperiods,
            "label_period_candles": LABEL_PERIOD_BY_TF.get(tf),
            "estimated_train_candles": (
                120 * (24 if tf == "1h" else 6 if tf == "4h" else 1)
            ),
        }

        best_vs_rows.append(
            {
                "timeframe": tf,
                "baseline_label": (baseline or {}).get("label"),
                "baseline_profit_pct": ((baseline or {}).get("metrics") or {}).get("profit_pct"),
                "baseline_dd_pct": ((baseline or {}).get("metrics") or {}).get(
                    "max_drawdown_pct"
                ),
                "best_ai_label": (best_ai or {}).get("label") or "-",
                "best_ai_profit_pct": ((best_ai or {}).get("metrics") or {}).get("profit_pct"),
                "best_ai_dd_pct": ((best_ai or {}).get("metrics") or {}).get("max_drawdown_pct"),
                "ai_advantage_profit_pct": (
                    None
                    if not best_ai or not baseline
                    else round(
                        float((best_ai.get("metrics") or {}).get("profit_pct") or 0)
                        - float((baseline.get("metrics") or {}).get("profit_pct") or 0),
                        4,
                    )
                ),
                "dd_difference_pct": (
                    None
                    if not best_ai or not baseline
                    else round(
                        float((best_ai.get("metrics") or {}).get("max_drawdown_pct") or 0)
                        - float((baseline.get("metrics") or {}).get("max_drawdown_pct") or 0),
                        4,
                    )
                ),
                "verdict": verdict,
            }
        )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timerange": args.timerange,
        "timeframes": args.timeframes,
        "pairs": PAIRS,
        "notes": [
            "Research-only layer; Score4WindowStrategy and 1d FreqAI strategies untouched.",
            "Short-term strategies require Score4Window total_score>=2 + FreqAI confirmation.",
            "Classifier target vocabulary remains up/down (project FreqAI convention).",
            "MultiTarget horizons: 1h=6/12/24, 4h=2/3/6 candles; strong-move thresh=1% on ~24h.",
            "Pair universe = existing 5 majors (not 100+). Top-15 gate inactive here.",
            "Ranking uses Sharpe then lower DD then profit (not profit-only).",
            "Subperiods default to baseline + best-AI per TF for cost; set SHORTTERM_SUBPERIODS_ALL=1 for full grid.",
        ],
        "results_by_timeframe": results_by_tf,
        "best_ai_vs_baseline": best_vs_rows,
    }
    report["answers"] = build_answers(report)

    # Final decision across TFs
    verdicts = [r["verdict"] for r in best_vs_rows]
    if all("geçemedi" in v for v in verdicts):
        report["final_decision"] = "AI bu testte deterministic baseline'ı geçemedi."
    elif any("ileri test için aday" in v for v in verdicts):
        report["final_decision"] = (
            "En az bir TF'de AI hem profit hem risk açısından aday görünüyor; "
            "yine de production'a alınmadı — sadece ileri research."
        )
    elif any("risk filtresi" in v for v in verdicts):
        report["final_decision"] = (
            "AI profit artırmadı fakat risk filtresi olarak potansiyel gösterdi."
        )
    else:
        report["final_decision"] = (
            "Sonuçlar karışık; Score4Window referans kalmaya devam ediyor. "
            "Hiçbir model production'a alınmadı."
        )

    out_json = REPORTS / "freqai_shortterm_leaderboard.json"
    out_md = REPORTS / "freqai_shortterm_leaderboard.md"
    out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_md(report), encoding="utf-8")

    print("\n=== SHORT-TERM LEADERBOARD DONE ===")
    for tf in args.timeframes:
        print(f"\n-- {tf} --")
        for r in results_by_tf[tf]["leaderboard"]:
            m = r.get("metrics") or {}
            print(
                f"{str(r.get('rank') or '-'):>3} {r['label']:<34} "
                f"{fmt(m.get('total_trades'), 0):>6} {fmt(m.get('profit_pct')):>8} "
                f"{fmt(m.get('max_drawdown_pct')):>7} {fmt(m.get('sharpe')):>7} {r['status']}"
            )
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
