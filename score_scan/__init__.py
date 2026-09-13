"""
Observation-only Score4Window score scan layer.

Never places orders. Never flips dry_run to live. Does not change strategy logic.
"""

from __future__ import annotations

__all__ = ["DEFAULT_MODE", "MODES", "normalize_mode"]

MODES = ("off", "force", "hourly")
DEFAULT_MODE = "off"


def normalize_mode(value: str | None) -> str:
    mode = (value or DEFAULT_MODE).strip().lower()
    if mode not in MODES:
        raise ValueError(f"Invalid score-scan mode {value!r}; expected one of {MODES}")
    return mode
