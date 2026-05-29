---
name: btc-5m-trader
description: Polymarket BTC 5-minute up/down Markov trading bot. Use when: (1) user asks to run/manage BTC 5m trading bot, (2) wants to check trading signals or status, (3) Telegram commands like /btc start|stop|status|info|prob|edge|dryrun, (4) configuring Markov chain parameters, (5) nightly review and auto-tuning. Supports DRY_RUN mode and live CLOB execution.
---

# BTC 5m Trader

## Commands

| Command | Description |
|---------|-------------|
| `/btc status` | Bot status + last signal |
| `/btc info` | Current config parameters |
| `/btc cycles` | Cycle history stats |
| `/btc start` | Start trading loop |
| `/btc stop` | Stop trading loop |
| `/btc dryrun on\|off` | Toggle DRY_RUN |
| `/btc prob <0.87>` | Set MIN_PROB |
| `/btc edge <0.03>` | Set MIN_EDGE |
| `/btc help` | Show all commands |

## Files

```
btc_5m_trader/
├── SKILL.md              ← This file
├── btc_5m_bot.py         ← Main trading engine
├── btc_5m_commands.py    ← Telegram command handler
├── config/
│   └── .env.template    ← Config template
├── references/
│   ├── config.md        ← Detailed field reference
│   └── trading.md       ← Markov + ATR/Vol logic
└── scripts/
    ├── run_loop.sh      ← Main loop runner
    ├── send_signal.sh   ← Telegram alert helper
    └── review.sh        ← Nightly review + auto-tune
```

## DRY_RUN / LIVE

`DRY_RUN=true` (default) → signals only, no orders
`DRY_RUN=false` → real Polymarket orders via CLOB API

## Key Parameters

| Param | Default | Description |
|-------|---------|-------------|
| `MIN_PROB` | 0.87 | Min continuation prob |
| `MIN_EDGE` | 0.03 | Min edge (p̂ − q) | 
| `STATE_WINDOW` | 4 | Markov lookback candles |
| `ATR_MULT` | 0.8 | ATR filter multiplier |
| `VOL_MULT` | 0.6 | Volume filter multiplier |
| `CHECK_INTERVAL` | 81 | Cycle interval (seconds) |

## Trading Logic

See `references/trading.md` for full details.

1. Fetch BTC 5m candles from OKX
2. Compute streak-based Markov states
3. Build ATR+Vol filtered transition matrix
4. Predict next direction probability p̂
5. Signal if p̂ ≥ MIN_PROB and edge ≥ MIN_EDGE
6. Execute via Polymarket CLOB (or DRY_RUN log)

## Position Sizing

Default: 2% per trade (`MAX_POSITION=$5`)

## Nightly Review

Cron at midnight UTC: `scripts/review.sh`
- Loads last N cycles from state file
- Win rate + avg prob stats
- Auto-bump MIN_PROB if performance poor

## Required Env Vars

See `config/.env.template`:
- `POLYCLAW_PRIVATE_KEY` — wallet private key
- `RELAYER_API_KEY_ADDRESS` — funder address
- `TELEGRAM_BOT_TOKEN` — alert bot token
- `TELEGRAM_CHAT_ID` — your Telegram user ID
