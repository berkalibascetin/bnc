"""S4 — On-chain support (0..10). Provider-agnostic; no fake data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from deterministic_layers.weights import WEIGHTS

S4_MAX = WEIGHTS["s4"]  # 10
S4_NEUTRAL = S4_MAX / 2.0  # 5.0 — used when unavailable so other layers aren't punished


class OnchainProvider(Protocol):
    def score_pair(self, pair: str) -> OnchainResult: ...


@dataclass(frozen=True)
class OnchainResult:
    s4_score: float | None
    status: str  # ok | unavailable | insufficient_data | error
    detail: str | None = None


class UnavailableOnchainProvider:
    """Default provider — honest about missing on-chain feeds."""

    def score_pair(self, pair: str) -> OnchainResult:
        return OnchainResult(
            s4_score=None,
            status="unavailable",
            detail="no_onchain_provider_configured",
        )


def s4_points(pair: str, provider: OnchainProvider | None = None) -> OnchainResult:
    """
    Return on-chain points for `pair`.

    If provider is missing/unavailable → status=unavailable, s4_score=None.
    Callers should treat unavailable as neutral (S4_NEUTRAL) for final_score math
    without labeling the coin as bad.
    """
    prov = provider or UnavailableOnchainProvider()
    return prov.score_pair(pair)


def s4_contribution_for_final(result: OnchainResult) -> float:
    """Map S4 result into final_score contribution without punishing unavailability."""
    if result.status == "unavailable" or result.s4_score is None:
        return float(S4_NEUTRAL)
    return float(max(0.0, min(S4_MAX, result.s4_score)))
