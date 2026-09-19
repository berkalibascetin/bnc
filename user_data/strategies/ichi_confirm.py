"""Causal Ichimoku helpers for Score4Window confirmation filters."""

from __future__ import annotations

from typing import Any

from pandas import DataFrame


def ichimoku_leading(
    dataframe: DataFrame,
    *,
    conversion_line_period: int = 9,
    base_line_periods: int = 26,
    laggin_span: int = 52,
) -> dict[str, Any]:
    """
    Causal Ichimoku components for machine checks.

    Returns tenkan/kijun plus *leading* senkou spans (not forward-shifted).
    Do not use chikou_span for entries (lookahead / unavailable live).
    """
    tenkan = (
        dataframe["high"].rolling(window=conversion_line_period).max()
        + dataframe["low"].rolling(window=conversion_line_period).min()
    ) / 2.0
    kijun = (
        dataframe["high"].rolling(window=base_line_periods).max()
        + dataframe["low"].rolling(window=base_line_periods).min()
    ) / 2.0
    leading_a = (tenkan + kijun) / 2.0
    leading_b = (
        dataframe["high"].rolling(window=laggin_span).max()
        + dataframe["low"].rolling(window=laggin_span).min()
    ) / 2.0
    return {
        "tenkan_sen": tenkan,
        "kijun_sen": kijun,
        "leading_senkou_span_a": leading_a,
        "leading_senkou_span_b": leading_b,
        "cloud_green": leading_a > leading_b,
    }


def crossed_below(series_a, series_b):
    return (series_a < series_b) & (series_a.shift(1) >= series_b.shift(1))
