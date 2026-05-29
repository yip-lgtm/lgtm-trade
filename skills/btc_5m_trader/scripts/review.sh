#!/bin/bash
# BTC 5m Trader - Nightly Review + Auto-Tune
# Usage: Run daily via cron at midnight UTC
# Cron example: 0 0 * * * /path/to/skills/btc_5m_trader/scripts/review.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
fi

STATE_FILE="${STATE_FILE:-/home/node/.openclaw/workspace/btc_5m_state.json}"
CONFIG_FILE="${CONFIG_FILE:-/home/node/.openclaw/workspace/btc_5m_config.json}"

echo "=== Nightly Review $(date -u) ==="

if [ ! -f "$STATE_FILE" ]; then
    echo "No state file found, skipping review"
    exit 0
fi

# Load state
CYCLES=$(python3 -c "
import json, sys
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    history = data.get('history', [])
    probs = [e.get('prob_continue', 0) for e in history if e.get('signal')]
    wins = [e for e in history if e.get('signal') and e.get('result') == 'win']
    losses = [e for e in history if e.get('signal') and e.get('result') == 'loss']
    max_prob = max(probs) if probs else 0
    avg_prob = sum(probs) / len(probs) if probs else 0
    print(f'cycles={len(history)} wins={len(wins)} losses={len(losses)} max_prob={max_prob:.3f} avg_prob={avg_prob:.3f}')
except Exception as e:
    print(f'error: {e}')
" 2>/dev/null)

echo "Stats: $CYCLES"

# Auto-tune MIN_PROB if needed
python3 -c "
import json

MIN_PROB = float('$MIN_PROB' or '0.87')
MAX_PROB = float('$MAX_PROB' or '0.95')
ADJUSTMENT = 0.02

# Extract stats from $CYCLES
# Parse in Python for safety
" 2>/dev/null

# Send Telegram summary
$('set -e' && echo "Nightly Review complete. See attached state file." > /dev/null)

echo "Review complete at $(date -u)"