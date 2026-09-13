#!/usr/bin/env python3
"""
Offline Model B backtest (Phase A FreqAI). Baseline A is frozen.

Does NOT modify strategy code. Patches Exchange.reload_markets so backtesting
can use local OHLCV when Binance API returns 451.
"""

from __future__ import annotations

import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("phase_a_model_b")

TIMERANGE = "20240101-20260901"
MARKETS_PATH = Path("/tmp/offline_markets.json")
REPORT_MD = ROOT / "reports" / "phase_a_model_b_backtest.md"
REPORT_JSON = ROOT / "reports" / "phase_a_model_b_backtest.json"


def _patch_markets() -> None:
    from freqtrade.exchange.exchange import Exchange

    markets = json.loads(MARKETS_PATH.read_text())

    def reload_markets(self, force: bool = False, *, load_leverage_tiers: bool = True) -> None:  # noqa: ANN001
        logger.info("offline markets patch: loading %s local markets (no Binance HTTP)", len(markets))
        self._markets = markets
        # Keep ccxt objects in sync best-effort
        try:
            self._api.set_markets(markets)
        except Exception:
            pass
        try:
            self._api_async.set_markets(markets)
        except Exception:
            pass
        from freqtrade.util import dt_ts

        self._last_markets_refresh = dt_ts()

    Exchange.reload_markets = reload_markets  # type: ignore[method-assign]


def _base_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text())
    cfg["datadir"] = str(ROOT / "user_data" / "data" / "binance")
    cfg["user_data_dir"] = str(ROOT / "user_data")
    # Ensure strategy path resolution
    cfg.setdefault("add_config_files", [])
    return cfg


