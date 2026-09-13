"""Dry-run / research-mode safety guards."""

from __future__ import annotations

from typing import Any


def assert_dry_run_true(config: dict[str, Any]) -> None:
    """Hard require dry_run=true. Never coerce it to false."""
    if config.get("dry_run") is not True:
        raise RuntimeError(
            "safety abort: dry_run must be true "
            f"(got {config.get('dry_run')!r}). Refusing to continue."
        )


def assert_max_open_trades_research_safe(config: dict[str, Any]) -> None:
    """
    max_open_trades=-1 (unlimited) is research/dry-run only.

    Live configs must not use unlimited open trades via this research setting.
    """
    max_ot = config.get("max_open_trades")
    if max_ot == -1 and config.get("dry_run") is not True:
        raise RuntimeError(
            "safety abort: max_open_trades=-1 is only allowed when dry_run=true "
            f"(dry_run={config.get('dry_run')!r})."
        )


def validate_research_trading_config(config: dict[str, Any]) -> None:
    """Combined research-mode validation. Does not mutate config."""
    assert_dry_run_true(config)
    assert_max_open_trades_research_safe(config)
    # Belt-and-suspenders: never allow this layer to flip dry_run.
    if config.get("dry_run") is False:
        raise RuntimeError("safety abort: dry_run=false is forbidden in this phase")
