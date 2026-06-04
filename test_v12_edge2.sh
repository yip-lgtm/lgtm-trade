#!/bin/bash
cd /home/node/.openclaw/workspace

echo "=== Edge case A: Malformed pending ==="
echo "not json" > /tmp/ict_pending_trades.json
python3 ict_daily_settlement.py settle 2>&1 | head -3

echo ""
echo "=== Edge case B: Empty pending file ==="
> /tmp/ict_pending_trades.json
python3 ict_daily_settlement.py settle 2>&1 | head -3

echo ""
echo "=== Edge case C: No pending file ==="
rm -f /tmp/ict_pending_trades.json
python3 ict_daily_settlement.py settle 2>&1 | head -3

echo ""
echo "=== Edge case D: No settled file + report ==="
rm -f /tmp/ict_settled_trades.jsonl /tmp/ict_daily_stats.json
python3 ict_auto_iteration.py report 2>&1 | head -5

echo ""
echo "=== Edge case E: Corrupt daily stats ==="
echo "bad json" > /tmp/ict_daily_stats.json
python3 ict_auto_iteration.py report 2>&1 | head -5

echo ""
echo "=== Edge case F: Corrupt settled file with bad lines ==="
echo '{"id": "1", "date": "2026-06-04", "outcome": "WIN_TP1", "pnl": 250, "symbol": "TEST", "direction": "LONG"}' > /tmp/ict_settled_trades.jsonl
echo "garbage line" >> /tmp/ict_settled_trades.jsonl
echo '{"id": "2", "date": "2026-06-04", "outcome": "LOSS", "pnl": -100, "symbol": "TEST", "direction": "SHORT"}' >> /tmp/ict_settled_trades.jsonl
python3 ict_auto_iteration.py metrics 2>&1 | head -10
