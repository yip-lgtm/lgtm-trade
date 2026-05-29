# Markov BTC Trader - Bonereaper Strategy

## Status: RUNNING (Dry-Run Mode)

## Files Created
```
/home/node/.openclaw/workspace/state/
├── .env                    # Config (PRIVATE_KEY left blank, awaiting your input)
├── trader.js               # Main trading bot (Markov Chain logic)
├── ecosystem.config.json   # PM2 process manager config
├── state.json              # Runtime state (auto-created)
├── trades.json             # Trade log (auto-created)
├── stats.json              # Nightly review stats (auto-created)
└── run-trader.sh          # Manual start script
```

## Architecture
- **Markov Chain**: N=3 state length, learns from 30-lookback 5m candles
- **Signal**: Enter when continuation probability p̂ ≥ 0.87 (auto-tunable)
- **Edge**: Δ = p̂ − 0.5 must exceed MIN_EDGE (0.03 default)
- **Data Source**: Binance public API (BTC/USDT 5m klines)
- **Execution**: Polymarket CLOB API via py_clob_client v2 (Node.js wrapper)
- **Process Manager**: PM2 (auto-restart, memory limit 500MB)

## PM2 Commands
```bash
pm2 status                   # Check status
pm2 logs markov-btc-trader   # View logs
pm2 stop markov-btc-trader   # Stop
pm2 restart markov-btc-trader # Restart
```

## Current Cycle
First cycle ran at: 2026-05-28 03:53 UTC
- Prob: 0.3750, Direction: down
- No signal (prob < 0.87 threshold)
- Markov chain still learning — will improve over next cycles

## To Add Private Key & Go Live
1. Edit `/home/node/.openclaw/workspace/state/.env`
2. Set `PRIVATE_KEY=0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`
3. Set `DRY_RUN=false`
4. Run: `pm2 restart markov-btc-trader`

## Telegram Setup (optional)
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in .env for real-time notifications.