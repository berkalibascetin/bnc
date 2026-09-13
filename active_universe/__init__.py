"""
Active trading universe: only the current top-N ranked pairs may open trades.

Pre-AI volume control for dry-run research:
  - Rank the full whitelist via score_scan (final_score, else Score4Window)
  - Keep top_n (default 15)
  - Refresh every refresh_minutes (default 30)
  - Optionally exit when a pair drops out of the top-N

Does not place orders itself. Never flips dry_run.
"""

from __future__ import annotations

from active_universe.manager import (
    DEFAULT_REFRESH_MINUTES,
    DEFAULT_TOP_N,
    ActiveUniverseState,
    load_active_universe_settings,
    refresh_active_universe,
    select_top_pairs,
    should_refresh,
)

__all__ = [
    "DEFAULT_REFRESH_MINUTES",
    "DEFAULT_TOP_N",
    "ActiveUniverseState",
    "load_active_universe_settings",
    "refresh_active_universe",
    "select_top_pairs",
    "should_refresh",
]
