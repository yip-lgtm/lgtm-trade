#!/usr/bin/env python3
"""
LSTM 60-Day Backtest - Daily resampled data
Uses lstm_live.py style: seq_len=40, epochs=2
"""
import os, sys, json
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
sys.path.insert(0, '/home/node/.openclaw/workspace')

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from datetime import datetime

# Config - same as live
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

PRECISION = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2, 'MBT.F':2, 'MET.F':2, 'SIL.F':3, 'MGC.F':2}
TICK_VALUE = {'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'M6E.F':12.5, 'M6A.F':1, 'MCL.F':100, 'MBT.F':100, 'MET.F':100, 'SIL.F':5, 'MGC.F':10}
TICK_SIZE = {'MES.F':0.25, 'MNQ.F':0.25, 'M2K.F':0.25, 'M6E.F':0.0001, 'M6A.F':0.0001, 'MCL.F':0.01, 'MBT.F':0.01, 'MET.F':0.01, 'SIL.F':0.005, 'MGC.F':0.1}
CONTRACTS = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1, 'MBT.F':1, 'MET.F':1, 'SIL.F':1, 'MGC.F':2}
RESULTS_FILE = '/home/node/.openclaw/workspace/backtest_results.csv'

def load_daily(sym, csv_file):
    """Load CSV and resample to daily OHLC"""
    df = pd.read_csv(csv_file)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    daily = df.resample('1D').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()
    return daily

def compute_atr(high, low, close, period=14):
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)

def create_sequences(data, seq_len=40):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i-seq_len:i])
        y.append(data[i])
    return np.array(X), np.array(y)

def train_and_predict(closes, seq_len=40):
    """Train LSTM and get prediction"""
    if len(closes) < seq_len + 30: return None, None, None
    
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes.reshape(-1, 1)).flatten()
    
    X, y = create_sequences(scaled, seq_len)
    if len(X) < 20: return None, None, None
    
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
    
    last_seq = scaled[-seq_len:].reshape(1, seq_len, 1)
    pred = model.predict(last_seq, verbose=0)[0, 0]
    pred_clipped = np.clip(pred, scaled.min(), scaled.max())
    pred_price = scaler.inverse_transform([[pred_clipped]])[0, 0]
    actual_price = closes[-1]
    direction = 'long' if pred_price > actual_price else 'short'
    
    return direction, pred_price, actual_price

def run_backtest(sym, csv_file):
    print(f"  回測 {sym}...")
    df = load_daily(sym, csv_file)
    
    if len(df) < 60:
        print(f"  {sym}: 數據不足 ({len(df)} daily rows)，跳過")
        return []
    
    closes = df['close'].values
    atr = compute_atr(df['high'].values, df['low'].values, df['close'].values)
    
    # Walk forward - predict each day after 60-day train
    train_days = 60
    trades = []
    in_trade = False
    
    for i in range(train_days, len(closes)):
        # Train on data up to i, predict at i
        train_closes = closes[:i]
        if len(train_closes) < 50: continue
        
        direction, pred_price, actual_price = train_and_predict(train_closes)
        if direction is None: continue
        
        # ATR filter
        threshold = atr * 0.3
        if direction == 'long' and pred_price <= actual_price + threshold: continue
        if direction == 'short' and pred_price >= actual_price - threshold: continue
        
        tick = TICK_SIZE.get(sym, 0.25)
        pv = TICK_VALUE.get(sym, 5)
        contracts = CONTRACTS.get(sym, 2)
        prec = PRECISION.get(sym, 2)
        
        # SL: $200 per trade
        sl_ticks = 200 / (pv * contracts)
        sl_price = sl_ticks * tick
        
        entry = round(actual_price, prec)
        if direction == 'short':
            sl = round(entry + sl_price, prec)
            tp1 = round(entry - sl_price * 3, prec)
            tp2 = round(entry - sl_price * 6, prec)
        else:
            sl = round(entry - sl_price, prec)
            tp1 = round(entry + sl_price * 3, prec)
            tp2 = round(entry + sl_price * 6, prec)
        
        # Record trade
        trades.append({
            'symbol': sym,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'pred': round(pred_price, prec),
            'actual': round(actual_price, prec),
            'atr': round(atr, 4),
            'date': df.index[i].strftime('%Y-%m-%d')
        })
        print(f"    {sym}: {direction} @{entry} | SL={sl} | {df.index[i].strftime('%Y-%m-%d')}")
    
    return trades

# ====================== Main ======================
print("=" * 80)
print("🚀 LSTM 60天回測（Daily Resampled, seq_len=40, epochs=2）")
print("=" * 80)

all_trades = []
for sym, csv_file in CSV_FILES.items():
    trades = run_backtest(sym, csv_file)
    all_trades.extend(trades)

if all_trades:
    results_df = pd.DataFrame(all_trades)
    results_df.to_csv(RESULTS_FILE, index=False)
    
    # Summary
    total = len(results_df)
    longs = len(results_df[results_df['direction'] == 'long'])
    shorts = len(results_df[results_df['direction'] == 'short'])
    print(f"\n{'=' * 80}")
    print(f"📊 回測結果：共 {total} 筆交易")
    print(f"   Long: {longs} | Short: {shorts}")
    print(f"   結果已保存: {RESULTS_FILE}")
else:
    print("\n無交易記錄")