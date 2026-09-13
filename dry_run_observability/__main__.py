"""CLI entrypoint: python -m dry_run_observability report"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from dry_run_observability.core import build_report, render_markdown


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Invalid datetime: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dry_run_observability",
        description="Generate Freqtrade dry-run observability reports (read-only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    report_p = sub.add_parser("report", help="Build JSON + Markdown dry-run observation report")
    report_p.add_argument("--project-root", type=Path, default=Path.cwd())
    report_p.add_argument("--config", type=Path, default=None)
    report_p.add_argument("--db", type=Path, default=None)
    report_p.add_argument("--log", type=Path, default=None)
    report_p.add_argument("--since", type=str, default=None, help="YYYY-MM-DD[ HH:MM[:SS]]")
    report_p.add_argument("--until", type=str, default=None, help="YYYY-MM-DD[ HH:MM[:SS]]")
    report_p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory for dry_run_report.json and dry_run_report.md",
    )
    report_p.add_argument("--json-out", type=Path, default=None)
    report_p.add_argument("--md-out", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command != "report":
        parser.error(f"Unknown command: {args.command}")

    report = build_report(
        args.project_root,
        since=_parse_dt(args.since),
        until=_parse_dt(args.until),
        config_path=args.config,
        db_path=args.db,
        log_path=args.log,
    )

    safety = report.get("safety") or {}
    if safety.get("dry_run") is False:
        print("SAFETY FAILURE: dry_run is not true. Aborting output.")
        print(json.dumps(safety, indent=2))
        return 2

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.json_out or (out_dir / "dry_run_report.json")
    md_path = args.md_out or (out_dir / "dry_run_report.md")

    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(
        "Summary:",
        f"pairs={((report.get('universe') or {}).get('configured_pair_count'))}",
        f"dry_run={safety.get('dry_run')}",
        f"open_trades={((report.get('trades') or {}).get('currently_open'))}",
        f"open_orders={((report.get('orders') or {}).get('open'))}",
        f"network_events={((report.get('api_health') or {}).get('total'))}",
        f"system_events={((report.get('system_health') or {}).get('total'))}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
