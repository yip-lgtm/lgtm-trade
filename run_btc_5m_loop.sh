#!/bin/bash
# BTC 5m Bot Auto-Runner on California VPS
# Loops every 81s (each iteration runs one full trading cycle)
cd /home/ubuntu/btc_5m
while true; do
    echo "=== $(date -u) ===" >> btc_5m_runner.log
    /usr/bin/python3 btc_5m_bot.py >> btc_5m_runner.log 2>&1
    echo "---" >> btc_5m_runner.log
    sleep 81
done
