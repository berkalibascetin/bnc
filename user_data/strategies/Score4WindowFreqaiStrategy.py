"""
Score4WindowFreqaiStrategy — Phase A FreqAI gate on top of Score4Window.

Keeps:
  - Score4Window scoring (via shared score4window_scoring)
  - deterministic leaderboard / score_scan (unchanged)
  - active Top-15 as ENTRY-only gate (drop-exit OFF by default)

Adds:
  - leakage-safe FreqAI features (pair-local deterministic + simple market)
  - regression target: forward return
  - entry = Top-15 AND baseline score AND FreqAI prediction gate

Does NOT:
  - rewrite Score4Window / layer weights
  - use S1/S2/rank/in_top15 as FreqAI features (Phase B)
  - AI exits
  - live trading (config must keep dry_run=true)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Project root on sys.path so deterministic_layers imports resolve under freqtrade.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter

from deterministic_layers.pair_local_features import attach_phase_a_deterministic_columns
from score4window_scoring import apply_score4window_scores

# Import base under a private name so freqtrade strategy discovery does not
# register Score4WindowStrategy twice from this module.
from Score4WindowStrategy import Score4WindowStrategy as _Score4WindowBase

logger = logging.getLogger(__name__)

# Default prediction gate: require strictly positive expected forward return.
# Not claimed optimal — tune after Model A vs B measurement.
DEFAULT_PREDICTION_THRESHOLD = 0.0


class Score4WindowFreqaiStrategy(_Score4WindowBase):
    """Score4Window baseline + Top-15 entry gate + FreqAI prediction gate."""

    STRATEGY_ID = "SCORE_4WINDOW_FREQAI_PHASE_A"
    startup_candle_count: int = 120

    prediction_threshold = DecimalParameter(
        -0.05,
        0.10,
        default=DEFAULT_PREDICTION_THRESHOLD,
        decimals=4,
        space="buy",
        optimize=False,
        load=True,
    )

    plot_config = {
        "main_plot": {},
        "subplots": {
            "score": {
                "total_score": {"color": "blue"},
                "dl_final_score": {"color": "purple"},
            },
            "freqai": {
                "&-s_close": {"color": "green"},
                "do_predict": {"color": "orange"},
            },
        },
    }

    def _prediction_threshold(self) -> float:
        block = (self.config or {}).get("freqai_phase_a") or {}
        if "prediction_threshold" in block:
            return float(block["prediction_threshold"])
        return float(self.prediction_threshold.value)

    def _leader_closes(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.dp is None:
            return out
        for pair in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            try:
                df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                if df is None or df.empty:
                    raw = self.dp.get_pair_dataframe(pair=pair, timeframe=self.timeframe)
                    if raw is None or raw.empty:
                        continue
                    out[pair] = raw["close"].copy()
                else:
                    out[pair] = df["close"].copy()
            except Exception:
                continue
        return out

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-atr_pct-period"] = (
            ta.ATR(dataframe, timeperiod=period) / dataframe["close"]
        ) * 100.0
        dataframe["%-volatility-period"] = (
            dataframe["close"].pct_change().rolling(period).std() * 100.0
        )
        ema = ta.EMA(dataframe, timeperiod=period)
        dataframe["%-ema_slope-period"] = (ema / ema.shift(1) - 1.0) * 100.0
        dataframe["%-rel_volume-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-return_1"] = dataframe["close"].pct_change()
        dataframe["%-volume_change_1"] = dataframe["volume"].pct_change()
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """Pair-local deterministic features only (no S1/S2/rank/top15)."""
        dataframe = apply_score4window_scores(
            dataframe,
            window_1w=int(self.window_1w.value),
            window_2w=int(self.window_2w.value),
            window_1m=int(self.window_1m.value),
            window_2m=int(self.window_2m.value),
        )
        dataframe = attach_phase_a_deterministic_columns(
            dataframe,
            total_score_col="total_score",
            leader_closes=self._leader_closes(),
        )
        dataframe["%-score4window_score"] = dataframe["total_score"].astype(float)
        dataframe["%-main"] = dataframe["dl_main"].astype(float)
        dataframe["%-s3"] = dataframe["dl_s3"].astype(float)
        dataframe["%-s4"] = dataframe["dl_s4"].astype(float)
        dataframe["%-s7"] = dataframe["dl_s7"].astype(float)
        dataframe["%-final_score"] = dataframe["dl_final_score"].astype(float)
        if "date" in dataframe.columns:
            dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek
            dataframe["%-month"] = dataframe["date"].dt.month
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """Forward return target; shift(-N) only on the label column."""
        freqai = self.freqai_info if hasattr(self, "freqai_info") else {}
        feature_params = (freqai or {}).get("feature_parameters") or {}
        label_period = int(
            feature_params.get(
                "label_period_candles",
                ((self.config or {}).get("freqai") or {})
                .get("feature_parameters", {})
                .get("label_period_candles", 1),
            )
        )
        label_period = max(1, label_period)
        dataframe["&-s_close"] = (
            dataframe["close"].shift(-label_period) / dataframe["close"] - 1.0
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe = attach_phase_a_deterministic_columns(
            dataframe,
            total_score_col="total_score",
            leader_closes=self._leader_closes(),
        )
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        threshold = int(self.entry_score_threshold.value)
        pred_thr = self._prediction_threshold()
        score_cond = (
            (dataframe["total_score"] >= threshold)
            & (dataframe["total_score"].notna())
            & (dataframe["volume"] > 0)
        )
        if "&-s_close" in dataframe.columns and "do_predict" in dataframe.columns:
            ai_cond = (dataframe["do_predict"] == 1) & (dataframe["&-s_close"] > pred_thr)
        else:
            ai_cond = False
        entry_cond = score_cond & ai_cond
        # Historical candle-causal Top-15 in backtest/hyperopt; live snapshot otherwise.
        pair = str(metadata.get("pair") or "")
        if pair and self._active_universe_enabled():
            if self._use_historical_top15_gate():
                from active_universe.historical import membership_series_for_pair

                membership = self._ensure_historical_top15()
                in_top = membership_series_for_pair(
                    membership, pair, dataframe["date"]
                )
                entry_cond = entry_cond & in_top.to_numpy()
            elif not self._pair_in_active_universe(pair):
                entry_cond = entry_cond & False
        dataframe.loc[entry_cond, "enter_long"] = 1
        tag = (
            "s4w_"
            + dataframe["total_score"].fillna(0).astype(int).astype(str)
            + "|ai"
        )
        dataframe.loc[entry_cond, "enter_tag"] = tag[entry_cond]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        return dataframe

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        # Top-15: same candle-causal / live logic as baseline A (do not regress).
        if not super().confirm_trade_entry(
            pair,
            order_type,
            amount,
            rate,
            time_in_force,
            current_time,
            entry_tag,
            side,
            **kwargs,
        ):
            return False

        # Backtest: AI gate already applied per-candle in populate_entry_trend.
        if self._use_historical_top15_gate():
            return True

        # Live / dry-run: defense-in-depth AI + score check on latest candle.
        dataframe, _ = (
            self.dp.get_analyzed_dataframe(pair, self.timeframe) if self.dp else (None, None)
        )
        last = dataframe.iloc[-1] if dataframe is not None and not dataframe.empty else None
        total = float(last.get("total_score", float("nan"))) if last is not None else float("nan")
        final = float(last.get("dl_final_score", float("nan"))) if last is not None else float("nan")
        pred = float(last.get("&-s_close", float("nan"))) if last is not None else float("nan")
        do_pred = int(last.get("do_predict", 0)) if last is not None else 0
        pred_thr = self._prediction_threshold()
        baseline_ok = (not np.isnan(total)) and total >= int(self.entry_score_threshold.value)
        ai_ok = do_pred == 1 and (not np.isnan(pred)) and pred > pred_thr
        allow = bool(baseline_ok and ai_ok)
        logger.info(
            "freqai_phase_a decision pair=%s total_score=%s final_score=%s "
            "prediction=%s do_predict=%s threshold=%s entry=%s tag=%s",
            pair,
            total,
            final,
            pred,
            do_pred,
            pred_thr,
            allow,
            entry_tag,
        )
        return allow


# Avoid duplicate IStrategy discovery of the imported base class.
del _Score4WindowBase
