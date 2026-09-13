"""Write score_scan JSON + Markdown reports (observation only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from score_scan.engine import ScanReport

DEFAULT_RETENTION = 48  # keep last N timestamped history files (json+md pairs ~24 scans)


def write_reports(report: ScanReport, reports_dir: Path, *, retention: int = DEFAULT_RETENTION) -> dict[str, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    hist_dir = reports_dir / "score_scans"
    hist_dir.mkdir(parents=True, exist_ok=True)

    payload = report.to_dict()
    latest_json = reports_dir / "score_scan_latest.json"
    latest_md = reports_dir / "score_scan_latest.md"
    latest_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(render_markdown(payload), encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    hist_json = hist_dir / f"{stamp}.json"
    hist_md = hist_dir / f"{stamp}.md"
    hist_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    hist_md.write_text(render_markdown(payload), encoding="utf-8")

    _prune_history(hist_dir, retention=retention)
    return {
        "latest_json": latest_json,
        "latest_md": latest_md,
        "hist_json": hist_json,
        "hist_md": hist_md,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    s = payload.get("summary") or {}
    lines = [
        f"# Score Scan - {str(payload.get('mode', '')).upper()}",
        "",
        f"- Timestamp: `{payload.get('timestamp')}`",
        f"- Timeframe: `{payload.get('timeframe')}`",
        f"- Pairs: **{payload.get('pair_count')}**",
        f"- dry_run: **{payload.get('dry_run')}**",
        f"- Entry threshold: `{payload.get('entry_score_threshold')}`",
        "",
        "## Summary",
        "",
        f"- Scored: {s.get('scored')}",
        f"- Insufficient data: {s.get('insufficient_data')}",
        f"- Errors: {s.get('error')}",
        f"- Max score: {s.get('max_score')}",
        f"- Min score: {s.get('min_score')}",
        f"- Score distribution: `{s.get('score_distribution')}`",
        f"- güçlü alım (+4): {', '.join(s.get('strong_buy_signals') or []) or '-'}",
        f"- alım (+2): {', '.join(s.get('buy_signals') or []) or '-'}",
        f"- sell (-2): {', '.join(s.get('sell_signals') or []) or '-'}",
        f"- hızlıca sell (-4): {', '.join(s.get('strong_sell_signals') or []) or '-'}",
        "",
        "## Results",
        "",
        "| Rank | Pair | Score | Signal | Candle | Status | Reason |",
        "|------|------|------:|--------|--------|--------|--------|",
    ]
    for r in payload.get("results") or []:
        lines.append(
            "| {rank} | {pair} | {score} | {signal} | {candle} | {status} | {reason} |".format(
                rank=r.get("rank") if r.get("rank") is not None else "-",
                pair=r.get("pair"),
                score="" if r.get("score") is None else r.get("score"),
                signal=r.get("signal") or "-",
                candle=r.get("candle_timestamp") or "-",
                status=r.get("status"),
                reason=r.get("reason") or "",
            )
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _prune_history(hist_dir: Path, *, retention: int) -> None:
    files = sorted(hist_dir.glob("*.json"))
    if len(files) <= retention:
        return
    for path in files[:-retention]:
        path.unlink(missing_ok=True)
        md = path.with_suffix(".md")
        md.unlink(missing_ok=True)
