# Score4Window + Ichimoku hybrid (dry-run)

Adapted from uploaded community **ichiV1** + `berkalifreqtradeconfig`, aligned to our validated stack.

## Design

| Piece | Role |
|-------|------|
| **Score4Window `total_score`** | Primary entry gate (`>= 2`) — unchanged math |
| **Ichimoku leading cloud + EMA fan** | Confirmation filter (default ON) |
| **risk_pct sizing** | Unchanged SW4 stake formula |
| **ROI / stoploss** | SW4 defaults (`10%` / `-10%`) + optional ichi fan-cross exit |
| **Config** | `dry_run=true`, no secrets, Binance ~100 USDT pairs, market pricing |

## What we changed vs uploaded files

- `dry_run: false` → **`true`** (never ship live keys)
- Removed API / Telegram / JWT secrets
- Timeframe `15m`/`5m` → **`1d`** (SW4 system)
- Old `buy`/`sell` v2 API → **INTERFACE_VERSION 3** (`enter_long` / `exit_long`)
- No Heikin-Ashi OHLC overwrite (would corrupt SW4)
- Use **leading** senkou spans only (no chikou lookahead)
- Ichimoku periods: classic daily `9/26/52` (upload used `20/60/120/30` on 5m)
- Universe: our ~100 liquid USDT list (not the small 13-pair list / dead LUNA)

## Run (Windows)

```powershell
.\.venv\Scripts\Activate.ps1
python -m score_scan trade -c user_data/config_sw4_ichi_dryrun.json --userdir user_data --strategy Score4WindowIchiStrategy --score-scan hourly
```

Or without score-scan:

```powershell
freqtrade trade -c user_data/config_sw4_ichi_dryrun.json --userdir user_data --strategy Score4WindowIchiStrategy
```

## FreqAI note

Popular FreqAI setups treat Ichimoku / fan columns as **features** and keep a deterministic score or label. This hybrid stays deterministic; FreqAI can later consume `filt_ichi`, `fan_magnitude`, `leading_senkou_*` without replacing SW4 as the human-readable score core.
