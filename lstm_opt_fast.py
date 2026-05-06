#!/usr/bin/env python3
"""LSTM+ICT Parameter Optimizer - FAST version"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
import json
from datetime import datetime

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
TICK_VALUE = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'M6E.F':12.5,'M6A.F':1,'MCL.F':100,'MBT.F':100,'MET.F':100,'SIL.F':5,'MGC.F':10}
TICK_SIZE = {'MES.F':0.25,'MNQ.F':0.25,'M2K.F':0.25,'M6E.F':0.0001,'M6A.F':0.0001,'MCL.F':0.01,'MBT.F':0.01,'MET.F':0.01,'SIL.F':0.005,'MGC.F':0.1}
CONTRACTS = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'M6E.F':2,'M6A.F':2,'MCL.F':1,'MBT.F':1,'MET.F':1,'SIL.F':1,'MGC.F':2}

def load_daily(csv_file):
    df = pd.read_csv(csv_file)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    return daily

def create_sequences(data, seq_len):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i-seq_len:i])
        y.append(data[i])
    return np.array(X), np.array(y)

def calc_atr(high, low, close, period=14):
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)

def train_and_predict(closes, seq_len, lstm_units, epochs):
    if len(closes) < seq_len + 30: return None, None
    
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes.reshape(-1, 1)).flatten()
    
    X, y = create_sequences(scaled, seq_len)
    if len(X) < 20: return None, None
    
    train_size = int(len(X) * 0.8)
    xt, yt = X[:train_size], y[:train_size]
    
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=[seq_len, 1]),
        tf.keras.layers.LSTM(lstm_units, return_sequences=False),
        tf.keras.layers.Dense(12, activation='relu'),
        tf.keras.layers.Dense(1)
    ])
    model.compile(optimizer=tf.keras.optimizers.Adam(0.02), loss='mse')
    model.fit(xt, yt, epochs=epochs, batch_size=8, verbose=0)
    
    preds = []
    for i in range(train_size, len(X)):
        p = model.predict(X[i:i+1], verbose=0)[0, 0]
        p = np.clip(p, scaled.min(), scaled.max())
        pred_price = scaler.inverse_transform([[p]])[0, 0]
        actual_price = scaler.inverse_transform([[y[i]]])[0, 0]
        direction = 1 if pred_price > actual_price else -1
        preds.append((direction, actual_price, pred_price))
    
    return preds, scaler

# Load data
print("Loading data...")
all_data = {}
for sym, csv_file in CSV_FILES.items():
    try:
        df = load_daily(csv_file)
        if len(df) >= 60:
            all_data[sym] = df
    except:
        pass
print(f"Loaded {len(all_data)} symbols")

# FAST GRID - only 12 combinations
params = [
    # (seq_len, lstm_units, epochs, threshold)
    (20, 24, 2, 0.3),
    (30, 24, 2, 0.3),
    (40, 24, 2, 0.3),
    (40, 12, 2, 0.3),
    (40, 48, 2, 0.3),
    (40, 24, 1, 0.3),
    (40, 24, 3, 0.3),
    (40, 24, 2, 0.1),
    (40, 24, 2, 0.2),
    (40, 24, 2, 0.5),
    (40, 24, 2, 0.4),
    (40, 24, 2, 0.35),
]

results = []
start_time = datetime.now()

for seq_len, lstm_units, epochs, threshold in params:
    print(f"\nTesting: seq={seq_len}, units={lstm_units}, ep={epochs}, thr={threshold}")
    
    total_pnl = 0
    total_trades = 0
    total_wins = 0
    
    for sym, df in all_data.items():
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        
        train_size = int(len(closes) * 0.8)
        train_closes = closes[:train_size + 20]
        
        result = train_and_predict(train_closes, seq_len, lstm_units, epochs)
        if result[0] is None: continue
        
        preds = result[0]
        test_highs = highs[train_size:]
        test_lows = lows[train_size:]
        test_closes = closes[train_size:]
        test_atr = calc_atr(test_highs, test_lows, test_closes) if len(test_highs) > 14 else calc_atr(highs, lows, closes)
        
        for i, (direction, actual, pred) in enumerate(preds):
            # ATR filter
            if abs(pred - actual) < test_atr * threshold: continue
            
            tick = TICK_SIZE.get(sym, 0.25)
            pv = TICK_VALUE.get(sym, 5)
            contracts = CONTRACTS.get(sym, 2)
            sl_ticks = 200 / (pv * contracts)
            sl_price = sl_ticks * tick
            
            # TP1 P&L
            if direction == 1:
                pnl = sl_price * 3 / tick * pv * contracts
            else:
                pnl = sl_price * 3 / tick * pv * contracts
            
            total_pnl += pnl
            total_trades += 1
            if pnl > 0: total_wins += 1
    
    win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
    
    results.append({
        'seq_len': seq_len,
        'lstm_units': lstm_units,
        'epochs': epochs,
        'threshold': threshold,
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'win_rate': round(win_rate, 1)
    })
    print(f"  → P&L: ${total_pnl:.0f} | Trades: {total_trades} | Win%: {win_rate:.0f}%")

elapsed = (datetime.now() - start_time).total_seconds()
print(f"\nCompleted in {elapsed:.0f} seconds")

# Results
results_df = pd.DataFrame(results).sort_values('total_pnl', ascending=False)
print("\n" + "=" * 60)
print("OPTIMIZATION RESULTS (sorted by P&L)")
print("=" * 60)
print(results_df.to_string(index=False))

# Best
best = results_df.iloc[0]
best_params = {
    'seq_len': int(best['seq_len']),
    'lstm_units': int(best['lstm_units']),
    'epochs': int(best['epochs']),
    'atr_threshold': float(best['threshold'])
}
with open('/home/node/.openclaw/workspace/best_params.json', 'w') as f:
    json.dump(best_params, f, indent=2)

print(f"\n🏆 BEST: seq={best['seq_len']}, units={best['lstm_units']}, ep={best['epochs']}, thr={best['threshold']}")
print(f"   P&L: ${best['total_pnl']} | Trades: {best['total_trades']} | Win%: {best['win_rate']}%")
print(f"\nSaved: /home/node/.openclaw/workspace/best_params.json")