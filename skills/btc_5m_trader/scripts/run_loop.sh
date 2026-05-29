#!/bin/bash
# BTC 5m Trader - Main Trading Loop
# Usage: ./run_loop.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load env vars
if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
fi

# Check required vars
if [ -z "$POLYCLAW_PRIVATE_KEY" ] || [ -z "$RELAYER_API_KEY_ADDRESS" ]; then
    echo "ERROR: POLYCLAW_PRIVATE_KEY and RELAYER_API_KEY_ADDRESS must be set in config/.env"
    exit 1
fi

# Check Python dependencies
python3 -c "import httpx, asyncio" 2>/dev/null || {
    echo "Installing httpx..."
    python3 -m pip install httpx --quiet 2>/dev/null || pip3 install httpx 2>/dev/null || true
}

echo "=== BTC 5m Trader Loop Started at $(date -u) ==="
echo "DRY_RUN=${DRY_RUN:-true}"
echo "MIN_PROB=${MIN_PROB:-0.87}"
echo "MIN_EDGE=${MIN_EDGE:-0.03}"
echo ""

cd "$PROJECT_ROOT"

while true; do
    echo "[$(date -u)] Running trading cycle..."
    
    python3 btc_5m_bot.py
    
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        echo "Warning: bot exited with code $EXIT_CODE, retrying in 30s..."
        sleep 30
        continue
    fi
    
    INTERVAL=${CHECK_INTERVAL:-81}
    echo "[$(date -u)] Sleeping ${INTERVAL}s until next cycle..."
    sleep "$INTERVAL"
done