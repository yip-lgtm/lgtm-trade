#!/bin/bash
# Check VPS state
/tmp/sshcmd.exp "echo '=== FILES ===' && ls -la /tmp/btc_5m_*.json /tmp/btc_5m_*.jsonl /tmp/ict_*.json /tmp/ict_*.jsonl 2>&1" 2>&1 | tail -15
echo ""
echo "=== JSON validity ==="
/tmp/sshcmd.exp "python3 -c \"
import json
files = ['/tmp/btc_5m_relax.json', '/tmp/btc_5m_state_v3.json', '/tmp/ict_pending_trades.json', '/tmp/ict_daily_stats.json', '/tmp/ict_rolling_metrics.json', '/tmp/ict_suspended_symbols.json']
for f in files:
    try:
        with open(f) as fp:
            content = fp.read().strip()
            if not content:
                print(f'{f}: EMPTY')
                continue
            json.loads(content)
        print(f'{f}: OK')
    except FileNotFoundError:
        print(f'{f}: MISSING')
    except json.JSONDecodeError as e:
        print(f'{f}: INVALID - {e}')

# Check JSONL
import os
for f in ['/tmp/btc_5m_trades.jsonl', '/tmp/ict_settled_trades.jsonl']:
    if not os.path.exists(f):
        print(f'{f}: MISSING')
        continue
    bad = 0
    good = 0
    with open(f) as fp:
        for line in fp:
            line = line.strip()
            if not line: continue
            try:
                json.loads(line)
                good += 1
            except:
                bad += 1
    print(f'{f}: {good} good, {bad} bad')
\"" 2>&1 | tail -20
