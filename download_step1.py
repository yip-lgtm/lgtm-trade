import yfinance as yf
import pandas as pd

symbols = ['MES=F', 'MNQ=F', 'M2K=F', 'MYM=F', 'M6E=F', 'M6A=F', 'MCL=F']
file_names = ['MES.F.csv', 'MNQ.F.csv', 'M2K.F.csv', 'MYM.F.csv', 'M6E.F.csv', 'M6A.F.csv', 'MCL.F.csv']

for sym, fname in zip(symbols, file_names):
    print(f"下載 {sym} ...")
    df = yf.download(sym, interval='15m', period='60d', prepost=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    df.index.name = 'Datetime'
    df = df.reset_index()
    df.to_csv(fname, index=False)
    print(f"✅ {fname} 已更新 ({len(df)} 筆)")

print("🎉 全部最新數據已儲存！")