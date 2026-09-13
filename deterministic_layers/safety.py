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
    Freqtrade forbids max_open_trades=-1 together with stake_amount=unlimited.

    For dry-run research we use a very high finite cap (e.g. 1_000_000) so
    stuck/unfilled open trades cannot exhaust entry slots, while
    stake_amount stays unlimited for risk_pct sizing. Temporary observation
    configs may also set active_universe.top_n to 1_000_000 (no Top-15 cut).

    max_open_trades=-1 remains dry-run-only if ever used with a fixed stake.
    """
    max_ot = config.get("max_open_trades")
    stake = config.get("stake_amount")
    stake_unlimited = stake == "unlimited" or stake is None
    if max_ot == -1 and stake_unlimited:
        raise RuntimeError(
            "safety abort: max_open_trades and stake_amount cannot both be "
            "unlimited (Freqtrade). Use a finite max_open_trades "
            "(e.g. 1000000) when stake_amount='unlimited'."
        )
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
