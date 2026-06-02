#!/bin/bash
# BTC 5m Bot Auto-Runner
# Runs every 81 seconds continuously

cd /home/node/.openclaw/workspace

while true; do
    echo "=== $(date -u) ===" >> btc_5m_runner.log
    /home/node/.openclaw/workspace/.btc_venv/bin/python3 btc_5m_urllib.py >> btc_5m_runner.log 2>&1
    echo "---" >> btc_5m_runner.log
    sleep 81
done
