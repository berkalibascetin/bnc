#!/usr/bin/env python3
"""Diagnose Model B underperformance vs frozen A. No Phase B. No A changes."""
from __future__ import annotations

import json
import logging
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("diagnose_b")

TIMERANGE = "20240101-20260901"
MARKETS_PATH = Path("/tmp/offline_markets.json")
PRED_DIR = ROOT / "user_data" / "models" / "score4window_phase_a_v1" / "backtesting_predictions"
EXPORT_DIR = ROOT / "user_data" / "backtest_results"
OUT_MD = ROOT / "reports" / "phase_a_model_b_failure_diagnosis.md"
OUT_JSON = ROOT / "reports" / "phase_a_model_b_failure_diagnosis.json"
B_WINDOW_START = pd.Timestamp("2025-05-01", tz="UTC")


def _patch_markets() -> None:
    from freqtrade.exchange.exchange import Exchange
    markets = json.loads(MARKETS_PATH.read_text())
    def reload_markets(self, force: bool = False, *, load_leverage_tiers: bool = True) -> None:  # noqa: ANN001
        self._markets = markets
        try: self._api.set_markets(markets)
        except Exception: pass
        try: self._api_async.set_markets(markets)
        except Exception: pass
        from freqtrade.util import dt_ts
        self._last_markets_refresh = dt_ts()
    Exchange.reload_markets = reload_markets  # type: ignore[method-assign]


def _run_export(label: str, config_path: Path, strategy: str, freqaimodel: str | None) -> Path:
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.backtesting import Backtesting

    cfg_obj = json.loads(config_path.read_text())
    cfg_obj.setdefault("exit_pricing", {})
    cfg_obj["exit_pricing"]["price_side"] = "other"
    cfg_obj["datadir"] = str(ROOT / "user_data" / "data" / "binance")
    cfg_obj["user_data_dir"] = str(ROOT / "user_data")
    tmp_cfg = Path(f"/tmp/phase_a_diag_{label}_config.json")
    tmp_cfg.write_text(json.dumps(cfg_obj, indent=2))
    export_stem = EXPORT_DIR / f"diag_{label}"
    args: dict[str, Any] = {
        "config": [str(tmp_cfg)],
        "strategy": strategy,
        "strategy_path": str(ROOT / "user_data" / "strategies"),
        "timerange": TIMERANGE,
        "export": "trades",
        "exportfilename": str(export_stem),
        "datadir": str(ROOT / "user_data" / "data" / "binance"),
        "user_data_dir": str(ROOT / "user_data"),
        "verbosity": 0,
    }
    if freqaimodel:
        args["freqaimodel"] = freqaimodel
    config = setup_utils_configuration(args, RunMode.BACKTEST)
    config["datadir"] = Path(ROOT / "user_data" / "data" / "binance")
    config["user_data_dir"] = Path(ROOT / "user_data")
    config["strategy_path"] = str(ROOT / "user_data" / "strategies")
    before = {p.resolve() for p in EXPORT_DIR.glob("*.zip")}
    t0 = time.time()
    bt = Backtesting(config)
    bt.start()
    logger.info("%s finished in %.1fs", label, time.time() - t0)
    after = {p.resolve() for p in EXPORT_DIR.glob("*.zip")}
    new = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new:
        return Path(new[-1])
    # fallback newest
    zips = sorted(EXPORT_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1]


