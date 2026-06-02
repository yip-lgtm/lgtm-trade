#!/usr/bin/env python3
"""Download 60 days of 15min data via direct Yahoo Finance CSV URL"""
import pandas as pd
import time
import urllib.request
from datetime import datetime, timedelta

symbols = ['MES=F', 'MNQ=F', 'M2K=F', 'MYM=F', 'M6E=F', 'M6A=F', 'MCL=F']
files = ['MES.F.csv', 'MNQ.F.csv', 'M2K.F.csv', 'MYM.F.csv', 'M6E.F.csv', 'M6A.F.csv', 'MCL.F.csv']

now = datetime(2026, 4, 25, 12, 0, 0)
start = int((now - timedelta(days=60)).timestamp())
end = int(now.timestamp())

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

for sym, fname in zip(symbols, files):
    url = f'https://query1.finance.yahoo.com/v7/finance/download/{sym}?interval=15m&period1={start}&period2={end}&events=history'
    print(f"  下載 {sym}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode('utf-8')
        lines = data.strip().split('\n')
        if len(lines) < 5:
            print(f"  ❌ {sym}: 數據不足")
            continue
        # Parse and convert to standard format
        rows = []
        for i, line in enumerate(lines):
            if i == 0:
                continue  # skip header
            parts = line.split(',')
            if len(parts) < 6:
                continue
            dt = parts[0]
            open_, high, low, close_, volume = parts[1], parts[2], parts[3], parts[4], parts[5]
            rows.append(f"{dt},{open_},{high},{low},{close_},{volume}")
        with open(fname, 'w') as f:
            f.write("datetime,open,high,low,close,volume\n")
            f.write('\n'.join(rows))
        print(f"  ✅ {fname} ({len(rows)} rows)")
    except Exception as e:
        print(f"  ❌ {sym} 失敗: {e}")
    time.sleep(5)

print("\n🎉 下載完成")
# Show date ranges
for fname in files:
    try:
        df = pd.read_csv(fname)
        print(f"  {fname}: {df['datetime'].min()} → {df['datetime'].max()} ({len(df)} rows)")
    except:
        print(f"  {fname}: 讀取失敗")