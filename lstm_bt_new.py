#!/usr/bin/env python3
"""LSTM Backtest - NEW parameters: seq=20, threshold=0.4, EMA+FVG filters"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

CSV_FILES = {
    'MES.F': '/home/node/.openclaw/workspace/MES.F.csv',
    'MNQ.F': '/home/node/.openclaw/workspace/MNQ.F.csv',
    'M2K.F': '/home/node/.openclaw/workspace/M2K.F.csv',
    'M6E.F': '/home/node/.openclaw/workspace/M6E.F.csv',
    'M6A.F': '/home/node/.openclaw/workspace/M6A.F.csv',
    'MCL.F': '/home/node/.openclaw/workspace/MCL.F.csv',
    'MBT.F': '/home/node/.openclaw/workspace/MBT.F.csv',
    'MET.F': '/home/node/.openclaw/workspace/MET.F.csv',
    'SIL.F': '/home/node/.openclaw/workspace/SIL.F.csv',
    'MGC.F': '/home/node/.openclaw/workspace/MGC.F.csv',
}
POINT_VALUE = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'M6E.F':12500,'M6A.F':10000,'MCL.F':100,'MBT.F':0.1,'MET.F':0.1,'SIL.F':5,'MGC.F':10}
CONTRACTS = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'M6E.F':2,'M6A.F':2,'MCL.F':1,'MBT.F':1,'MET.F':1,'SIL.F':1,'MGC.F':2}

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf

def load_daily(csv_file):
    df = pd.read_csv(csv_file)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    return daily

def create_sequences(data, seq_len=20):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i-seq_len:i])
        y.append(data[i])
    return np.array(X), np.array(y)

def calc_ema(df, fast=12, slow=26):
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean().iloc[-1]
    return ema_fast, ema_slow

def check_fvg(df):
    if len(df) < 3:
        return False, False
    fvg_bull = df['low'].iloc[-2] > df['high'].iloc[-3]
    fvg_bear = df['high'].iloc[-2] < df['low'].iloc[-3]
    return fvg_bull, fvg_bear

def calc_atr(high, low, close, period=14):
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)

def get_signal(pred, actual, atr, ema_fast, ema_slow, fvg_bull, fvg_bear, threshold_mult=0.4):
    threshold = atr * threshold_mult
    
    if pred > actual + threshold:
        lstm_dir = 'long'
    elif pred < actual - threshold:
        lstm_dir = 'short'
    else:
        return 'no_signal'
    
    trend_bull = ema_fast > ema_slow
    trend_bear = ema_fast < ema_slow
    
    if lstm_dir == 'long' and (trend_bull or fvg_bull):
        return 'long'
    elif lstm_dir == 'short' and (trend_bear or fvg_bear):
        return 'short'
    return 'no_signal'

def train_and_predict_all(closes, seq_len=20):
    if len(closes) < seq_len + 30: return None
    
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes.reshape(-1, 1)).flatten()
    
    X, y = create_sequences(scaled, seq_len)
    if len(X) < 20: return None
    
    train_size = int(len(X) * 0.8)
    xt, yt = X[:train_size], y[:train_size]
    
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=[seq_len, 1]),
        tf.keras.layers.LSTM(24, return_sequences=False),
        tf.keras.layers.Dense(12, activation='relu'),
        tf.keras.layers.Dense(1)
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(0.02), loss='mse')
    model.fit(xt, yt, epochs=2, batch_size=4, verbose=0)
    
    preds, acts = [], []
    for i in range(train_size, len(X)):
        p = model.predict(X[i:i+1], verbose=0)[0, 0]
        p = np.clip(p, scaled.min(), scaled.max())
        pred_price = scaler.inverse_transform([[p]])[0, 0]
        actual_price = scaler.inverse_transform([[y[i]]])[0, 0]
        preds.append((pred_price, actual_price))
        acts.append(actual_price)
    
    return preds, acts

def run_backtest(sym, csv_file):
    print(f"  {sym}...", end=' ', flush=True)
    df = load_daily(csv_file)
    if len(df) < 60:
        print(f"數據不足({len(df)}天)")
        return []
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    
    result = train_and_predict_all(closes)
    if result is None:
        print("訓練失敗")
        return []
    
    preds, actuals = result
    
    trades = []
    for i, (pred_price, actual_price) in enumerate(preds):
        idx = int(len(closes) * 0.8) + i
        
        if idx >= len(df):
            continue
        
        ema_fast, ema_slow = calc_ema(df.iloc[:idx+1])
        fvg_bull, fvg_bear = check_fvg(df.iloc[:idx+1])
        atr = calc_atr(highs[:idx+1], lows[:idx+1], closes[:idx+1])
        
        signal = get_signal(pred_price, actual_price, atr, ema_fast, ema_slow, fvg_bull, fvg_bear, 0.4)
        
        if signal == 'no_signal':
            continue
        
        pv = POINT_VALUE.get(sym, 5)
        contracts = CONTRACTS.get(sym, 2)
        sl_price = 200 / (pv * contracts)
        
        entry = actual_price
        if signal == 'short':
            sl = entry + sl_price
            tp1 = entry - sl_price * 3
        else:
            sl = entry - sl_price
            tp1 = entry + sl_price * 3
        
        trades.append({
            'symbol': sym, 'direction': signal, 'entry': round(entry, 4),
            'sl': round(sl, 4), 'tp1': round(tp1, 4),
            'pred': round(pred_price, 4), 'actual': round(actual_price, 4),
            'date': df.index[idx].strftime('%Y-%m-%d')
        })
    
    print(f"{len(trades)}筆")
    return trades

print("=" * 60)
print("LSTM Backtest (NEW: seq=20, thr=0.4, EMA+FVG)")
print("=" * 60)
all_trades = []
for sym, csv_file in CSV_FILES.items():
    trades = run_backtest(sym, csv_file)
    all_trades.extend(trades)

if all_trades:
    pd.DataFrame(all_trades).to_csv('/home/node/.openclaw/workspace/backtest_new_params.csv', index=False)
    longs = len([t for t in all_trades if t['direction']=='long'])
    shorts = len([t for t in all_trades if t['direction']=='short'])
    print(f"\n共 {len(all_trades)} 筆: Long={longs} Short={shorts}")
    print("已保存: /home/node/.openclaw/workspace/backtest_new_params.csv")
else:
    print("\n無交易")