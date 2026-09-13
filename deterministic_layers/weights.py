"""Target component weights (sum = 100)."""

from __future__ import annotations

WEIGHTS = {
    "main": 30.0,
    "s1": 20.0,
    "s2": 15.0,
    "s3": 15.0,
    "s4": 10.0,
    "s7": 10.0,
}

assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9
