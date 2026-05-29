#!/bin/bash
# BTC 5m Trader - Telegram Signal Sender
# Usage: ./send_signal.sh "<message>"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
fi

MESSAGE="$1"

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set"
    exit 1
fi

if [ -z "$MESSAGE" ]; then
    echo "Usage: $0 <message>"
    exit 1
fi

URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
PAYLOAD='{"chat_id":"'"$TELEGRAM_CHAT_ID"'","text":"'"$MESSAGE"'","parse_mode":"HTML"}'

curl -s -X POST "$URL" -H "Content-Type: application/json" -d "$PAYLOAD" > /dev/null

echo "Signal sent at $(date -u)"