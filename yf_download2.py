#!/usr/bin/env python3
"""Download 60 days of 15min data via yfinance ticker.history()"""
import yfinance as yf
import pandas as pd
import time

symbols = ['MES=F', 'MNQ=F', 'M2K=F', 'MYM=F', 'M6E=F', 'M6A=F', 'MCL=F']
files = ['MES.F.csv', 'MNQ.F.csv', 'M2K.F.csv', 'MYM.F.csv', 'M6E.F.csv', 'M6A.F.csv', 'MCL.F.csv']

print("🚀 下載 60天 15min 數據...")
for sym, fname in zip(symbols, files):
    for attempt in range(3):
        try:
            print(f"  下載 {sym}...")
            ticker = yf.Ticker(sym)
            df = ticker.history(interval='15m', period='60d', prepost=True)
            if df.empty:
                raise ValueError("Empty dataframe")
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df.columns = ['open', 'high', 'low', 'close', 'volume']
            df.index = df.index.tz_localize(None)
            df.index.name = 'datetime'
            df = df.reset_index()
            df.to_csv(fname, index=False)
            print(f"  ✅ {fname} ({len(df)} rows, {df['datetime'].min()} → {df['datetime'].max()})")
            break
        except Exception as e:
            print(f"  ❌ {sym} 失敗: {e}, 重試({attempt+1}/3)...")
            time.sleep(10)
    time.sleep(3)

print("\n🎉 全部下載完成")