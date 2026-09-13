"""Core dry-run observability helpers and report builder."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+-\s+"
    r"(?P<logger>\S+)\s+-\s+(?P<level>\w+)\s+-\s+(?P<msg>.*)$"
)
PAIR_RE = re.compile(r"\b([A-Z0-9]{2,20}/USDT)\b")

NETWORK_RULES = [
    ("network_error", re.compile(r"NetworkError|network error", re.I)),
    ("timeout", re.compile(r"RequestTimeout|timed?\s*out|Timeout|keepalive missing", re.I)),
    ("connection_error", re.compile(r"ConnectionError|Connection reset|Connection refused|name resolution", re.I)),
    ("rate_limit", re.compile(r"DDosProtection|RateLimitExceeded|\b429\b|rate limit", re.I)),
    ("http_api_error", re.compile(r"ExchangeError|ExchangeNotAvailable|\b451\b|HTTPError|AuthenticationError", re.I)),
    ("ticker_fetch_failure", re.compile(r"fetch_ticker|Could not load ticker|Unable to (load|fetch) ticker", re.I)),
    ("ohlcv_fetch_failure", re.compile(r"fetch_ohlcv|Could not load (historical )?data|Unable to download", re.I)),
    ("reconnect", re.compile(r"reconnect|websocket.*(reopen|restart)|exchange_ws", re.I)),
]
SYSTEM_RULES = [
    ("python_exception", re.compile(r"Traceback \(most recent call last\):")),
    ("strategy_exception", re.compile(r"StrategyException|strategy.*failed", re.I)),
    ("dataframe_error", re.compile(r"KeyError:|empty dataframe|DataFrame", re.I)),
    ("config_error", re.compile(r"Configuration error|InvalidConfiguration|ConfigurationError", re.I)),
    ("crash_or_restart", re.compile(r"Starting freqtrade|Changing state to: STOPPED|Bot process died|Fatal", re.I)),
]
SIGNAL_RULES = [
    ("entry_signal", re.compile(r"Buy signal|Long signal|Create trade for|Entering long|found entry opportunity", re.I)),
    ("exit_signal", re.compile(r"Sell signal|Exit for|Exiting trade|exit reason", re.I)),
    ("rejected_signal", re.compile(r"Unable to create trade|Max open trades reached|not enough stake|Rejected", re.I)),
]


@dataclass
class LogEvent:
    ts: datetime | None
    logger: str
    level: str
    message: str
    category: str
    pairs: list[str] = field(default_factory=list)
    raw: str = ""


def extract_pairs(text: str) -> list[str]:
    return sorted(set(PAIR_RE.findall(text or "")))


def classify_message(message: str, level: str = "INFO") -> str:
    for name, pat in NETWORK_RULES:
        if pat.search(message):
            return f"network:{name}"
    for name, pat in SYSTEM_RULES:
        if pat.search(message):
            return f"system:{name}"
    for name, pat in SIGNAL_RULES:
        if pat.search(message):
            return f"signal:{name}"
    if level.upper() in {"ERROR", "CRITICAL"}:
        return "system:unclassified_error"
    return "other"


def classify_log_lines(lines: list[str]) -> list[LogEvent]:
    events: list[LogEvent] = []
    pending_tb = False
    for line in lines:
        m = LOG_RE.match(line.rstrip("\n"))
        if not m:
            if pending_tb and events:
                events[-1].message += "\n" + line.rstrip("\n")
                events[-1].raw += "\n" + line.rstrip("\n")
            continue
        try:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = None
        msg = m.group("msg")
        level = m.group("level")
        category = classify_message(msg, level)
        if "Traceback (most recent call last)" in msg:
            pending_tb = True
            category = "system:python_exception"
        elif pending_tb and level.upper() not in {"ERROR", "CRITICAL"}:
            pending_tb = False
        events.append(
            LogEvent(
                ts=ts,
                logger=m.group("logger"),
                level=level,
                message=msg,
                category=category,
                pairs=extract_pairs(msg),
                raw=line.rstrip("\n"),
            )
        )
    return events


def summarize_prefix(events: list[LogEvent], prefix: str) -> dict[str, Any]:
    selected = [e for e in events if e.category.startswith(prefix)]
    by_cat: dict[str, list[LogEvent]] = defaultdict(list)
    for e in selected:
        by_cat[e.category].append(e)
    out: dict[str, Any] = {"total": len(selected), "by_category": {}}
    for cat, items in sorted(by_cat.items()):
        pairs: set[str] = set()
        for i in items:
            pairs.update(i.pairs)
        ts_vals = [i.ts for i in items if i.ts is not None]
        out["by_category"][cat] = {
            "count": len(items),
            "first_occurrence": min(ts_vals).isoformat(sep=" ") if ts_vals else None,
            "last_occurrence": max(ts_vals).isoformat(sep=" ") if ts_vals else None,
            "affected_pairs": sorted(pairs),
        }
    return out


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def connect_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def load_trades(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "trades"):
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY id")]


def load_orders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "orders"):
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM orders ORDER BY id")]


def analyze_trades_orders(
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    long_open_order_minutes: float = 30.0,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    open_trades = [t for t in trades if int(t.get("is_open") or 0) == 1]
    closed_trades = [t for t in trades if int(t.get("is_open") or 0) == 0]
    filled_like = [
        t
        for t in trades
        if float(t.get("amount") or 0) > 0
        or (int(t.get("is_open") or 0) == 0 and t.get("close_date"))
    ]
    open_orders = [
        o
        for o in orders
        if int(o.get("ft_is_open") or 0) == 1
        or str(o.get("status") or "").lower() in {"open", "new", "partially_filled"}
    ]
    filled_orders = [
        o
        for o in orders
        if str(o.get("status") or "").lower() in {"closed", "filled"}
        or (float(o.get("filled") or 0) > 0 and int(o.get("ft_is_open") or 0) == 0)
    ]
    cancelled_orders = [
        o
        for o in orders
        if str(o.get("status") or "").lower() in {"canceled", "cancelled"}
        or o.get("ft_cancel_reason")
    ]

    suspicious: list[dict[str, Any]] = []
    for o in open_orders:
        amount = float(o.get("amount") or o.get("ft_amount") or 0)
        filled = float(o.get("filled") or 0)
        order_date = parse_dt(o.get("order_date"))
        age_min = ((now - order_date).total_seconds() / 60.0) if order_date else None
        reasons: list[str] = []
        if amount == 0 and filled == 0:
            reasons.append("amount_zero")
        if age_min is not None and age_min >= long_open_order_minutes:
            reasons.append("open_unusually_long")
        if reasons:
            suspicious.append(
                {
                    "kind": "order",
                    "order_id": o.get("order_id") or o.get("id"),
                    "pair": o.get("ft_pair") or o.get("symbol"),
                    "status": o.get("status"),
                    "amount": amount,
                    "filled": filled,
                    "age_minutes": None if age_min is None else round(age_min, 2),
                    "reasons": reasons,
                    "note": "OPEN ORDER (not a filled position)",
                }
            )
    for t in open_trades:
        if float(t.get("amount") or 0) == 0:
            suspicious.append(
                {
                    "kind": "trade",
                    "trade_id": t.get("id"),
                    "pair": t.get("pair"),
                    "amount": 0.0,
                    "open_rate": t.get("open_rate"),
                    "open_date": str(t.get("open_date")),
                    "reasons": ["open_trade_amount_zero"],
                    "note": "Trade row exists with amount=0 (likely unfilled entry order)",
                }
            )

    durations_h: list[float] = []
    for t in closed_trades:
        od = parse_dt(t.get("open_date"))
        cd = parse_dt(t.get("close_date"))
        if od and cd and cd >= od:
            durations_h.append((cd - od).total_seconds() / 3600.0)

    by_pair: dict[str, int] = {}
    for t in trades:
        pair = str(t.get("pair") or "?")
        by_pair[pair] = by_pair.get(pair, 0) + 1

    realized = [
        float(t["close_profit_abs"])
        for t in closed_trades
        if t.get("close_profit_abs") is not None
    ]
    wins = [p for p in realized if p > 0]
    losses = [p for p in realized if p < 0]

    return {
        "trades": {
            "created": len(trades),
            "currently_open": len(open_trades),
            "closed": len(closed_trades),
            "filled_like": len(filled_like),
            "distribution_by_pair": dict(sorted(by_pair.items(), key=lambda kv: (-kv[1], kv[0]))),
            "open_details": [
                {
                    "id": t.get("id"),
                    "pair": t.get("pair"),
                    "amount": t.get("amount"),
                    "open_rate": t.get("open_rate"),
                    "stake_amount": t.get("stake_amount"),
                    "open_date": str(t.get("open_date")),
                    "enter_tag": t.get("enter_tag"),
                }
                for t in open_trades
            ],
            "closed_details": [
                {
                    "id": t.get("id"),
                    "pair": t.get("pair"),
                    "amount": t.get("amount"),
                    "open_rate": t.get("open_rate"),
                    "close_rate": t.get("close_rate"),
                    "close_profit_abs": t.get("close_profit_abs"),
                    "open_date": str(t.get("open_date")),
                    "close_date": str(t.get("close_date")),
                    "exit_reason": t.get("exit_reason"),
                }
                for t in closed_trades
            ],
            "average_duration_hours": (
                round(sum(durations_h) / len(durations_h), 4) if durations_h else None
            ),
        },
        "orders": {
            "created": len(orders),
            "open": len(open_orders),
            "filled": len(filled_orders),
            "cancelled": len(cancelled_orders),
            "distinction_note": (
                "OPEN ORDER = unfinished dry-run/exchange order. "
                "OPEN TRADE = trades.is_open=1. "
                "Unfilled entry orders can appear as amount=0 open trades."
            ),
            "suspicious": suspicious,
        },
        "performance": {
            "realized_simulated_pnl": round(sum(realized), 8) if realized else None,
            "unrealized_simulated_pnl": "N/A",
            "unrealized_note": "Requires live mark prices; omitted in offline reporter.",
            "win_rate": round(len(wins) / len(realized), 4) if realized else None,
            "profit_factor": (
                round(sum(wins) / abs(sum(losses)), 4)
                if wins and losses and sum(losses) != 0
                else None
            ),
            "average_trade_pnl": round(sum(realized) / len(realized), 8) if realized else None,
            "max_drawdown": "N/A",
            "closed_trade_count_for_metrics": len(realized),
            "note": "Do not claim strategy profitability from tiny dry-run samples.",
        },
    }


def discover_paths(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    configs = [root / "user_data" / "config.json", root / "config.json"]
    dbs = [
        root / "tradesv3.dryrun.sqlite",
        root / "user_data" / "tradesv3.dryrun.sqlite",
        root / "tradesv3.sqlite",
    ]
    logs: list[Path] = []
    for d in (root / "user_data" / "logs", root / "logs"):
        if d.exists():
            logs.extend(sorted(d.glob("*.log")))
    logs.extend(sorted(root.glob("freqtrade*.log")))
    strategy_json = root / "user_data" / "strategies" / "Score4WindowStrategy.json"
    strategy_py = root / "user_data" / "strategies" / "Score4WindowStrategy.py"
    return {
        "project_root": root,
        "config": next((p for p in configs if p.exists()), None),
        "db": next((p for p in dbs if p.exists()), None),
        "log": logs[-1] if logs else None,
        "strategy_json": strategy_json if strategy_json.exists() else None,
        "strategy_py": strategy_py if strategy_py.exists() else None,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_risk_pct(strategy_json: Path | None, strategy_py: Path | None) -> Any:
    if strategy_json is not None:
        buy = (load_json(strategy_json).get("params") or {}).get("buy") or {}
        if "risk_pct" in buy:
            return buy["risk_pct"]
    if strategy_py is not None:
        for line in strategy_py.read_text(encoding="utf-8").splitlines():
            if "RISK_PCT" in line and "=" in line and not line.strip().startswith("#"):
                try:
                    return float(line.split("=", 1)[1].strip().split()[0])
                except Exception:
                    pass
    return None


def analyze_universe(config: dict[str, Any], data_dir: Path | None) -> dict[str, Any]:
    exchange = config.get("exchange") or {}
    whitelist = list(exchange.get("pair_whitelist") or [])
    counts = Counter(whitelist)
    duplicates = sorted([p for p, n in counts.items() if n > 1])
    non_usdt = sorted([p for p in whitelist if not str(p).endswith("/USDT")])
    present = 0
    missing: list[str] = []
    if data_dir and data_dir.exists():
        for pair in dict.fromkeys(whitelist):
            stem = pair.replace("/", "_")
            if (data_dir / f"{stem}-1d.feather").exists() or (data_dir / f"{stem}-1d.json").exists():
                present += 1
            else:
                missing.append(pair)
    return {
        "configured_pair_count": len(whitelist),
        "unique_pair_count": len(set(whitelist)),
        "duplicates": duplicates,
        "non_usdt_pairs": non_usdt,
        "pairs": whitelist,
        "exchange_name": exchange.get("name"),
        "pairs_with_local_1d_data": present if data_dir else None,
        "pairs_missing_local_1d_data": missing,
        "note": "Configured StaticPairList is the intended scan universe.",
    }


def analyze_signals(events: list[LogEvent]) -> dict[str, Any]:
    entries = [e for e in events if e.category == "signal:entry_signal"]
    exits = [e for e in events if e.category == "signal:exit_signal"]
    rejected = [e for e in events if e.category == "signal:rejected_signal"]

    def by_pair(items: list[LogEvent]) -> dict[str, int]:
        c: Counter[str] = Counter()
        for e in items:
            if e.pairs:
                for p in e.pairs:
                    c[p] += 1
            else:
                c["UNKNOWN"] += 1
        return dict(c.most_common())

    return {
        "total_entry_signals_from_logs": len(entries),
        "total_exit_signals_from_logs": len(exits),
        "rejected_signals_from_logs": len(rejected),
        "entry_signals_by_pair": by_pair(entries),
        "exit_signals_by_pair": by_pair(exits),
        "entry_timestamps": [e.ts.isoformat(sep=" ") for e in entries if e.ts],
        "exit_timestamps": [e.ts.isoformat(sep=" ") for e in exits if e.ts],
        "limitation": (
            "Exact raw strategy signals cannot be fully reconstructed without strategy "
            "instrumentation. Log-derived counts may undercount if logs were not saved."
        ),
    }


def estimate_uptime(events: list[LogEvent]) -> dict[str, Any]:
    ts_vals = [e.ts for e in events if e.ts is not None]
    if not ts_vals:
        return {
            "observation_start": None,
            "observation_end": None,
            "span_hours": None,
            "restarts_detected_from_logs": None,
            "data_collection_gaps": [],
            "note": "No timestamped logs; uptime cannot be inferred.",
        }
    start, end = min(ts_vals), max(ts_vals)
    ordered = sorted(ts_vals)
    gaps = []
    for a, b in zip(ordered, ordered[1:]):
        mins = (b - a).total_seconds() / 60.0
        if mins >= 30:
            gaps.append(
                {
                    "gap_start": a.isoformat(sep=" "),
                    "gap_end": b.isoformat(sep=" "),
                    "gap_minutes": round(mins, 2),
                    "label": "DATA COLLECTION GAP",
                }
            )
    restarts = sum(
        1
        for e in events
        if e.category == "system:crash_or_restart" and "Starting freqtrade" in e.message
    )
    return {
        "observation_start": start.isoformat(sep=" "),
        "observation_end": end.isoformat(sep=" "),
        "span_hours": round((end - start).total_seconds() / 3600.0, 4),
        "restarts_detected_from_logs": restarts,
        "data_collection_gaps": gaps,
        "note": "Sleep/network outages appear as DATA COLLECTION GAP.",
    }


def safety_check(config: dict[str, Any], risk_pct: Any) -> dict[str, Any]:
    dry_run = bool(config.get("dry_run"))
    exchange = (config.get("exchange") or {}).get("name")
    return {
        "dry_run": dry_run,
        "live_trading_disabled": dry_run is True,
        "exchange": exchange,
        "timeframe": config.get("timeframe"),
        "max_open_trades": config.get("max_open_trades"),
        "stake_amount": config.get("stake_amount"),
        "risk_pct": risk_pct,
        "stoploss_in_config": "stoploss" in config,
        "minimal_roi_in_config": "minimal_roi" in config,
        "strategy_name_expected": "Score4WindowStrategy",
        "safe_to_continue_dry_run": dry_run is True and str(exchange).lower() == "binance",
        "stop_reason": None if dry_run else "dry_run is not true — SAFETY FAILURE",
    }


def build_report(
    project_root: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    config_path: Path | None = None,
    db_path: Path | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    paths = discover_paths(project_root)
    if config_path:
        paths["config"] = config_path
    if db_path:
        paths["db"] = db_path
    if log_path:
        paths["log"] = log_path

    limitations: list[str] = []
    if paths["config"] is None:
        raise FileNotFoundError("Could not find user_data/config.json")

    config = load_json(Path(paths["config"]))
    risk_pct = read_risk_pct(paths["strategy_json"], paths["strategy_py"])
    safety = safety_check(config, risk_pct)
    if not safety["dry_run"]:
        return {
            "observation": {"status": "ABORTED"},
            "safety": safety,
            "limitations": ["Reporter aborted because dry_run is not true."],
        }

    data_dir = Path(paths["project_root"]) / "user_data" / "data" / "binance"
    universe = analyze_universe(config, data_dir if data_dir.exists() else None)

    trades: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    if paths["db"] is None:
        limitations.append("Dry-run SQLite DB not found; trade/order metrics unavailable.")
        trade_order = analyze_trades_orders([], [])
    else:
        conn = connect_ro(Path(paths["db"]))
        try:
            trades = load_trades(conn)
            orders = load_orders(conn)
        finally:
            conn.close()
        if since or until:
            def in_range(raw: Any) -> bool:
                dt = parse_dt(raw)
                if dt is None:
                    return False
                if since and dt < since:
                    return False
                if until and dt > until:
                    return False
                return True

            trades = [t for t in trades if in_range(t.get("open_date"))]
            orders = [o for o in orders if in_range(o.get("order_date"))]
            limitations.append("Trade/order metrics filtered by --since/--until.")
        trade_order = analyze_trades_orders(trades, orders)

    events: list[LogEvent] = []
    if paths["log"] is None:
        limitations.append("No log file found; signal/API/system metrics from logs are limited.")
        system_statement = "STRATEGY/SYSTEM ERRORS: unknown (no logs)"
        system_health: dict[str, Any] = {"total": None, "by_category": {}, "statement": system_statement}
        api_health: dict[str, Any] = {"total": None, "by_category": {}}
    else:
        lines = Path(paths["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
        events = classify_log_lines(lines)
        if since or until:
            events = [
                e
                for e in events
                if e.ts is not None
                and (since is None or e.ts >= since)
                and (until is None or e.ts <= until)
            ]
        system_health = summarize_prefix(events, "system:")
        api_health = summarize_prefix(events, "network:")
        if system_health["total"] == 0:
            system_statement = "STRATEGY/SYSTEM ERRORS: 0 detected"
        else:
            system_statement = f"STRATEGY/SYSTEM ERRORS: {system_health['total']} detected"
        system_health["statement"] = system_statement

    signals = analyze_signals(events)
    signals["trades_by_enter_tag_from_db"] = dict(
        Counter(str(t.get("enter_tag") or "untagged") for t in trades)
    )
    uptime = estimate_uptime(events)
    api_health["classification_note"] = (
        "Temporary NetworkError/timeouts are API/network health issues, NOT strategy failures."
    )

    return {
        "observation": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + "Z",
            "project_root": str(paths["project_root"]),
            "config_path": str(paths["config"]),
            "db_path": str(paths["db"]) if paths["db"] else None,
            "log_path": str(paths["log"]) if paths["log"] else None,
            "strategy_name": "Score4WindowStrategy",
            "period": uptime,
        },
        "universe": universe,
        "signals": signals,
        "orders": trade_order["orders"],
        "trades": trade_order["trades"],
        "performance": trade_order["performance"],
        "api_health": api_health,
        "system_health": system_health,
        "data_quality": {
            "data_collection_gaps": uptime.get("data_collection_gaps") or [],
            "pairs_missing_local_1d_data": universe.get("pairs_missing_local_1d_data") or [],
            "notes": [
                "PC sleep creates DATA COLLECTION GAP and reduces observation quality.",
                "1–2 day samples validate operations; they do not prove edge.",
            ],
        },
        "safety": safety,
        "limitations": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    def fmt(v: Any) -> Any:
        return "N/A" if v is None else v

    obs = report.get("observation") or {}
    period = obs.get("period") or {}
    uni = report.get("universe") or {}
    sig = report.get("signals") or {}
    orders = report.get("orders") or {}
    trades = report.get("trades") or {}
    perf = report.get("performance") or {}
    api = report.get("api_health") or {}
    sysh = report.get("system_health") or {}
    dq = report.get("data_quality") or {}
    safety = report.get("safety") or {}
    limitations = report.get("limitations") or []

    lines = [
        "========================================",
        "DRY-RUN OBSERVATION REPORT",
        "========================================",
        "",
        f"Generated: {obs.get('generated_at_utc')}",
        f"Config: {obs.get('config_path')}",
        f"DB: {obs.get('db_path')}",
        f"Log: {obs.get('log_path')}",
        "",
        "Period:",
        f"Start: {period.get('observation_start')}",
        f"End: {period.get('observation_end')}",
        f"Span hours: {period.get('span_hours')}",
        f"Restarts detected: {period.get('restarts_detected_from_logs')}",
        "",
        "Universe:",
        f"Pairs configured: {uni.get('configured_pair_count')}",
        f"Unique pairs: {uni.get('unique_pair_count')}",
        f"Duplicates: {uni.get('duplicates')}",
        f"Non-USDT pairs: {uni.get('non_usdt_pairs')}",
        f"Pairs with local 1d data: {uni.get('pairs_with_local_1d_data')}",
        f"Pairs missing local 1d data: {len(uni.get('pairs_missing_local_1d_data') or [])}",
        "",
        "Signals:",
        f"Entry signals (log-derived): {sig.get('total_entry_signals_from_logs')}",
        f"Exit signals (log-derived): {sig.get('total_exit_signals_from_logs')}",
        f"Rejected signals (log-derived): {sig.get('rejected_signals_from_logs')}",
        f"Limitation: {sig.get('limitation')}",
        "",
        "Trades:",
        f"Trades created: {trades.get('created')}",
        f"Trades currently open: {trades.get('currently_open')}",
        f"Trades closed: {trades.get('closed')}",
        f"Filled-like trades: {trades.get('filled_like')}",
        f"Average duration hours: {fmt(trades.get('average_duration_hours'))}",
        "",
        "Orders:",
        f"Orders created: {orders.get('created')}",
        f"Orders open (unfilled): {orders.get('open')}",
        f"Orders filled: {orders.get('filled')}",
        f"Orders cancelled: {orders.get('cancelled')}",
        f"Note: {orders.get('distinction_note')}",
        "",
        "Performance:",
        f"Realized simulated PnL: {fmt(perf.get('realized_simulated_pnl'))}",
        f"Unrealized simulated PnL: {perf.get('unrealized_simulated_pnl')}",
        f"Win rate: {fmt(perf.get('win_rate'))}",
        f"Profit factor: {fmt(perf.get('profit_factor'))}",
        f"Average trade: {fmt(perf.get('average_trade_pnl'))}",
        f"Max drawdown: {perf.get('max_drawdown')}",
        "",
        "Health:",
        f"Network/API events: {api.get('total')}",
        f"Strategy/system events: {sysh.get('total')}",
        f"{sysh.get('statement')}",
        "",
        "Top trade pairs:",
    ]
    dist = trades.get("distribution_by_pair") or {}
    if dist:
        for pair, count in list(dist.items())[:10]:
            lines.append(f"- {pair}: {count}")
    else:
        lines.append("- none")

    lines += ["", "Problematic orders/trades:"]
    suspicious = orders.get("suspicious") or []
    if suspicious:
        for s in suspicious[:20]:
            lines.append(f"- {s}")
    else:
        lines.append("- none flagged")

    lines += ["", "Data gaps:"]
    gaps = dq.get("data_collection_gaps") or []
    if gaps:
        for g in gaps:
            lines.append(f"- {g}")
    else:
        lines.append("- none detected from available logs")

    lines += [
        "",
        "Safety:",
        f"dry_run={safety.get('dry_run')}",
        f"LIVE TRADING: {'DISABLED' if safety.get('live_trading_disabled') else 'ENABLED/UNKNOWN'}",
        f"exchange={safety.get('exchange')}",
        f"timeframe={safety.get('timeframe')}",
        f"max_open_trades={safety.get('max_open_trades')}",
        f"stake_amount={safety.get('stake_amount')}",
        f"risk_pct={safety.get('risk_pct')}",
        f"safe_to_continue_dry_run={safety.get('safe_to_continue_dry_run')}",
        "",
        "Limitations:",
    ]
    if limitations:
        for lim in limitations:
            lines.append(f"- {lim}")
    else:
        lines.append("- none")
    lines += ["", "========================================", ""]
    return "\n".join(lines)
