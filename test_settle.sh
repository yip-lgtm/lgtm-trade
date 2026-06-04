#!/bin/bash
cd /home/node/.openclaw/workspace
python3 -c "
import json
test_trades = [
    {'symbol': 'MNQ.F', 'date': '2026-06-03', 'signal_time': '2026-06-03T06:30:00+00:00', 'kz': 'LondonOpen', 'direction': 'SHORT', 'entry': 30580.0, 'sl': 30630.0, 'tp1': 30530.0, 'tp2': 30480.0, 'confidence': 6, 'reasons': ['OTE', 'MACD bearish', 'Order Block']},
    {'symbol': 'M2K.F', 'date': '2026-06-03', 'signal_time': '2026-06-03T06:00:00+00:00', 'kz': 'LondonOpen', 'direction': 'SHORT', 'entry': 2923.9, 'sl': 2928.0, 'tp1': 2918.9, 'tp2': 2913.9, 'confidence': 5, 'reasons': ['OTE', 'Liquidity sweep', 'MACD bearish']}
]
with open('/tmp/ict_pending_trades.json', 'w') as f:
    json.dump(test_trades, f, indent=2)
print('OK')
"
echo "---SETTLE---"
python3 ict_daily_settlement.py settle
echo "---SUMMARY---"
python3 ict_daily_settlement.py summary
