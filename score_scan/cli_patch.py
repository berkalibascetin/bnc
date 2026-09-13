"""
Register ``--score-scan`` on Freqtrade's trade CLI without forking Freqtrade core.

Usage (drop-in):
  python -m score_scan trade -c user_data/config.json --strategy Score4WindowStrategy ...

Also usable by importing ``apply_freqtrade_cli_patch()`` before ``freqtrade.main``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from score_scan import DEFAULT_MODE, MODES, normalize_mode

logger = logging.getLogger(__name__)

_PATCHED = False


def apply_freqtrade_cli_patch() -> None:
    """Idempotently add --score-scan to Freqtrade trade arguments."""
    global _PATCHED
    if _PATCHED:
        return

    from freqtrade.commands.arguments import ARGS_TRADE
    from freqtrade.commands.cli_options import AVAILABLE_CLI_OPTIONS, Arg

    if "score_scan" not in AVAILABLE_CLI_OPTIONS:
        AVAILABLE_CLI_OPTIONS["score_scan"] = Arg(
            "--score-scan",
            help=(
                "Observation-only Score4Window market score scan mode: "
                "off (default), force (once at startup), hourly (max once per hour). "
                "Never places orders; requires dry_run=true."
            ),
            type=str,
            choices=list(MODES),
            default=DEFAULT_MODE,
            metavar="MODE",
        )
    if "score_scan" not in ARGS_TRADE:
        ARGS_TRADE.append("score_scan")

    # Ensure Configuration copies CLI value into config dict.
    _patch_configuration_process()
    _PATCHED = True


def _patch_configuration_process() -> None:
    from freqtrade.configuration.configuration import Configuration

    if getattr(Configuration, "_score_scan_patched", False):
        return

    original = Configuration._process_trading_options

    def _process_trading_options(self, config: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
        original(self, config)
        inject_score_scan_into_config(config, getattr(self, "args", {}) or {})

    Configuration._process_trading_options = _process_trading_options  # type: ignore[method-assign]
    Configuration._score_scan_patched = True  # type: ignore[attr-defined]


def inject_score_scan_into_config(config: dict[str, Any], args: dict[str, Any] | None = None) -> str:
    """
    Resolve score_scan mode from CLI args or config; never alters dry_run/whitelist/risk.
    """
    args = args or {}
    raw = args.get("score_scan")
    if raw is None:
        raw = config.get("score_scan", DEFAULT_MODE)
    mode = normalize_mode(str(raw))
    config["score_scan"] = mode
    # Hard safety: scanner path must never coerce live trading.
    if config.get("dry_run") is not True:
        logger.error(
            "score_scan=%s requested but dry_run=%r — scan hooks will no-op for safety",
            mode,
            config.get("dry_run"),
        )
    return mode


def main(argv: list[str] | None = None) -> int:
    """CLI entry: patch Freqtrade then dispatch to freqtrade.main."""
    apply_freqtrade_cli_patch()
    argv = list(sys.argv[1:] if argv is None else argv)
    # freqtrade.main reads sys.argv
    sys.argv = ["freqtrade", *argv]
    from freqtrade import main as ft_main

    return int(ft_main.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
