"""Active top-N universe manager (pre-AI selection)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 15
DEFAULT_REFRESH_MINUTES = 30
# Generic name — not tied to Top-15 (top_n may be 15 or 1_000_000).
DEFAULT_REPORT_NAME = "active_universe_latest.json"


@dataclass
class ActiveUniverseState:
    enabled: bool = True
    top_n: int = DEFAULT_TOP_N
    refresh_minutes: int = DEFAULT_REFRESH_MINUTES
    exit_when_dropped: bool = True
    pairs: list[str] = field(default_factory=list)
    ranks: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float | None] = field(default_factory=dict)
    refreshed_at: str | None = None
    next_refresh_at: str | None = None

    def as_set(self) -> set[str]:
        return set(self.pairs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_active_universe_settings(config: dict[str, Any]) -> dict[str, Any]:
    if "active_universe" not in config:
        # Absent from config → off (unit tests / minimal configs).
        return {
            "enabled": False,
            "top_n": DEFAULT_TOP_N,
            "refresh_minutes": DEFAULT_REFRESH_MINUTES,
            "exit_when_dropped": True,
            "reports_dir": "reports",
        }
    block = config.get("active_universe") or {}
    return {
        "enabled": bool(block.get("enabled", True)),
        "top_n": int(block.get("top_n", DEFAULT_TOP_N)),
        "refresh_minutes": int(block.get("refresh_minutes", DEFAULT_REFRESH_MINUTES)),
        "exit_when_dropped": bool(block.get("exit_when_dropped", True)),
        "reports_dir": block.get("reports_dir") or "reports",
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except ValueError:
        return None


def should_refresh(state: ActiveUniverseState, now: datetime, refresh_minutes: int) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    last = _parse_ts(state.refreshed_at)
    if last is None:
        return True
    return (now - last).total_seconds() >= max(1, int(refresh_minutes)) * 60


def select_top_pairs(
    ranked_rows: list[Any],
    *,
    top_n: int,
) -> tuple[list[str], dict[str, int], dict[str, float | None]]:
    """Pick first top_n OK rows (already preferably ranked)."""
    ok = [r for r in ranked_rows if getattr(r, "status", None) == "ok"]
    ok.sort(
        key=lambda r: (
            getattr(r, "rank", None) is None,
            getattr(r, "rank", 10**9) or 10**9,
            -(
                getattr(r, "final_score", None)
                if getattr(r, "final_score", None) is not None
                else -999.0
            ),
            -(getattr(r, "score", None) if getattr(r, "score", None) is not None else -999.0),
            getattr(r, "pair", ""),
        )
    )
    chosen = ok[: max(0, int(top_n))]
    pairs = [str(r.pair) for r in chosen]
    ranks = {
        str(r.pair): int(getattr(r, "rank", i) or i) for i, r in enumerate(chosen, start=1)
    }
    scores: dict[str, float | None] = {}
    for r in chosen:
        final = getattr(r, "final_score", None)
        base = getattr(r, "score", None)
        if final is not None:
            scores[str(r.pair)] = float(final)
        elif base is not None:
            scores[str(r.pair)] = float(base)
        else:
            scores[str(r.pair)] = None
    return pairs, ranks, scores


def write_active_universe_report(state: ActiveUniverseState, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / DEFAULT_REPORT_NAME
    payload = {
        **state.to_dict(),
        "note": (
            "Pre-AI active universe. Only these pairs may open new trades. "
            "AI selection will replace this later."
        ),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def refresh_active_universe(
    strategy: Any,
    config: dict[str, Any],
    state: ActiveUniverseState,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> ActiveUniverseState:
    """Refresh top-N from a full score_scan ranking (throttled unless force)."""
    settings = load_active_universe_settings(config)
    state.enabled = bool(settings["enabled"])
    state.top_n = int(settings["top_n"])
    state.refresh_minutes = int(settings["refresh_minutes"])
    state.exit_when_dropped = bool(settings["exit_when_dropped"])

    if not state.enabled:
        return state

    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)

    if not force and not should_refresh(state, ts, state.refresh_minutes):
        return state

    from score_scan.engine import run_score_scan

    report = run_score_scan(
        strategy,
        config,
        mode="force",
        print_table=False,
        now=ts,
        reports_dir=Path(str(settings["reports_dir"])),
    )
    if report is None:
        logger.warning(
            "active_universe: score_scan returned None — keeping previous top list"
        )
        return state

    pairs, ranks, scores = select_top_pairs(report.results, top_n=state.top_n)
    state.pairs = pairs
    state.ranks = ranks
    state.scores = scores
    state.refreshed_at = ts.isoformat()
    state.next_refresh_at = (ts + timedelta(minutes=state.refresh_minutes)).isoformat()

    out = write_active_universe_report(state, Path(str(settings["reports_dir"])))
    logger.info(
        "active_universe: refreshed top_n=%s selected=%s pairs -> %s | file=%s",
        state.top_n,
        len(state.pairs),
        state.pairs,
        out,
    )
    return state
