# BTC 5m Trader Config

## .env File Template

```env
# === REQUIRED ===
POLYCLAW_PRIVATE_KEY=0x580c58cafb7f2a9b7b56fe9daa82e87407a3115233159e97239d293e24ab6127
RELAYER_API_KEY_ADDRESS=0x8AfCA7B78096fe4980Ff709626A8B464B17AC311
TELEGRAM_BOT_TOKEN=8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY
TELEGRAM_CHAT_ID=8475453959

# === TRADING CONFIG ===
DRY_RUN=true
MIN_PROB=0.87
MIN_EDGE=0.03
MAX_POSITION=5.0
MAX_DAILY_LOSS=30.0
CHECK_INTERVAL=81
STATE_WINDOW=4

# === FILTERS ===
ATR_MULT=0.8
VOL_MULT=0.6

# === PATHS ===
STATE_FILE=/home/node/.openclaw/workspace/btc_5m_state.json
CONFIG_FILE=/home/node/.openclaw/workspace/btc_5m_config.json
```

## Field Descriptions

| Field | Description |
|-------|-------------|
| `POLYCLAW_PRIVATE_KEY` | Wallet private key (0x... format) for signing L2 orders |
| `RELAYER_API_KEY_ADDRESS` | Funder wallet address on Polygon (0x... format) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (from @BotFather) for sending alerts |
| `TELEGRAM_CHAT_ID` | Your Telegram user ID (get via @userinfobot) |
| `DRY_RUN` | `true`=signals only, `false`=real trading |
| `MIN_PROB` | Minimum continuation probability threshold (0.80-0.95) |
| `MIN_EDGE` | Minimum edge = p̂ − q (0.01-0.05) |
| `MAX_POSITION` | Max $ per trade (default $5) |
| `MAX_DAILY_LOSS` | Max daily loss before pausing (default $30) |
| `CHECK_INTERVAL` | Seconds between trading cycles (default 81) |
| `STATE_WINDOW` | Number of candles for Markov state (default 4) |
| `ATR_MULT` | ATR filter multiplier (default 0.8) |
| `VOL_MULT` | Volume filter multiplier (default 0.6) |
