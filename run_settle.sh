#!/bin/bash
cd /home/node/.openclaw/workspace
echo "=== Empty pending test ==="
echo '[]' > /tmp/ict_pending_trades.json
python3 ict_daily_settlement.py settle
echo ""
echo "=== Summary ==="
python3 ict_daily_settlement.py summary
echo ""
echo "=== Stats file ==="
cat /tmp/ict_daily_stats.json 2>&1
