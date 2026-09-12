========================================
DRY-RUN OBSERVATION REPORT
========================================

Generated: 2026-09-12 13:08:36Z
Config: /workspace/user_data/config.json
DB: /workspace/tradesv3.dryrun.sqlite
Log: None

Period:
Start: None
End: None
Span hours: None
Restarts detected: None

Universe:
Pairs configured: 100
Unique pairs: 100
Duplicates: []
Non-USDT pairs: []
Pairs with local 1d data: 100
Pairs missing local 1d data: 0

Signals:
Entry signals (log-derived): 0
Exit signals (log-derived): 0
Rejected signals (log-derived): 0
Limitation: Exact raw strategy signals cannot be fully reconstructed without strategy instrumentation. Log-derived counts may undercount if logs were not saved.

Trades:
Trades created: 5
Trades currently open: 5
Trades closed: 0
Filled-like trades: 3
Average duration hours: N/A

Orders:
Orders created: 5
Orders open (unfilled): 2
Orders filled: 3
Orders cancelled: 0
Note: OPEN ORDER = unfinished dry-run/exchange order. OPEN TRADE = trades.is_open=1. Unfilled entry orders can appear as amount=0 open trades.

Performance:
Realized simulated PnL: N/A
Unrealized simulated PnL: N/A
Win rate: N/A
Profit factor: N/A
Average trade: N/A
Max drawdown: N/A

Health:
Network/API events: None
Strategy/system events: None
STRATEGY/SYSTEM ERRORS: unknown (no logs)

Top trade pairs:
- BNB/USDT: 1
- ETH/USDT: 1
- NEAR/USDT: 1
- SOL/USDT: 1
- ZEC/USDT: 1

Problematic orders/trades:
- {'kind': 'order', 'order_id': 'dry_run_buy_ETH/USDT_9ba75eb9-12f4-4349-9121-35c57963939d', 'pair': 'ETH/USDT', 'status': 'open', 'amount': 0.0119, 'filled': 0.0, 'age_minutes': 127.58, 'reasons': ['open_unusually_long'], 'note': 'OPEN ORDER (not a filled position)'}
- {'kind': 'order', 'order_id': 'dry_run_buy_SOL/USDT_ce2578d6-3803-4a5d-9154-54864fb94fe8', 'pair': 'SOL/USDT', 'status': 'open', 'amount': 0.122, 'filled': 0.0, 'age_minutes': 127.58, 'reasons': ['open_unusually_long'], 'note': 'OPEN ORDER (not a filled position)'}
- {'kind': 'trade', 'trade_id': 1, 'pair': 'ETH/USDT', 'amount': 0.0, 'open_rate': 2534.45, 'open_date': '2026-09-12 11:01:02.054483', 'reasons': ['open_trade_amount_zero'], 'note': 'Trade row exists with amount=0 (likely unfilled entry order)'}
- {'kind': 'trade', 'trade_id': 2, 'pair': 'SOL/USDT', 'amount': 0.0, 'open_rate': 102.2, 'open_date': '2026-09-12 11:01:02.343435', 'reasons': ['open_trade_amount_zero'], 'note': 'Trade row exists with amount=0 (likely unfilled entry order)'}

Data gaps:
- none detected from available logs

Safety:
dry_run=True
LIVE TRADING: DISABLED
exchange=binance
timeframe=1d
max_open_trades=5
stake_amount=unlimited
risk_pct=3.0
safe_to_continue_dry_run=True

Limitations:
- No log file found; signal/API/system metrics from logs are limited.

========================================
