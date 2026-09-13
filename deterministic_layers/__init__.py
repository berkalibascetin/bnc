"""
Deterministic post-Score4Window scoring layers (no AI / no FreqAI).

MAIN + S1 + S2 + S3 + S4 + S7 → final_score in [0, 100].

Observation / ranking only — does not replace Score4Window entry logic.
"""

from __future__ import annotations

from deterministic_layers.composite import ComponentScores, score_universe
from deterministic_layers.safety import (
    assert_dry_run_true,
    assert_max_open_trades_research_safe,
    validate_research_trading_config,
)
from deterministic_layers.weights import WEIGHTS

__all__ = [
    "WEIGHTS",
    "ComponentScores",
    "assert_dry_run_true",
    "assert_max_open_trades_research_safe",
    "score_universe",
    "validate_research_trading_config",
]
