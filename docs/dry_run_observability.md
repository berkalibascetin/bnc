# Dry-run observability and automated reporting for Freqtrade

This layer inspects an existing dry-run bot and produces structured evidence.

It does **not** change strategy logic, risk settings, or enable live trading.

## What it measures

| Area | Meaning |
|---|---|
| Strategy behavior | Signal heuristics from logs (if logs exist) |
| Trade/order behavior | Rows in dry-run SQLite (`trades`, `orders`) |
| Data/API health | Network/timeout/ticker errors from logs |
| System health | Python/strategy/config crashes from logs |
| Test quality | Sleep gaps, missing logs/data limitations |

## Important distinctions

- **Signal**: strategy interest in entering/exiting (log-derived; may be incomplete)
- **Order**: exchange/dry-run order object (may be open/unfilled)
- **Trade**: Freqtrade trade row (`is_open=1` does not always mean filled size > 0)

An open order with `amount=0` is **not** a filled position.

## Generate a report

From the project root:

```bash
python -m dry_run_observability report
```

Optional filters:

```bash
python -m dry_run_observability report --since 2026-09-12 --until 2026-09-14
python -m dry_run_observability report --config user_data/config.json --db tradesv3.dryrun.sqlite --log path/to/freqtrade.log
python -m dry_run_observability report --output-dir reports
```

Outputs:

- `reports/dry_run_report.json`
- `reports/dry_run_report.md`

## Safety behavior

Before reporting, the tool checks `dry_run=true`.

If `dry_run` is false, it aborts and does not pretend the run is safe.

This tool never sets `dry_run=false`.

## Network errors vs strategy failures

Temporary Binance `NetworkError` / websocket timeouts are classified under **API health**.

They are **not** counted as strategy failures.

Strategy/system failures are separate (tracebacks, config errors, crashes).

## Sleep / downtime

If the PC sleeps, logs show a time gap.

The reporter marks gaps ≥ 30 minutes as:

`DATA COLLECTION GAP`

Those periods are not treated as normal observation time.

## Metrics that may be N/A

With little data, these can be `N/A` / `null`:

- win rate
- profit factor
- average trade duration
- unrealized PnL
- max drawdown

A 1–2 day dry-run validates operations. It does **not** prove profitability.

## Recommended 1–2 day workflow

1. Keep PC awake (disable sleep)
2. Run dry-run on the ~100-pair universe
3. Persist logs to a file if possible
4. Generate report:

```bash
python -m dry_run_observability report
```

5. Review:
   - safety (`dry_run=true`)
   - universe size
   - open order vs open trade
   - network error rate
   - strategy/system errors (expect 0)
   - data gaps

Do not optimize thresholds from this short sample.