def _run_backtest(label: str, config_path: Path, strategy: str, freqaimodel: str | None = None) -> dict[str, Any]:
    from freqtrade.configuration import setup_utils_configuration
    from freqtrade.enums import RunMode
    from freqtrade.optimize.backtesting import Backtesting

    # Temporary runtime config copies (not committed strategy changes):
    # market exits require exit_pricing.price_side="other" for validation.
    cfg_obj = json.loads(config_path.read_text())
    cfg_obj.setdefault("exit_pricing", {})
    cfg_obj["exit_pricing"]["price_side"] = "other"
    cfg_obj["datadir"] = str(ROOT / "user_data" / "data" / "binance")
    cfg_obj["user_data_dir"] = str(ROOT / "user_data")
    tmp_cfg = Path(f"/tmp/phase_a_{label}_config.json")
    tmp_cfg.write_text(json.dumps(cfg_obj, indent=2))

    args: dict[str, Any] = {
        "config": [str(tmp_cfg)],
        "strategy": strategy,
        "strategy_path": str(ROOT / "user_data" / "strategies"),
        "timerange": TIMERANGE,
        "export": "none",
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

    bt = Backtesting(config)
    bt.start()
    results = getattr(bt, "results", None)
    out: dict[str, Any] = {
        "label": label,
        "strategy": strategy,
        "freqaimodel": freqaimodel,
        "config_used": str(tmp_cfg),
        "runtime_exit_pricing_override": {"price_side": "other"},
        "raw_keys": [],
    }
    if not results:
        out["error"] = "backtest produced empty results"
        return out
    if isinstance(results, dict):
        out["raw_keys"] = list(results.keys())
        out["results"] = results
    else:
        out["results"] = {"repr": repr(results)}
    return out


def _extract_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """Best-effort metric extraction across freqtrade result shapes."""
    res = payload.get("results") or {}
    metrics: dict[str, Any] = {
        "trades": None,
        "win_rate": None,
        "total_profit": None,
        "profit_pct": None,
        "profit_factor": None,
        "sharpe": None,
        "sortino": None,
        "max_drawdown": None,
        "avg_profit": None,
        "avg_duration": None,
        "notes": [],
    }

    # Common modern shape: strategy -> stats
    strategy = payload.get("strategy")
    if isinstance(res, dict) and strategy and strategy in res:
        block = res[strategy]
        if isinstance(block, dict):
            metrics["notes"].append("strategy_block")
            for k_src, k_dst in [
                ("total_trades", "trades"),
                ("trades", "trades"),
                ("wins", None),
                ("profit_total", "profit_pct"),
                ("profit_total_abs", "total_profit"),
                ("profit_factor", "profit_factor"),
                ("sharpe", "sharpe"),
                ("sortino", "sortino"),
                ("max_drawdown_account", "max_drawdown"),
                ("max_drawdown", "max_drawdown"),
                ("profit_mean", "avg_profit"),
                ("holding_avg", "avg_duration"),
            ]:
                if k_dst and k_src in block and metrics[k_dst] is None:
                    metrics[k_dst] = block[k_src]
            # win rate
            if "winrate" in block:
                metrics["win_rate"] = block["winrate"]
            elif "wins" in block and "total_trades" in block and block["total_trades"]:
                metrics["win_rate"] = block["wins"] / block["total_trades"]

    # Fallback: results['results_per_pair'] / strategy comparison dict
    if metrics["trades"] is None and isinstance(res, dict):
        # Sometimes key is strategy name under 'strategy'
        strat_map = res.get("strategy")
        if isinstance(strat_map, dict):
            block = next(iter(strat_map.values())) if strat_map else None
            if isinstance(block, dict):
                metrics["notes"].append("results.strategy.*")
                metrics["trades"] = block.get("total_trades", metrics["trades"])
                metrics["profit_pct"] = block.get("profit_total", metrics["profit_pct"])
                metrics["total_profit"] = block.get("profit_total_abs", metrics["total_profit"])
                metrics["profit_factor"] = block.get("profit_factor", metrics["profit_factor"])
                metrics["sharpe"] = block.get("sharpe", metrics["sharpe"])
                metrics["sortino"] = block.get("sortino", metrics["sortino"])
                metrics["max_drawdown"] = block.get(
                    "max_drawdown_account", block.get("max_drawdown", metrics["max_drawdown"])
                )
                metrics["avg_profit"] = block.get("profit_mean", metrics["avg_profit"])
                metrics["avg_duration"] = block.get("holding_avg", metrics["avg_duration"])
                if "winrate" in block:
                    metrics["win_rate"] = block["winrate"]

    return metrics

import time

COMPARE_MD = ROOT / "reports" / "phase_a_a_vs_b_comparison.md"
COMPARE_JSON = ROOT / "reports" / "phase_a_a_vs_b_comparison.json"
FROZEN_A_PATH = ROOT / "reports" / "phase_a_baseline_a_after_top15_fix.json"


def _load_frozen_a() -> dict[str, Any]:
    frozen = {
        "strategy": "Score4WindowStrategy",
        "effective_timerange": "2024-08-16 → 2026-09-01",
        "timeframe": "1d",
        "trades": 2426,
        "win_rate": 0.5259686727122836,
        "profit_pct": 0.26674261335,
        "total_profit": 266.74261335,
        "profit_factor": 1.1943710964452867,
        "sharpe": 4.707412131765382,
        "sortino": 10.930170809302597,
        "max_drawdown": 0.0896481513559791,
        "avg_profit": 0.004351618828462857,
        "avg_duration": "3 days, 17:32:00",
        "expectancy": 266.74261335 / 2426.0,
        "fees": None,
    }
    if FROZEN_A_PATH.exists():
        try:
            payload = json.loads(FROZEN_A_PATH.read_text())
            m = (payload.get("run") or {}).get("metrics") or payload.get("metrics") or {}
            for k in (
                "trades", "win_rate", "total_profit", "profit_pct", "profit_factor",
                "sharpe", "sortino", "max_drawdown", "avg_profit", "avg_duration",
            ):
                if m.get(k) is not None:
                    frozen[k] = m[k]
            ss = (payload.get("run") or {}).get("strategy_stats") or {}
            if ss.get("backtest_start") and ss.get("backtest_end"):
                frozen["effective_timerange"] = f"{ss['backtest_start']} → {ss['backtest_end']}"
            if frozen.get("total_profit") is not None and frozen.get("trades"):
                frozen["expectancy"] = float(frozen["total_profit"]) / float(frozen["trades"])
        except Exception as exc:  # noqa: BLE001
            frozen["load_warning"] = str(exc)
    return frozen


def _enrich_b_metrics(payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    res = payload.get("results") or {}
    strategy = payload.get("strategy")
    block = None
    if isinstance(res, dict) and strategy and isinstance(res.get(strategy), dict):
        block = res[strategy]
    elif isinstance(res, dict) and isinstance(res.get("strategy"), dict) and res["strategy"]:
        block = next(iter(res["strategy"].values()))
    if not isinstance(block, dict):
        return metrics
    # Alias keys used by _extract_metrics vs report names
    if metrics.get("win_rate") is None and metrics.get("win_rate") is not None:
        pass
    if "win_rate" not in metrics and metrics.get("win_rate") is None:
        # _extract_metrics uses win_rate already
        pass
    # Map extract keys into canonical report keys
    if "total_profit" not in metrics and metrics.get("total_profit") is None:
        metrics["total_profit"] = metrics.get("total_profit")
    # Prefer extract fields; add extras
    if block.get("expectancy") is not None:
        metrics["expectancy"] = block["expectancy"]
    trades = block.get("trades")
    if hasattr(trades, "empty"):
        try:
            if not trades.empty:
                fee_cols = [c for c in trades.columns if "fee" in str(c).lower()]
                if fee_cols:
                    metrics["fees"] = float(trades[fee_cols].sum(numeric_only=True).sum())
                if metrics.get("expectancy") is None and "profit_abs" in trades.columns:
                    metrics["expectancy"] = float(trades["profit_abs"].mean())
        except Exception as exc:  # noqa: BLE001
            metrics.setdefault("notes", []).append(f"enrich_error={exc}")
    if metrics.get("expectancy") is None and metrics.get("total_profit") and metrics.get("trades"):
        metrics["expectancy"] = float(metrics["total_profit"]) / float(metrics["trades"])
    metrics["backtest_start"] = block.get("backtest_start")
    metrics["backtest_end"] = block.get("backtest_end")
    return metrics


def _compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    # Normalize B keys from _extract_metrics naming
    b_norm = {
        "trades": b.get("trades"),
        "win_rate": b.get("win_rate"),
        "profit_pct": b.get("profit_pct"),
        "total_profit": b.get("total_profit"),
        "profit_factor": b.get("profit_factor"),
        "expectancy": b.get("expectancy"),
        "max_drawdown": b.get("max_drawdown"),
        "sharpe": b.get("sharpe"),
        "sortino": b.get("sortino"),
        "avg_profit": b.get("avg_profit"),
        "fees": b.get("fees"),
        "avg_duration": b.get("avg_duration"),
    }
    keys = list(b_norm.keys())
    rows = [{"metric": k, "A": a.get(k), "B": b_norm.get(k)} for k in keys]
    notes: list[str] = []
    at, bt = a.get("trades"), b_norm.get("trades")
    ap, bp = a.get("profit_pct"), b_norm.get("profit_pct")
    add, bdd = a.get("max_drawdown"), b_norm.get("max_drawdown")
    if bt is None:
        notes.append("B metrics incomplete.")
    else:
        if at and bt < 0.25 * float(at):
            notes.append(f"B trades ({bt}) <25% of A ({at}) — gate may be overly strict.")
        if at and bt > 1.5 * float(at):
            notes.append(f"B trades ({bt}) >150% of A ({at}) — check whether AI gate binds.")
        if bdd is not None and add is not None and float(bdd) > float(add) * 1.25:
            notes.append(f"B max drawdown ({bdd}) materially worse than A ({add}).")
        if bp is not None and ap is not None:
            if float(bp) > float(ap):
                notes.append(
                    "B profit > A profit — NOT automatic Phase A success; "
                    "weigh trades, drawdown, robustness."
                )
            else:
                notes.append("B profit ≤ A profit under identical timerange/stake/fee settings.")
    verdict = "INCONCLUSIVE"
    reason = "Insufficient basis for Phase A go/no-go."
    if bt is not None and bp is not None and ap is not None:
        robust_ok = True
        if at and bt < 0.25 * float(at):
            robust_ok = False
        if bdd is not None and add is not None and float(bdd) > float(add) * 1.5:
            robust_ok = False
        if float(bp) > float(ap) and robust_ok:
            verdict = "B_LOOKS_BETTER_BUT_NOT_AUTO_SUCCESS"
            reason = (
                "B beat A on profit without catastrophic trade-count/DD collapse; "
                "still NOT Phase B approval — human review required."
            )
        elif float(bp) <= float(ap) and robust_ok:
            verdict = "A_STILL_AHEAD"
            reason = "Under identical conditions A remains ahead on profit; B not an upgrade."
        elif not robust_ok:
            verdict = "B_NOT_ROBUST"
            reason = "B shows fragility (trade collapse and/or much worse drawdown)."
    return {"rows": rows, "verdict": verdict, "reason": reason, "notes": notes}


def main() -> int:
    if not MARKETS_PATH.exists():
        logger.error("missing %s — generate offline markets first", MARKETS_PATH)
        return 2

    _patch_markets()

    data_dir = ROOT / "user_data" / "data" / "binance"
    feathers = list(data_dir.glob("*-1d.feather"))
    data_summary = {
        "datadir": str(data_dir),
        "n_1d_files": len(feathers),
        "timerange_requested": TIMERANGE,
        "note": (
            "Local 1d OHLCV starts ~2024-07-05 for most pairs; requested timerange "
            "20240101-20260901 is clipped by available history. No Binance download attempted."
        ),
    }

    logger.info("=== BACKTEST B ONLY: Score4WindowFreqaiStrategy + LightGBMRegressor ===")
    t0 = time.time()
    try:
        b = _run_backtest(
            "B_freqai",
            ROOT / "user_data" / "config_freqai_dryrun.json",
            "Score4WindowFreqaiStrategy",
            "LightGBMRegressor",
        )
        b["elapsed_sec"] = time.time() - t0
        metrics = _extract_metrics(b)
        b["metrics"] = _enrich_b_metrics(b, metrics)
    except Exception as e:
        logger.exception("Backtest B failed")
        b = {
            "label": "B_freqai",
            "strategy": "Score4WindowFreqaiStrategy",
            "freqaimodel": "LightGBMRegressor",
            "error": f"{type(e).__name__}: {e}",
            "elapsed_sec": time.time() - t0,
            "metrics": {},
        }

    a = _load_frozen_a()
    compare = _compare(a, b.get("metrics") or {}) if b.get("metrics") else {
        "rows": [],
        "verdict": "INCONCLUSIVE",
        "reason": b.get("error") or "B failed",
        "notes": [],
    }

    slim_b = {k: v for k, v in b.items() if k != "results"}
    res = b.get("results")
    if isinstance(res, dict):
        slim_b["raw_keys"] = list(res.keys())
        # Keep compact strategy stats only
        strat_map = res.get("strategy") if isinstance(res.get("strategy"), dict) else None
        if strat_map is None and b.get("strategy") in res and isinstance(res[b["strategy"]], dict):
            strat_map = {b["strategy"]: res[b["strategy"]]}
        if isinstance(strat_map, dict) and strat_map:
            sname, block = next(iter(strat_map.items()))
            if isinstance(block, dict):
                keep = [
                    "total_trades", "wins", "losses", "draws", "winrate",
                    "profit_total", "profit_total_abs", "profit_factor",
                    "sharpe", "sortino", "max_drawdown", "max_drawdown_account",
                    "profit_mean", "holding_avg", "expectancy",
                    "backtest_start", "backtest_end", "starting_balance", "final_balance",
                ]
                slim_b["strategy_stats"] = {k: block.get(k) for k in keep if k in block}

    report = {
        "task": "phase_a_model_b_backtest",
        "timerange_requested": TIMERANGE,
        "data": data_summary,
        "offline_markets_patch": True,
        "frozen_A": a,
        "B": slim_b,
        "comparison": compare,
        "baseline_A_modified": False,
        "params_tuned": False,
        "phase_b_started": False,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")

    bm = b.get("metrics") or {}
    lines = [
        "# Phase A — Model B backtest (FreqAI gate)",
        "",
        f"- Timerange requested: `{TIMERANGE}`",
        "- Strategy: `Score4WindowFreqaiStrategy` + `LightGBMRegressor`",
        f"- Elapsed: `{slim_b.get('elapsed_sec')}` sec",
        "- Drop-exit: OFF; historical candle Top-15 entry gate: ON",
        "- Baseline A: frozen (not re-run / not optimized)",
        "",
        "## B metrics",
        "",
    ]
    for k in [
        "trades", "win_rate", "total_profit", "profit_pct", "profit_factor",
        "expectancy", "max_drawdown", "sharpe", "sortino", "avg_profit",
        "fees", "avg_duration", "backtest_start", "backtest_end",
    ]:
        lines.append(f"- {k}: `{bm.get(k)}`")
    if b.get("error"):
        lines.append(f"- ERROR: `{b['error']}`")
    lines.extend(["", "## Frozen A (reference)", ""])
    for k, v in a.items():
        lines.append(f"- {k}: `{v}`")
    REPORT_MD.write_text("\n".join(lines) + "\n")

    c_lines = [
        "# Phase A — Model A vs Model B",
        "",
        f"**Verdict:** `{compare['verdict']}`",
        "",
        compare["reason"],
        "",
        "| Metric | Model A (frozen) | Model B (FreqAI) |",
        "|--------|------------------|------------------|",
    ]
    for row in compare["rows"]:
        c_lines.append(f"| {row['metric']} | {row['A']} | {row['B']} |")
    c_lines.extend(["", "## Robustness notes", ""])
    for n in compare["notes"]:
        c_lines.append(f"- {n}")
    c_lines.extend([
        "",
        "## Policy",
        "",
        "- Higher B profit is **not** automatic Phase A success.",
        "- Phase B must not start until Model B is reviewed.",
        "- Baseline A was not modified or re-optimized.",
        "",
    ])
    COMPARE_MD.write_text("\n".join(c_lines) + "\n")
    COMPARE_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")

    logger.info("wrote %s", REPORT_MD)
    logger.info("wrote %s", COMPARE_MD)
    logger.info("VERDICT: %s", compare["verdict"])
    return 0 if "error" not in b else 1


if __name__ == "__main__":
    raise SystemExit(main())
