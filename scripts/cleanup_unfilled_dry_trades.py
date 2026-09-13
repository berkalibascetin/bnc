#!/usr/bin/env python3
"""Free max_open_trades slots blocked by unfilled dry-run entry trades.

Freqtrade counts every open Trade toward max_open_trades — including
entries whose buy order never filled (amount == 0). Those "ghost" slots
stop new dry-run entries even though no position exists.

This script is dry-run SQLite only. It refuses live DBs.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _looks_like_dry_run_db(path: Path) -> bool:
    name = path.name.lower()
    return "dryrun" in name or "dry_run" in name or "dry-run" in name


def cleanup(db_path: Path, *, apply: bool) -> int:
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2
    if not _looks_like_dry_run_db(db_path):
        print(
            f"Refusing to touch {db_path}: name does not look like a dry-run DB.",
            file=sys.stderr,
        )
        return 2

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    ghosts = list(
        con.execute(
            """
            SELECT id, pair, amount, stake_amount, open_date
            FROM trades
            WHERE is_open = 1 AND COALESCE(amount, 0) = 0
            ORDER BY id
            """
        )
    )
    if not ghosts:
        print("No amount=0 open trades. Nothing to clean.")
        return 0

    print(f"Found {len(ghosts)} unfilled open trade(s) blocking slots:")
    for g in ghosts:
        print(
            f"  id={g['id']} {g['pair']} amount={g['amount']} "
            f"stake={g['stake_amount']} opened={g['open_date']}"
        )

    if not apply:
        print("Dry preview only. Re-run with --apply to close them in the DB.")
        return 0

    ids = [int(g["id"]) for g in ghosts]
    placeholders = ",".join("?" * len(ids))
    # Cancel any still-open orders tied to these trades.
    try:
        con.execute(
            f"UPDATE orders SET ft_is_open = 0, status = 'canceled' "
            f"WHERE ft_is_open = 1 AND ft_trade_id IN ({placeholders})",
            ids,
        )
    except sqlite3.Error as exc:
        print(f"Order update skipped/failed: {exc}")

    # Mark trades closed with zero profit so slots free up.
    con.execute(
        f"""
        UPDATE trades
        SET is_open = 0,
            close_date = CURRENT_TIMESTAMP,
            close_rate = open_rate,
            close_profit = 0,
            close_profit_abs = 0,
            exit_reason = 'cleanup_unfilled_entry'
        WHERE id IN ({placeholders}) AND is_open = 1 AND COALESCE(amount, 0) = 0
        """,
        ids,
    )
    con.commit()
    print(f"Closed {len(ids)} ghost trade(s). Restart the bot afterward.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--db",
        type=Path,
        default=Path("tradesv3.dryrun.sqlite"),
        help="Path to dry-run SQLite DB",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is preview-only)",
    )
    args = p.parse_args(argv)
    return cleanup(args.db, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
