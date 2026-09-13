#!/usr/bin/env python3
"""
Build a deterministic ~100-pair Binance SPOT USDT universe.

Methodology ID: BINANCE_SPOT_USDT_CURATED100_QV24H_V1

Uses Binance public market-data API (data-api.binance.vision) so generation
works even when api.binance.com is geo-restricted.

Selection rules (in order):
1. Candidate pool = curated well-known bases ∩ currently TRADING SPOT USDT.
2. Exclude leveraged tokens, non-ASCII bases, stablecoin bases, tokenized-stock wrappers.
3. Force-include BTC/ETH/SOL/BNB/XRP.
4. Force-include a priority tier of established majors when listed.
5. Fill remaining seats by descending 24h USDT quoteVolume among curated live markets.
6. If still < target, fill from other filtered liquid markets (documented).

IMPORTANT: This is a CURRENT dry-run observation universe, not a historical
top-100. See docs/binance_universe_methodology.md (survivorship bias).
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = "https://data-api.binance.vision"
TARGET = 100

MUST_INCLUDE = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# Established majors / large well-known assets — included whenever listed+tradable.
PRIORITY_BASES = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "DOGE", "ADA", "TRX", "AVAX", "DOT", "LINK", "SHIB", "LTC", "BCH",
    "NEAR", "UNI", "APT", "ATOM", "XLM", "ICP", "FIL", "HBAR", "INJ", "SUI",
    "SEI", "OP", "ARB", "AAVE", "MKR", "CRV", "LDO", "RUNE", "ALGO", "VET",
    "EGLD", "XTZ", "EOS", "FLOW", "MANA", "SAND", "AXS", "THETA", "ETC",
    "XMR", "ZEC", "DASH", "NEO", "IOTA", "QNT", "GRT", "SNX", "COMP",
    "ENS", "CAKE", "DYDX", "GMX", "PENDLE", "JUP", "JTO", "PYTH", "TIA",
    "STRK", "ENA", "ETHFI", "WLD", "ONDO", "RENDER", "FET", "TAO", "AR",
    "ORDI", "BONK", "WIF", "PEPE", "FLOKI", "NOT", "EIGEN", "ZRO", "POL",
    "TRUMP", "VIRTUAL", "BERA", "STX", "IMX", "LUNC", "APT", "SUI",
]

# Broader curated set used for volume fill after priority seats.
CURATED_BASES = PRIORITY_BASES + [
    "BLUR", "LOOKS", "SSV", "RPL", "FXS", "CVX", "BAL", "SUSHI", "KSM",
    "MINA", "CELO", "ONE", "ROSE", "SKL", "ANKR", "CKB", "QTUM", "ICX",
    "ONT", "IOST", "SC", "DGB", "RVN", "BEAM", "RSR", "JST", "SUN", "TWT",
    "WOO", "API3", "BAND", "STORJ", "AUDIO", "CHR", "CELR", "CTSI", "RLC",
    "ACH", "TLM", "ALICE", "SUPER", "MAGIC", "PAXG", "WBTC", "WBETH",
    "BNSOL", "OMNI", "REZ", "BB", "ACE", "NFP", "XAI", "AI", "SAGA",
    "TAIKO", "ZETA", "DYM", "ALT", "JASMY", "MASK", "LPT", "TRB", "PHA",
    "HOOK", "HFT", "ID", "EDU", "CYBER", "ARKM", "WAXP", "GLMR", "ASTR",
    "KDA", "GAS", "ZEN", "NTRN", "ARK", "IQ", "HOT", "WIN", "COTI", "SXP",
    "DEXE", "UMA", "BADGER", "FIDA", "RAY", "ORCA", "AEVO", "METIS",
    "AURORA", "BOBA", "USTC", "LUNA", "MORPHO", "TNSR", "PIXEL", "PORTAL",
    "MANTA", "BLAST", "W", "LISTA", "IO", "ZK", "MOVE", "S", "PENGU",
    "KAITO", "LAYER", "OM", "FORM", "SPX", "POPCAT", "MEW", "TURBO",
    "NEIRO", "GOAT", "ACT", "PNUT", "MEME", "BOME", "DOGS", "HMSTR",
    "CATI", "MELANIA", "AIXBT", "AI16Z", "CHZ", "GALA", "APE", "GMT",
    "CFX", "1INCH", "BAT", "ZRX", "YFI", "ENJ", "KAVA", "ZIL", "ZRX",
    "PROM", "LSK", "RIF", "SANTOS", "ASR", "ATM", "CITY", "BAR",
    "PSG", "JUV", "ACM", "OG", "ZEN", "SKL", "CELR", "IOST", "LSK",
    "REI", "BANANA", "COOKIE", "ANIME", "SHELL", "RED", "PARTI", "EPIC",
    "INIT", "SIGN", "WCT", "HYPER", "OBOL", "HOME", "RESOLV", "SOPH",
    "IDOL", "MUBARAK", "BROCCOLI", "GPS", "PLUME", "TREE", "TOWNS",
    "ERA", "BIO", "MOVE", "ME", "VANA", "USUAL", "AERO", "HYPE",
]

EXCLUDE_BASES = {
    "USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "EUR", "GBP", "AEUR",
    "USD1", "USDE", "BFUSD", "RLUSD", "XUSD", "PAX", "EURI", "TRY", "BRL",
    "ARS", "BIDR", "IDRT", "UAH", "NGN", "PLN", "RON", "ZAR",
}

# Crypto bases that legitimately end with "B" (must NOT be treated as stock wrappers).
KNOWN_B_SUFFIX = {
    "SHIB", "WBTC", "WBETH", "BCH", "BOME", "BANANA", "BLAST", "BEAM", "BTT",
    "BTTC", "BOND", "BAL", "BAT", "BB", "BIFI", "BAKE", "BURGER", "BAND",
    "BADGER", "BIO", "BNSOL", "BONK", "SCRB", "AMB", "SNT", "CTB",
}

BASE_OK = re.compile(r"^[A-Z0-9]{2,15}$")


def http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "bnc-universe-builder/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def is_leveraged(base: str) -> bool:
    if base.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return True
    return bool(re.search(r"\d+[LS]$", base))


def is_stock_wrapper(base: str) -> bool:
    """Heuristic for Binance tokenized-equity tickers (e.g. NVDAB, MSTRB, QQQB)."""
    if base in KNOWN_B_SUFFIX:
        return False
    # Never exclude curated/priority crypto solely for ending with B (e.g. SHIB).
    if base in PRIORITY_BASES or base in CURATED_BASES:
        return False
    # Tokenized equity tickers commonly look like {STOCK}B with short alpha prefix.
    if re.fullmatch(r"[A-Z]{2,5}B", base):
        return True
    return False


def unique(seq: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def load_live_markets(api: str) -> dict[str, dict[str, Any]]:
    info = http_get_json(f"{api}/api/v3/exchangeInfo")
    tickers = http_get_json(f"{api}/api/v3/ticker/24hr")
    tmap = {t["symbol"]: t for t in tickers}
    markets: dict[str, dict[str, Any]] = {}
    for s in info["symbols"]:
        if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
            continue
        base = s["baseAsset"]
        if not BASE_OK.match(base):
            continue
        if is_leveraged(base) or base in EXCLUDE_BASES or is_stock_wrapper(base):
            continue
        # Prefer SPOT permission when present.
        perms = s.get("permissions") or []
        psets = s.get("permissionSets") or []
        flat = list(perms) + [x for ps in psets if isinstance(ps, list) for x in ps]
        if flat and "SPOT" not in flat:
            continue
        sym = s["symbol"]
        t = tmap.get(sym, {})
        qv = float(t.get("quoteVolume") or 0)
        last = float(t.get("lastPrice") or 0)
        if last <= 0 or qv <= 0:
            continue
        markets[base] = {
            "symbol": sym,
            "pair": f"{base}/USDT",
            "base": base,
            "quote": "USDT",
            "market_type": "spot",
            "status": "TRADING",
            "active": True,
            "quoteVolume_24h": qv,
            "lastPrice": last,
        }
    return markets


def build_universe(api: str, target: int = TARGET) -> dict[str, Any]:
    curated = unique(CURATED_BASES)
    priority = unique(PRIORITY_BASES)
    markets = load_live_markets(api)

    selected: dict[str, dict[str, Any]] = {}

    def take(base: str, rule: str) -> None:
        if base in selected or base not in markets:
            return
        row = dict(markets[base])
        row["selection_rule"] = rule
        selected[base] = row

    for b in MUST_INCLUDE:
        if b not in markets:
            raise RuntimeError(f"Must-include market missing/unavailable: {b}/USDT")
        take(b, "must_include")

    for b in priority:
        take(b, "priority_established")
        if len(selected) >= target:
            break

    curated_live = sorted(
        [markets[b] for b in curated if b in markets],
        key=lambda x: -x["quoteVolume_24h"],
    )
    for row in curated_live:
        if len(selected) >= target:
            break
        take(row["base"], "curated_top_volume")

    if len(selected) < target:
        others = sorted(markets.values(), key=lambda x: -x["quoteVolume_24h"])
        for row in others:
            if len(selected) >= target:
                break
            take(row["base"], "volume_fill_non_curated")

    if len(selected) < target:
        raise RuntimeError(f"Only selected {len(selected)} pairs; need {target}")

    # Deterministic ordering: must-include order, then remaining by volume desc.
    must_rows = [selected[b] for b in MUST_INCLUDE]
    rest = sorted(
        [v for k, v in selected.items() if k not in MUST_INCLUDE],
        key=lambda x: (-x["quoteVolume_24h"], x["pair"]),
    )
    # If priority/curated overshot, keep top (target - 5) by volume from rest,
    # but never drop priority names already selected until target trim.
    if len(must_rows) + len(rest) > target:
        # Prefer keeping priority bases when trimming.
        priority_set = set(priority)
        priority_rest = [r for r in rest if r["base"] in priority_set]
        other_rest = [r for r in rest if r["base"] not in priority_set]
        need = target - len(must_rows)
        rest = (priority_rest + other_rest)[:need]

    final = must_rows + rest
    assert len(final) == target, len(final)
    assert len({r["pair"] for r in final}) == target

    for i, row in enumerate(final, 1):
        row["universe_rank"] = i

    rules: dict[str, int] = {}
    for row in final:
        rules[row["selection_rule"]] = rules.get(row["selection_rule"], 0) + 1

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_api": api,
        "methodology_id": "BINANCE_SPOT_USDT_CURATED100_QV24H_V1",
        "methodology_summary": (
            "Curated/priority well-known Binance SPOT USDT markets, force-including "
            "BTC/ETH/SOL/BNB/XRP, excluding leveraged/stable/stock-wrapper tokens, "
            "then filling by 24h USDT quoteVolume."
        ),
        "survivorship_bias_note": (
            "CURRENT listed/liquid universe only. Not a historical top-100. "
            "Do not claim historical strategy quality from this membership without "
            "date-aware universe reconstruction."
        ),
        "target_count": target,
        "final_count": len(final),
        "selection_rule_counts": rules,
        "must_include": [f"{b}/USDT" for b in MUST_INCLUDE],
        "priority_bases_count": len(priority),
        "curated_bases_count": len(curated),
        "live_filtered_markets_count": len(markets),
        "min_selected_quoteVolume_24h": min(r["quoteVolume_24h"] for r in final),
        "pairs": [r["pair"] for r in final],
        "details": final,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "user_data" / "universes",
    )
    args = parser.parse_args()
    payload = build_universe(args.api, args.target)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "binance_spot_usdt_top100.json"
    txt_path = args.out_dir / "binance_spot_usdt_top100_pairs.txt"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    txt_path.write_text("\n".join(payload["pairs"]) + "\n")
    print(f"Wrote {json_path}")
    print(f"Wrote {txt_path}")
    print(f"final_count={payload['final_count']} rules={payload['selection_rule_counts']}")
    print("pairs=" + ",".join(payload["pairs"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
