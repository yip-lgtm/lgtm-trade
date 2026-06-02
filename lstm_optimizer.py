#!/usr/bin/env python3
"""LSTM+ICT Parameter Optimizer - Grid Search"""
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from itertools import product
import json
from datetime import datetime

# ========== CONFIG ==========
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

# ========== LOAD DATA ==========
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

# ========== TRAIN & PREDICT ==========
def train_and_predict_all(closes, seq_len, lstm_units, epochs):
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
    model.fit(xt, yt, epochs=epochs, batch_size=4, verbose=0)
    
    preds, acts = [], []
    for i in range(train_size, len(X)):
        p = model.predict(X[i:i+1], verbose=0)[0, 0]
        p = np.clip(p, scaled.min(), scaled.max())
        pred_price = scaler.inverse_transform([[p]])[0, 0]
        actual_price = scaler.inverse_transform([[y[i]]])[0, 0]
        direction = 1 if pred_price > actual_price else -1
        preds.append(direction)
        acts.append(actual_price)
    
    return preds, acts

# ========== EVALUATE ==========
def evaluate_trades(preds, acts, atr, threshold_mult, sym, closes, trade_idx_start):
    tick = TICK_SIZE.get(sym, 0.25)
    pv = TICK_VALUE.get(sym, 5)
    contracts = CONTRACTS.get(sym, 2)
    threshold = atr * threshold_mult
    
    trades = []
    in_trade = False
    
    for i, (direction, actual) in enumerate(zip(preds, acts)):
        # Check entry condition
        entry = actual
        if direction == 1 and entry <= entry + threshold: continue
        if direction == -1 and entry >= entry - threshold: continue
        
        # Calculate SL/TP
        sl_ticks = 200 / (pv * contracts)
        sl_price = sl_ticks * tick
        
        if direction == 1:  # Long
            sl = entry - sl_price
            tp1 = entry + sl_price * 3
            tp2 = entry + sl_price * 6
        else:  # Short
            sl = entry + sl_price
            tp1 = entry - sl_price * 3
            tp2 = entry - sl_price * 6
        
        # Simulate exit at TP1 (simplified)
        if direction == 1:
            pnl = (tp1 - entry) / tick * pv * contracts
        else:
            pnl = (entry - tp1) / tick * pv * contracts
        
        trades.append(pnl)
    
    if not trades:
        return {'count': 0, 'pnl': 0, 'win_rate': 0, 'avg': 0}
    
    trades = np.array(trades)
    return {
        'count': len(trades),
        'pnl': np.sum(trades),
        'win_rate': len(trades[trades > 0]) / len(trades) * 100,
        'avg': np.mean(trades)
    }

# ========== MAIN GRID SEARCH ==========
print("=" * 70)
print("LSTM+ICT GRID SEARCH OPTIMIZATION")
print("=" * 70)

# Load all symbols
all_data = {}
for sym, csv_file in CSV_FILES.items():
    try:
        df = load_daily(csv_file)
        if len(df) >= 60:
            all_data[sym] = df
            print(f"Loaded {sym}: {len(df)} days")
    except Exception as e:
        print(f"Error loading {sym}: {e}")

print(f"\nLoaded {len(all_data)} symbols")

# Parameter grid
seq_lens = [20, 30, 40]
lstm_units = [12, 24, 48]
epochs_list = [1, 2, 3]
thresholds = [0.1, 0.2, 0.3, 0.5]

results = []
total_runs = len(seq_lens) * len(lstm_units) * len(epochs_list) * len(thresholds)
run = 0

print(f"\nRunning {total_runs} parameter combinations...")
start_time = datetime.now()

for seq_len, lstm_units, epochs, threshold in product(seq_lens, lstm_units, epochs_list, thresholds):
    run += 1
    print(f"\n[{run}/{total_runs}] seq={seq_len}, units={lstm_units}, ep={epochs}, thr={threshold}")
    
    total_pnl = 0
    total_trades = 0
    total_wins = 0
    
    for sym, df in all_data.items():
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        
        atr = calc_atr(highs, lows, closes)
        train_size = int(len(closes) * 0.8)
        result = train_and_predict_all(closes[:train_size + 20], seq_len, lstm_units, epochs)
        if result[0] is None: continue
        
        preds, acts = result
        # Get remaining for backtest
        test_closes = closes[train_size:]
        test_atr = calc_atr(highs[train_size:], lows[train_size:], closes[train_size:])
        
        for i, (direction, actual) in enumerate(zip(preds, acts)):
            if direction == 1 and actual <= actual + test_atr * threshold: continue
            if direction == -1 and actual >= actual - test_atr * threshold: continue
            
            tick = TICK_SIZE.get(sym, 0.25)
            pv = TICK_VALUE.get(sym, 5)
            contracts = CONTRACTS.get(sym, 2)
            sl_ticks = 200 / (pv * contracts)
            sl_price = sl_ticks * tick
            
            if direction == 1:
                pnl = sl_price * 3 / tick * pv * contracts
            else:
                pnl = sl_price * 3 / tick * pv * contracts
            
            total_pnl += pnl
            total_trades += 1
            if pnl > 0: total_wins += 1
    
    win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    result = {
        'seq_len': seq_len,
        'lstm_units': lstm_units,
        'epochs': epochs,
        'threshold': threshold,
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'win_rate': round(win_rate, 1),
        'avg_pnl': round(avg_pnl, 2)
    }
    results.append(result)
    print(f"  → P&L: ${total_pnl:.0f} | Trades: {total_trades} | Win%: {win_rate:.0f}% | Avg: ${avg_pnl:.0f}")

elapsed = (datetime.now() - start_time).total_seconds()
print(f"\n\nCompleted in {elapsed:.0f} seconds")

# Save all results
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('total_pnl', ascending=False)
results_df.to_csv('/home/node/.openclaw/workspace/optimization_results.csv', index=False)

print("\n" + "=" * 70)
print("TOP 10 PARAMETER COMBINATIONS")
print("=" * 70)
print(results_df.head(10).to_string(index=False))

# Best params
best = results_df.iloc[0]
print(f"\n🏆 BEST PARAMETERS:")
print(f"   seq_len: {best['seq_len']}")
print(f"   lstm_units: {best['lstm_units']}")
print(f"   epochs: {best['epochs']}")
print(f"   atr_threshold: {best['threshold']}")
print(f"   Total P&L: ${best['total_pnl']}")
print(f"   Win Rate: {best['win_rate']}%")

# Save best params
best_params = {
    'seq_len': int(best['seq_len']),
    'lstm_units': int(best['lstm_units']),
    'epochs': int(best['epochs']),
    'atr_threshold': float(best['threshold'])
}
with open('/home/node/.openclaw/workspace/best_params.json', 'w') as f:
    json.dump(best_params, f, indent=2)

print(f"\nSaved: optimization_results.csv, best_params.json")