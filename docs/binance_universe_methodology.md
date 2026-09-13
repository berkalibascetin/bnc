# Binance Universe Methodology

## Purpose

Expand the dry-run scanning universe from 5 pairs to ~100 well-known / liquid
Binance **SPOT USDT** pairs so we can measure whether `Score4WindowStrategy`
finds more opportunities when the search space is larger.

This change expands **search space only**. Strategy logic is unchanged.

## Methodology ID

`BINANCE_SPOT_USDT_CURATED100_QV24H_V1`

Generated at (UTC): `2026-09-12T10:55:14.985977+00:00`

Source API: `https://data-api.binance.vision`

## Selection rules

1. Start from a curated / priority list of established crypto bases (majors, large L1/L2, large DeFi, known memes).
2. Intersect with Binance markets that are currently `TRADING`, quote=`USDT`, spot-capable.
3. Exclude:
   - leveraged tokens (`UP`/`DOWN`/`BULL`/`BEAR`, leveraged `L`/`S` suffixes)
   - non-ASCII / invalid bases
   - stablecoin / fiat bases
   - tokenized-equity wrappers (heuristic like `NVDAB`/`MSTRB`, with crypto allowlist so `SHIB` is kept)
4. Force-include: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`, `BNB/USDT`, `XRP/USDT`
5. Force-include priority established majors when listed.
6. Fill remaining seats by descending 24h USDT `quoteVolume` among curated live markets.
7. If still short of 100, fill from other filtered liquid markets (documented in selection_rule counts).

### Why not "first 100 Binance symbols"?

Raw exchange order and raw volume dumps include leveraged tokens, obscure listings,
and transient high-volume noise. The curated ∩ live ∩ volume approach keeps the
universe interpretable for a dry-run observation test.

## Final universe summary

- Final count: **100**
- Selection rule counts: `{"must_include": 5, "priority_established": 76, "curated_top_volume": 19}`
- Min selected 24h quoteVolume (USDT): **235373.33**

## Survivorship / look-ahead bias warning

**This 100-coin universe is for CURRENT dry-run / live-market observation.**

It reflects assets that are listed and liquid **today**. It does **not** represent
the historical top-100 for 2024 / 2025 / earlier periods.

Do **not** claim historical strategy quality from backtests that use today's
membership without a date-aware universe. Any historical run using this list is
subject to **survivorship bias** and must be labeled as such.

Historical research should eventually use point-in-time universe membership.

## Reproducibility

```bash
python scripts/build_binance_universe.py
python scripts/download_binance_universe_data.py --days 800 --min-candles 60
```

Artifacts:

- `user_data/universes/binance_spot_usdt_top100.json`
- `user_data/universes/binance_spot_usdt_top100_pairs.txt`
