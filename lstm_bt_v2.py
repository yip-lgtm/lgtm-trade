#!/usr/bin/env python3
"""LSTM Backtest - Train once per symbol, batch predict"""
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
TICK_VALUE = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'M6E.F':12.5,'M6A.F':1,'MCL.F':100,'MBT.F':100,'MET.F':100,'SIL.F':5,'MGC.F':10}
TICK_SIZE = {'MES.F':0.25,'MNQ.F':0.25,'M2K.F':0.25,'M6E.F':0.0001,'M6A.F':0.0001,'MCL.F':0.01,'MBT.F':0.01,'MET.F':0.01,'SIL.F':0.005,'MGC.F':0.1}
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

def create_sequences(data, seq_len=40):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i-seq_len:i])
        y.append(data[i])
    return np.array(X), np.array(y)

def train_and_predict_all(closes, seq_len=40):
    """Train ONCE on first 80%, predict remaining"""
    if len(closes) < seq_len + 20: return None, None, None
    
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
    
    # Predict all from train_size onwards
    preds, acts = [], []
    for i in range(train_size, len(X)):
        # X[i] is already scaled seq, y[i] is scaled target
        p = model.predict(X[i:i+1], verbose=0)[0, 0]
        p = np.clip(p, scaled.min(), scaled.max())
        pred_price = scaler.inverse_transform([[p]])[0, 0]
        actual_price = scaler.inverse_transform([[y[i]]])[0, 0]
        direction = 'long' if pred_price > actual_price else 'short'
        preds.append((direction, pred_price, actual_price))
        acts.append(actual_price)
    
    return preds, acts, scaler

def run_backtest(sym, csv_file):
    print(f"  {sym}...", end=' ', flush=True)
    df = load_daily(csv_file)
    if len(df) < 60:
        print(f"數據不足({len(df)}天)")
        return []
    
    closes = df['close'].values
    atr = np.std(closes[-30:]) if len(closes) > 30 else np.std(closes)
    result = train_and_predict_all(closes)
    if result[0] is None:
        print("訓練失敗")
        return []
    
    preds, actuals, _ = result
    trades = []
    for i, (direction, pred_price, actual_price) in enumerate(preds):
        threshold = atr * 0.3
        if direction == 'long' and pred_price <= actual_price + threshold: continue
        if direction == 'short' and pred_price >= actual_price - threshold: continue
        
        tick = TICK_SIZE.get(sym, 0.25)
        pv = TICK_VALUE.get(sym, 5)
        contracts = CONTRACTS.get(sym, 2)
        sl_ticks = 200 / (pv * contracts)
        sl_price = sl_ticks * tick
        
        entry = actual_price
        if direction == 'short':
            sl = entry + sl_price
            tp1 = entry - sl_price * 3
            tp2 = entry - sl_price * 6
        else:
            sl = entry - sl_price
            tp1 = entry + sl_price * 3
            tp2 = entry + sl_price * 6
        
        trade_idx = int(len(closes) * 0.8) + i
        trades.append({
            'symbol': sym, 'direction': direction, 'entry': round(entry, 4),
            'sl': round(sl, 4), 'tp1': round(tp1, 4), 'tp2': round(tp2, 4),
            'pred': round(pred_price, 4), 'actual': round(actual_price, 4),
            'date': df.index[trade_idx].strftime('%Y-%m-%d')
        })
    
    print(f"{len(trades)}筆")
    return trades

# Main
print("=" * 60)
print("LSTM Backtest (Train once, seq=40, ep=2)")
print("=" * 60)
all_trades = []
for sym, csv_file in CSV_FILES.items():
    trades = run_backtest(sym, csv_file)
    all_trades.extend(trades)

if all_trades:
    pd.DataFrame(all_trades).to_csv('/home/node/.openclaw/workspace/backtest_results.csv', index=False)
    longs = len([t for t in all_trades if t['direction']=='long'])
    shorts = len([t for t in all_trades if t['direction']=='short'])
    print(f"\n共 {len(all_trades)} 筆: Long={longs} Short={shorts}")
    print("已保存: /home/node/.openclaw/workspace/backtest_results.csv")
else:
    print("\n無交易")