def _trades_from_zip(zpath: Path, strategy: str) -> pd.DataFrame:
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        main = [n for n in names if n.endswith(".json") and "config" not in n and not n.endswith(f"_{strategy}.json")]
        payload = json.loads(z.read(main[0]))
    block = (payload.get("strategy") or {}).get(strategy) or {}
    df = pd.DataFrame(block.get("trades") or [])
    if df.empty:
        return df
    for c in ("open_date", "close_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True)
    # freqtrade enters on next candle after signal; signal ~ prior daily bar
    df["signal_date"] = (df["open_date"] - pd.Timedelta(days=1)).dt.normalize()
    # Normalize common freqtrade column aliases
    if "profit_ratio" not in df.columns and "profit_ratio" in df.columns:
        pass
    if "profit_abs" not in df.columns and "profit_abs" in df.columns:
        pass
    # Some exports use profit_ratio / profit_abs already
    rename = {}
    if "profit_ratio" not in df.columns and "close_profit" in df.columns:
        rename["close_profit"] = "profit_ratio"
    if rename:
        df = df.rename(columns=rename)
    return df


def _load_predictions() -> pd.DataFrame:
    files = sorted(PRED_DIR.glob("cb_*_prediction.feather"))
    logger.info("loading %s prediction files", len(files))
    parts = []
    for p in files:
        stem = p.name[len("cb_"):-len("_prediction.feather")]
        coin = stem.rsplit("_", 1)[0]
        pair = f"{coin.upper()}/USDT"
        try:
            df = pd.read_feather(p)
        except Exception:
            continue
        if df.empty:
            continue
        df = df.copy()
        df["pair"] = pair
        parts.append(df)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.normalize()
    out = out.sort_values(["pair", "date"]).drop_duplicates(["pair", "date"], keep="last")
    out = out.rename(columns={c: "pred" for c in out.columns if "s_close" in c and "mean" not in c and "std" not in c})
    return out


def _attach_preds(trades: pd.DataFrame, preds: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.assign(pred=np.nan, do_predict=np.nan, has_pred=False)
    t = trades.copy()
    t["pair"] = t["pair"].astype(str)
    t["signal_date"] = pd.to_datetime(t["signal_date"], utc=True).dt.normalize()
    if preds.empty:
        t["pred"] = np.nan
        t["do_predict"] = np.nan
        t["has_pred"] = False
        return t
    p = preds[["pair", "date", "pred", "do_predict"]].rename(columns={"date": "signal_date"})
    m = t.merge(p, on=["pair", "signal_date"], how="left")
    m["has_pred"] = m["pred"].notna()
    return m


def _profit_stats(df: pd.DataFrame) -> dict[str, Any]:
    if df is None or df.empty:
        return {"trades": 0, "win_rate": None, "total_profit_abs": 0.0, "profit_factor": None,
                "expectancy": None, "avg_profit_ratio": None, "max_drawdown_approx": None, "pass_rate": None}
    profits = df["profit_abs"].astype(float)
    ratios = df["profit_ratio"].astype(float) if "profit_ratio" in df.columns else None
    wins = profits[profits > 0].sum()
    losses = (-profits[profits <= 0]).sum()
    pf = float(wins / losses) if losses > 1e-12 else None
    ordered = df.sort_values("open_date") if "open_date" in df.columns else df
    cum = ordered["profit_abs"].astype(float).cumsum()
    dd = cum - cum.cummax()
    max_dd = float((-dd).max()) / 1000.0 if len(dd) else 0.0
    return {
        "trades": int(len(df)),
        "win_rate": float((profits > 0).mean()),
        "total_profit_abs": float(profits.sum()),
        "profit_factor": pf,
        "expectancy": float(profits.mean()),
        "avg_profit_ratio": float(ratios.mean()) if ratios is not None else None,
        "max_drawdown_approx": max_dd,
    }


def _score_on_date(pair: str, date, cache: dict) -> float | None:
    from score4window_scoring import apply_score4window_scores
    if pair not in cache:
        path = ROOT / "user_data" / "data" / "binance" / f"{pair.replace('/', '_')}-1d.feather"
        if not path.exists():
            cache[pair] = None
            return None
        df = pd.read_feather(path)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        cache[pair] = apply_score4window_scores(df)
    df = cache[pair]
    if df is None: return None
    d = pd.to_datetime(date, utc=True).normalize()
    sub = df[df["date"].dt.normalize() <= d]
    if sub.empty or "total_score" not in sub.columns: return None
    v = sub.iloc[-1]["total_score"]
    return float(v) if pd.notna(v) else None


def _btc_ret(date, cache: dict, lookback: int = 5) -> float | None:
    key = "BTC/USDT"
    if key not in cache:
        path = ROOT / "user_data" / "data" / "binance" / "BTC_USDT-1d.feather"
        if not path.exists(): return None
        df = pd.read_feather(path)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        cache[key] = df
    df = cache[key]
    d = pd.to_datetime(date, utc=True).normalize()
    sub = df[df["date"].dt.normalize() <= d]
    if len(sub) < lookback + 1: return None
    return float(sub.iloc[-1]["close"] / sub.iloc[-(lookback + 1)]["close"] - 1.0)


def main() -> int:
    if not MARKETS_PATH.exists():
        logger.error("missing %s", MARKETS_PATH)
        return 2
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    _patch_markets()

    a_zip = _run_export("A_trades", ROOT / "user_data" / "config.json", "Score4WindowStrategy", None)
    b_zip = _run_export("B_trades", ROOT / "user_data" / "config_freqai_dryrun.json", "Score4WindowFreqaiStrategy", "LightGBMRegressor")

    a_trades = _trades_from_zip(a_zip, "Score4WindowStrategy")
    b_trades = _trades_from_zip(b_zip, "Score4WindowFreqaiStrategy")
    logger.info("loaded A=%s B=%s trades", len(a_trades), len(b_trades))

    preds = _load_predictions()
    logger.info("preds rows=%s pairs=%s", len(preds), preds["pair"].nunique() if len(preds) else 0)

    a_m = _attach_preds(a_trades, preds)
    b_m = _attach_preds(b_trades, preds)

    a_win = a_m[a_m["open_date"] >= B_WINDOW_START].copy() if len(a_m) else a_m
    thr0 = 0.0
    a_win["b_pass"] = a_win["has_pred"] & (a_win["do_predict"] == 1) & (a_win["pred"] > thr0)
    filtered = a_win[a_win["has_pred"] & ~a_win["b_pass"]].copy()
    passed = a_win[a_win["b_pass"]].copy()
    missing = a_win[~a_win["has_pred"]].copy()

    reject_reasons = {
        "a_trades_in_b_window": int(len(a_win)),
        "missing_prediction": int(len(missing)),
        "do_predict_ne_1": int(((a_win["has_pred"]) & (a_win["do_predict"] != 1)).sum()) if len(a_win) else 0,
        "pred_le_threshold": int(((a_win["has_pred"]) & (a_win["do_predict"] == 1) & (a_win["pred"] <= thr0)).sum()) if len(a_win) else 0,
        "passed_gate": int(len(passed)),
        "filtered_by_gate": int(len(filtered)),
    }

    a_all_stats = _profit_stats(a_m)
    a_window_stats = _profit_stats(a_win)
    passed_stats = _profit_stats(passed)
    filtered_stats = _profit_stats(filtered)
    b_stats = _profit_stats(b_m)

    pred_win = preds[preds["date"] >= B_WINDOW_START] if len(preds) else preds
    pred_dist = {}
    if len(pred_win):
        s = pred_win["pred"].astype(float)
        pred_dist = {
            "n": int(len(s)), "mean": float(s.mean()), "std": float(s.std()),
            "p10": float(s.quantile(0.1)), "p25": float(s.quantile(0.25)),
            "p50": float(s.quantile(0.5)), "p75": float(s.quantile(0.75)), "p90": float(s.quantile(0.9)),
            "frac_gt_0": float((s > 0).mean()), "frac_gt_0_005": float((s > 0.005).mean()),
            "frac_gt_0_01": float((s > 0.01).mean()), "frac_lt_0": float((s < 0).mean()),
            "do_predict_1_frac": float((pred_win["do_predict"] == 1).mean()),
        }

    base = a_win[a_win["has_pred"] & (a_win["do_predict"] == 1)].copy()
    sweep = []
    for thr in [-0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02, 0.03, 0.05]:
        sub = base[base["pred"] > thr]
        st = _profit_stats(sub)
        st["threshold"] = thr
        st["pass_rate"] = float(len(sub) / len(base)) if len(base) else 0.0
        sweep.append(st)

    score_cache: dict = {}
    btc_cache: dict = {}
    def enrich(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        out = df.copy()
        out["entry_total_score"] = [_score_on_date(str(r.pair), r.signal_date, score_cache) for r in out.itertuples()]
        out["btc_ret_5d"] = [_btc_ret(r.signal_date, btc_cache, 5) for r in out.itertuples()]
        return out
    logger.info("enriching score/BTC context...")
    passed_e, filtered_e = enrich(passed), enrich(filtered)

    def cond_summary(df: pd.DataFrame) -> dict[str, Any]:
        if df.empty: return {"n": 0}
        return {
            "n": int(len(df)),
            "avg_pred": float(df["pred"].mean()),
            "avg_entry_score": float(pd.Series(df["entry_total_score"]).dropna().mean()),
            "avg_btc_ret_5d": float(pd.Series(df["btc_ret_5d"]).dropna().mean()),
            "avg_profit_ratio": float(df["profit_ratio"].mean()) if "profit_ratio" in df else None,
            "win_rate": float((df["profit_abs"] > 0).mean()),
            "score_ge_2_frac": float((pd.Series(df["entry_total_score"]).dropna() >= 2).mean()),
            "btc_down_frac": float((pd.Series(df["btc_ret_5d"]).dropna() < 0).mean()),
        }

    def exit_breakdown(df: pd.DataFrame) -> dict[str, int]:
        if df.empty or "exit_reason" not in df.columns: return {}
        return {str(k): int(v) for k, v in df["exit_reason"].value_counts().to_dict().items()}

    hold_vs_target = {}
    if len(a_m) and "trade_duration" in a_m.columns:
        dur_days = a_m["trade_duration"].astype(float) / (60 * 24)
        hold_vs_target = {
            "avg_hold_days": float(dur_days.mean()),
            "median_hold_days": float(dur_days.median()),
            "frac_hold_gt_1d": float((dur_days > 1).mean()),
            "frac_hold_ge_3d": float((dur_days >= 3).mean()),
            "roi_exit_frac": float((a_m["exit_reason"] == "roi").mean()) if "exit_reason" in a_m else None,
            "stoploss_exit_frac": float((a_m["exit_reason"] == "stop_loss").mean()) if "exit_reason" in a_m else None,
            "target_horizon_days": 1,
            "minimal_roi": {"0": 0.10},
            "stoploss": -0.10,
            "alignment_note": "Target=1d forward return; exits are ±10% ROI/SL over multi-day holds — horizon mismatch.",
        }

    n_a_all, n_a_win, n_pass, n_b = len(a_m), len(a_win), len(passed), len(b_m)
    drivers = []
    if n_a_all and (1 - n_a_win / n_a_all) > 0.3:
        drivers.append("FreqAI warmup shortens B's effective window vs A (large trade-count cut before AI gate).")
    if reject_reasons["pred_le_threshold"] >= reject_reasons["do_predict_ne_1"]:
        drivers.append("Among A entries with predictions, pred<=0 threshold rejects more than do_predict!=1.")
    else:
        drivers.append("do_predict/availability rejects are at least as large as threshold rejects.")
    if pred_dist.get("frac_gt_0") is not None and pred_dist["frac_gt_0"] < 0.55:
        drivers.append("Predictions are not strongly skewed positive; >0 threshold removes a large share.")
    if hold_vs_target.get("avg_hold_days", 0) > 2:
        drivers.append("1d forward-return target poorly aligned with multi-day ROI/SL exits — wrong learning horizon.")
    # Did filtered trades actually do well? If filtered had good expectancy, gate hurts.
    if filtered_stats["expectancy"] is not None and passed_stats["expectancy"] is not None:
        if filtered_stats["expectancy"] > passed_stats["expectancy"]:
            drivers.append("Filtered-out A trades had HIGHER expectancy than passed ones — gate removes good trades.")
        else:
            drivers.append("Gate prefers higher-expectancy subset among A entries, but still loses total profit via fewer trades / window cut.")

    root_cause = {
        "a_all_trades": n_a_all,
        "a_trades_in_b_effective_window": n_a_win,
        "window_reduction_frac": (1.0 - n_a_win / n_a_all) if n_a_all else None,
        "of_window_missing_pred_frac": (len(missing) / n_a_win) if n_a_win else None,
        "of_window_filtered_by_threshold_or_dopredict_frac": (len(filtered) / n_a_win) if n_a_win else None,
        "of_window_passed_frac": (n_pass / n_a_win) if n_a_win else None,
        "b_actual_trades": n_b,
        "primary_drivers": drivers,
    }

    report = {
        "task": "phase_a_model_b_failure_diagnosis",
        "frozen_A_unchanged": True,
        "phase_b_started": False,
        "zips": {"A": str(a_zip), "B": str(b_zip)},
        "a_all_stats": a_all_stats,
        "a_in_b_window_stats": a_window_stats,
        "a_passed_gate_stats": passed_stats,
        "a_filtered_by_gate_stats": filtered_stats,
        "b_actual_stats": b_stats,
        "reject_reasons": reject_reasons,
        "prediction_distribution_b_window": pred_dist,
        "threshold_sweep_on_a_window_entries": sweep,
        "passed_conditions": cond_summary(passed_e),
        "filtered_conditions": cond_summary(filtered_e),
        "exit_breakdown_A": exit_breakdown(a_m),
        "exit_breakdown_B": exit_breakdown(b_m),
        "hold_vs_target": hold_vs_target,
        "root_cause": root_cause,
        "b_avg_profit_ratio": float(b_m["profit_ratio"].mean()) if len(b_m) and "profit_ratio" in b_m else None,
        "a_window_avg_profit_ratio": float(a_win["profit_ratio"].mean()) if len(a_win) and "profit_ratio" in a_win else None,
        "passed_avg_profit_ratio": float(passed["profit_ratio"].mean()) if len(passed) and "profit_ratio" in passed else None,
        "filtered_avg_profit_ratio": float(filtered["profit_ratio"].mean()) if len(filtered) and "profit_ratio" in filtered else None,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")

    lines = [
        "# Phase A — Model B failure diagnosis",
        "",
        "Frozen A unchanged. Phase B not started. Diagnosis only.",
        "",
        "## Setup",
        f"- A: `{a_zip.name}` ({len(a_trades)} trades)",
        f"- B: `{b_zip.name}` ({len(b_trades)} trades)",
        f"- Predictions: {len(preds)} unique pair/date rows",
        "- Default B gate: `do_predict==1` and `pred > 0`",
        "- Filter study window: A trades with `open_date >= 2025-05-01`",
        "",
        "## 1) A trades B would filter (B window)",
        "",
        "| Set | trades | win_rate | profit_abs | PF | expectancy | avg_profit_ratio |",
        "|-----|--------|----------|------------|----|------------|------------------|",
        f"| A in B window | {a_window_stats['trades']} | {a_window_stats['win_rate']} | {a_window_stats['total_profit_abs']} | {a_window_stats['profit_factor']} | {a_window_stats['expectancy']} | {report['a_window_avg_profit_ratio']} |",
        f"| Would PASS gate | {passed_stats['trades']} | {passed_stats['win_rate']} | {passed_stats['total_profit_abs']} | {passed_stats['profit_factor']} | {passed_stats['expectancy']} | {report['passed_avg_profit_ratio']} |",
        f"| Filtered by gate | {filtered_stats['trades']} | {filtered_stats['win_rate']} | {filtered_stats['total_profit_abs']} | {filtered_stats['profit_factor']} | {filtered_stats['expectancy']} | {report['filtered_avg_profit_ratio']} |",
        f"| Missing prediction | {reject_reasons['missing_prediction']} | — | — | — | — | — |",
        "",
        "### Reject breakdown",
        "```json",
        json.dumps(reject_reasons, indent=2),
        "```",
        "",
        "## 2) B-selected vs A returns",
        f"- B actual avg profit_ratio: `{report['b_avg_profit_ratio']}`",
        f"- A (B window) avg profit_ratio: `{report['a_window_avg_profit_ratio']}`",
        f"- A∩pass-gate avg profit_ratio: `{report['passed_avg_profit_ratio']}`",
        f"- A∩filtered avg profit_ratio: `{report['filtered_avg_profit_ratio']}`",
        f"- B actual stats: `{json.dumps(b_stats)}`",
        "",
        "## 3) Prediction distribution (B window)",
        "```json",
        json.dumps(pred_dist, indent=2),
        "```",
        "",
        "## 4) Threshold sweep (A entries in B window with do_predict==1)",
        "",
        "| threshold | trades | pass_rate | profit_abs | PF | expectancy | approx_maxDD |",
        "|-----------|--------|-----------|------------|----|------------|--------------|",
    ]
    for st in sweep:
        lines.append(
            f"| {st['threshold']} | {st['trades']} | {st['pass_rate']:.3f} | {st['total_profit_abs']:.2f} | {st['profit_factor']} | {st['expectancy']} | {st['max_drawdown_approx']} |"
        )
    lines += [
        "",
        "## 5) Score / market conditions",
        "### Passed",
        "```json",
        json.dumps(report["passed_conditions"], indent=2),
        "```",
        "### Filtered",
        "```json",
        json.dumps(report["filtered_conditions"], indent=2),
        "```",
        "",
        "## 6) Low trade-count root cause",
        "```json",
        json.dumps(root_cause, indent=2),
        "```",
        "",
        "## 7) Target vs exit structure",
        "```json",
        json.dumps(hold_vs_target, indent=2),
        "```",
        f"- A exits: `{report['exit_breakdown_A']}`",
        f"- B exits: `{report['exit_breakdown_B']}`",
        "",
        "## Diagnosis summary",
    ]
    for d in drivers:
        lines.append(f"- {d}")
    lines += [
        "",
        "## Policy",
        "- No Phase B implementation.",
        "- Frozen A not modified.",
        "- Threshold sweep is diagnostic, not an optimization claim.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n")
    logger.info("wrote %s", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
