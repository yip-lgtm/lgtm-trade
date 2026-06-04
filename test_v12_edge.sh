#!/bin/bash
cd /home/node/.openclaw/workspace

echo "=== Edge case 1: No settled trades file ==="
rm -f /tmp/ict_settled_trades.jsonl
python3 ict_auto_iteration.py metrics 2>&1 | head -5

echo ""
echo "=== Edge case 2: Empty file ==="
touch /tmp/ict_settled_trades.jsonl
python3 ict_auto_iteration.py report 2>&1 | head -10

echo ""
echo "=== Edge case 3: Malformed JSON in trades ==="
echo "{ bad json" > /tmp/ict_settled_trades.jsonl
python3 ict_auto_iteration.py metrics 2>&1 | head -5

echo ""
echo "=== Edge case 4: Trade with missing fields ==="
echo '{"symbol": "TEST.F", "date": "2026-06-04", "outcome": "WIN_TP1", "pnl": 250}' > /tmp/ict_settled_trades.jsonl
python3 ict_auto_iteration.py metrics 2>&1 | head -10

echo ""
echo "=== Edge case 5: Settlement with malformed pending ==="
echo "not json" > /tmp/ict_pending_trades.json
python3 ict_daily_settlement.py settle 2>&1

echo ""
echo "=== Edge case 6: Settlement with no data file ==="
rm -f /tmp/ict_settled_trades.jsonl
python3 ict_daily_settlement.py settle 2>&1
