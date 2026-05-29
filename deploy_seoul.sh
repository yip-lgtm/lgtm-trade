#!/bin/bash
# OpenClaw Seoul VPS Auto-Deploy Script
# Usage: bash setup_openclaw.sh

set -e

GATEWAY_PORT=18789
CONFIG_DIR="$HOME/.openclaw"
CONFIG_FILE="$CONFIG_DIR/openclaw.json"

echo "=========================================="
echo "  OpenClaw Seoul VPS Auto-Deploy"
echo "=========================================="

# 1. Create config directory
echo "[1/6] Creating config directory..."
mkdir -p "$CONFIG_DIR"

# 2. Get API Keys from environment or prompt
echo "[2/6] Checking API keys..."

# Polymarket keys (from env or literal values)
POLYMARKET_PRIVATE_KEY="${POLYMARKET_PRIVATE_KEY:-0x580c58cafb7f2a9b7b56fe9daa82e87407a3115233159e97239d293e24ab6127}"
POLYMARKET_API_KEY="${POLYMARKET_API_KEY:-019e6adf-f3d7-70b0-9d00-7b372f9dba35}"
POLYMARKET_API_SECRET="${POLYMARKET_API_SECRET:-}"
POLYMARKET_API_PASSPHRASE="${POLYMARKET_API_PASSPHRASE:-}"

# OpenRouter API key (from env)
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-OPENROUTER_API_KEY_PLACEHOLDER}"

# Telegram Bot Token (prompt if not set)
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "  Telegram Bot Token not found in TELEGRAM_BOT_TOKEN env."
  echo "  Please set it before running: export TELEGRAM_BOT_TOKEN='your_token'"
  exit 1
fi

# 3. Generate config.json
echo "[3/6] Generating config.json..."

cat > "$CONFIG_FILE" << 'CONFIG_EOF'
{
  "gateway": {
    "mode": "local",
    "port": 18789,
    "logLevel": "info",
    "dangerouslyDisableDeviceAuth": false
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "TELEGRAM_BOT_TOKEN_PLACEHOLDER",
      "dmPolicy": "allowlist",
      "allowFrom": ["8475453959"]
    }
  },
  "plugins": {
    "entries": {
      "minimax": {
        "enabled": true
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "openrouter/anthropic/claude-sonnet-4"
      }
    }
  },
  "openrouter": {
    "apiKey": "OPENROUTER_API_KEY_PLACEHOLDER"
  },
  "polymarket": {
    "privateKey": "POLYMARKET_PRIVATE_KEY_PLACEHOLDER",
    "apiKey": "POLYMARKET_API_KEY_PLACEHOLDER",
    "apiSecret": "POLYMARKET_API_SECRET_PLACEHOLDER",
    "apiPassphrase": "POLYMARKET_API_PASSPHRASE_PLACEHOLDER",
    "relayerAddress": "0x8AfCA7B78096fe4980Ff709626a8B464B17AC311",
    "clobEndpoint": "https://clob.polymarket.com",
    "gammaEndpoint": "https://gamma-api.polymarket.com"
  },
  "chainstack": {
    "nodeUrl": "https://1rpc.io/matic",
    "chainId": 137
  },
  "BTC_5m_Bot": {
    "enabled": false,
    "MIN_PROB": 0.87,
    "MIN_EDGE": 0.03,
    "MAX_POSITION": 5,
    "MAX_DAILY_LOSS": 30,
    "CHECK_INTERVAL": 81,
    "STATE_WINDOW": 4,
    "DRY_RUN": false,
    "atrThreshold": 0.8,
    "volThreshold": 0.6
  }
}
CONFIG_EOF

# Replace placeholders
sed -i "s/TELEGRAM_BOT_TOKEN_PLACEHOLDER/$TELEGRAM_BOT_TOKEN/g" "$CONFIG_FILE"
sed -i "s/OPENROUTER_API_KEY_PLACEHOLDER/$OPENROUTER_API_KEY/g" "$CONFIG_FILE"
sed -i "s/POLYMARKET_PRIVATE_KEY_PLACEHOLDER/$POLYMARKET_PRIVATE_KEY/g" "$CONFIG_FILE"
sed -i "s/POLYMARKET_API_KEY_PLACEHOLDER/$POLYMARKET_API_KEY/g" "$CONFIG_FILE"
sed -i "s/POLYMARKET_API_SECRET_PLACEHOLDER/${POLYMARKET_API_SECRET:-}/g" "$CONFIG_FILE"
sed -i "s/POLYMARKET_API_PASSPHRASE_PLACEHOLDER/${POLYMARKET_API_PASSPHRASE:-}/g" "$CONFIG_FILE"

echo "  Config written to $CONFIG_FILE"

# 4. Install OpenClaw
echo "[4/6] Installing OpenClaw..."
if command -v openclaw &> /dev/null; then
  echo "  OpenClaw already installed, skipping npm install"
else
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
  npm install -g openclaw
fi

# 5. Enable and start gateway service
echo "[5/6] Setting up gateway service..."
openclaw gateway enable
openclaw gateway start

# 6. Verify
echo "[6/6] Verifying..."
sleep 3
openclaw gateway status

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "  Telegram bot: @$(echo $TELEGRAM_BOT_TOKEN | cut -d: -f2)_bot"
echo "  Gateway: http://localhost:$GATEWAY_PORT"
echo "=========================================="