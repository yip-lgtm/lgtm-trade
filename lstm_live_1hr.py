#!/usr/bin/env python3
"""
LSTM Live Trading Signals v6 - 1HR Timeframe
Uses pre-saved *_1hr.csv files for faster execution
"""
import os
import sys
import json
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, '/home/node/.openclaw/workspace')

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf

# ====================== Config ======================
BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY'
CHAT_ID = '8475453959'

# 1HR CSV files (pre-resampled from 15min)
CSV_FILES = {
    'MES.F': '/home/node/.openclaw/workspace/MES.F_1hr.csv',
    'MNQ.F': '/home/node/.openclaw/workspace/MNQ.F_1hr.csv',
    'M2K.F': '/home/node/.openclaw/workspace/M2K.F_1hr.csv',
    'M6E.F': '/home/node/.openclaw/workspace/M6E.F_1hr.csv',
    'M6A.F': '/home/node/.openclaw/workspace/M6A.F_1hr.csv',
    'MCL.F': '/home/node/.openclaw/workspace/MCL.F_1hr.csv',
    'MBT.F': '/home/node/.openclaw/workspace/MBT.F_1hr.csv',
    'MET.F': '/home/node/.openclaw/workspace/MET.F_1hr.csv',
    'SIL.F': '/home/node/.openclaw/workspace/SIL.F_1hr.csv',
    'MGC.F': '/home/node/.openclaw/workspace/MGC.F_1hr.csv',
}

# Symbols to SKIP (POINT_VALUE issues or no data)
SKIP_SYMBOLS = []  # User confirmed POINT_VALUE values

POINT_VALUE = {
    'MES.F': 5,     # Micro E-Mini S&P 500
    'MNQ.F': 2,     # Micro E-Mini Nasdaq-100
    'M2K.F': 5,     # Micro E-Mini Russell 2000
    'MYM.F': 0.5,   # Micro E-Mini Dow Jones
    'M6E.F': 12500, # E-Micro EUR/USD
    'M6A.F': 10000, # E-Micro AUD/USD
    'MCL.F': 100,   # Micro Crude Oil
    'MBT.F': 0.1,   # Micro Bitcoin
    'MET.F': 0.1,   # Micro Ethereum
    'MGC.F': 10,    # E-Micro Gold
    'SIL.F': 5,     # E-Micro Silver
}
# TICK_SIZE = minimum price movement (for correct SL calculation)
TICK_SIZE = {
    'MES.F': 0.25,  # S&P 500 tick
    'MNQ.F': 0.25,  # Nasdaq tick
    'M2K.F': 0.5,   # Russell tick
    'MYM.F': 1.0,   # Dow tick
    'M6E.F': 0.00005, # EUR/USD tick
    'M6A.F': 0.0001, # AUD/USD tick
    'MCL.F': 0.01,  # Crude oil tick
    'MBT.F': 1.0,   # Bitcoin tick (corrected: SL 2000 pts from entry)
    'MET.F': 0.5,   # Ethereum tick
    'MGC.F': 0.1,   # Gold tick
    'SIL.F': 0.005, # Silver tick
}
CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 2, 'M6A.F': 2, 'MCL.F': 1,
    'MBT.F': 1, 'MET.F': 1,
    'MGC.F': 2,
    'SIL.F': 1,
}
PRECISION = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 4, 'M6A.F': 4, 'MCL.F': 2,
    'MBT.F': 1, 'MET.F': 1,
    'MGC.F': 2, 'SIL.F': 3,
}

# ====================== Helpers ======================
def load_1hr_csv(fpath):
    """Load pre-saved 1hr CSV"""
    if not os.path.exists(fpath):
        return None
    df = pd.read_csv(fpath)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    return df

def calc_ema(df, fast=12, slow=26):
    """Calculate EMA12 and EMA26"""
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean().iloc[-1]
    return ema_fast, ema_slow

def check_fvg(df):
    """
    FVG detection - last 5 bars
    Returns: (has_bull_fvg, has_bear_fvg, fvg_strength)
    """
    if len(df) < 5:
        return False, False, 0
    
    fvg_bull = False
    fvg_bear = False
    fvg_strength = 0
    
    # Check last 5 bars for FVGs
    for i in range(2, len(df)):
        # Bullish FVG: bar i-1 low > bar i-2 high
        if df['low'].iloc[i-1] > df['high'].iloc[i-2]:
            fvg_bull = True
            fvg_strength += 1
        
        # Bearish FVG: bar i-1 high < bar i-2 low
        if df['high'].iloc[i-1] < df['low'].iloc[i-2]:
            fvg_bear = True
            fvg_strength += 1
    
    return fvg_bull, fvg_bear, fvg_strength

def calc_atr(high, low, close, period=14):
    """Calculate ATR"""
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)

def create_sequences(data, seq_len=20):
    X, y = [], []
    for i in range(seq_len, len(data)):
        X.append(data[i-seq_len:i])
        y.append(data[i])
    return np.array(X), np.array(y)

def train_and_predict(closes, seq_len=20):
    """Train LSTM and predict next bar"""
    if len(closes) < seq_len + 30:
        return None
    
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes.reshape(-1, 1)).flatten()
    
    X, y = create_sequences(scaled, seq_len)
    if len(X) < 20:
        return None
    
    train_size = int(len(X) * 0.9)
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

def get_hybrid_signal(pred, actual_price, atr, ema_fast, ema_slow, fvg_bull, fvg_bear, fvg_strength=0):
    """Hybrid LSTM+ICT signal with ATR confirmation + enhanced FVG"""
    threshold = atr * 0.4
    
    if pred > actual_price + threshold:
        lstm_dir = 'long'
    elif pred < actual_price - threshold:
        lstm_dir = 'short'
    else:
        return 'no_signal'
    
    trend_bull = ema_fast > ema_slow
    trend_bear = ema_fast < ema_slow
    
    # FVG strength boost: strong FVG (>1) gives extra confirmation
    fvg_boost = fvg_strength > 1
    
    if lstm_dir == 'long' and (trend_bull or fvg_bull or fvg_boost):
        return 'long'
    elif lstm_dir == 'short' and (trend_bear or fvg_bear or fvg_boost):
        return 'short'
    return 'no_signal'

def get_kz_time():
    """Return 'London' or 'NY' based on current UTC time"""
    now = datetime.utcnow()
    est = now - timedelta(hours=4)
    h, m = est.hour, est.minute
    if h >= 3 and h < 4:
        return 'London'
    if (h == 9 and m >= 30) or (h == 10 and m < 30):
        return 'NY'
    return None

# ====================== Telegram ======================
def send_telegram(text):
    try:
        import urllib.request
        url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={urllib.parse.quote(text)}&parse_mode=HTML'
        urllib.request.urlopen(url, timeout=10)
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def format_signal_msg(signals, kz):
    if not signals:
        return f"📊 LSTM 1HR {kz}: No signals"
    msg = f"📊 LSTM 1HR {kz} Signals\n━━━━━━━━━━━━━━━━\n"
    for sym, s in signals.items():
        direction = "🔴 SHORT" if s['direction'] == 'short' else "🟢 LONG"
        msg += f"{sym}: {direction} @{s['entry']}\n"
        msg += f"   SL={s['sl']} | TP1={s['tp1']} TP2={s['tp2']}\n"
        msg += f"   {s['contracts']} contract{'s' if s['contracts']>1 else ''}\n\n"
    msg += f"━━━━━━━━━━━━━━━━\nTotal: {len(signals)} signals"
    return msg

# ====================== Main ======================
def main():
    kz = get_kz_time()
    print(f"[{datetime.utcnow().isoformat()}] LSTM 1HR {kz} START")
    
    signals = {}
    
    for symbol, fpath in CSV_FILES.items():
        if symbol in SKIP_SYMBOLS:
            print(f"  {symbol}: SKIPPED (POINT_VALUE issue)")
            continue
        if not os.path.exists(fpath):
            print(f"  {symbol}: 1hr CSV not found")
            continue
        
        try:
            df = load_1hr_csv(fpath)
            if df is None or len(df) < 50:
                print(f"  {symbol}: Insufficient data")
                continue
            
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            
            atr = calc_atr(highs, lows, closes)
            ema_fast, ema_slow = calc_ema(df)
            fvg_bull, fvg_bear, fvg_strength = check_fvg(df)
            
            result = train_and_predict(closes)
            
            if result:
                direction, pred_price, actual_price = result
                signal = get_hybrid_signal(pred_price, actual_price, atr, ema_fast, ema_slow, fvg_bull, fvg_bear, fvg_strength)
                
                if signal != 'no_signal':
                    contracts = CONTRACTS.get(symbol, 2)
                    pv = POINT_VALUE.get(symbol, 5)
                    tick = TICK_SIZE.get(symbol, 0.01)
                    prec = PRECISION.get(symbol, 2)
                    
                    # SL in ticks = $200 / ($/tick) = ticks
                    # Then convert ticks to price units = ticks × tick_size
                    sl_price = (200 / (pv * contracts)) * tick
                    tp1_price = sl_price * 3
                    tp2_price = sl_price * 6
                    
                    entry = round(actual_price, prec)
                    if signal == 'short':
                        sl = round(entry + sl_price, prec)
                        tp1 = round(entry - tp1_price, prec)
                        tp2 = round(entry - tp2_price, prec)
                    else:
                        sl = round(entry - sl_price, prec)
                        tp1 = round(entry + tp1_price, prec)
                        tp2 = round(entry + tp2_price, prec)
                    
                    signals[symbol] = {
                        'direction': signal,
                        'entry': entry,
                        'sl': sl,
                        'tp1': tp1,
                        'tp2': tp2,
                        'contracts': contracts,
                        'predicted': round(pred_price, prec),
                        'actual': round(actual_price, prec),
                        'atr': round(atr, prec),
                    }
                    print(f"  {symbol}: {signal} @{entry} | SL={sl} TP1={tp1} TP2={tp2} | {contracts}c")
                else:
                    print(f"  {symbol}: no_signal (pred={pred_price:.4f}, close={actual_price:.4f})")
            else:
                print(f"  {symbol}: No result")
        except Exception as e:
            print(f"  {symbol}: ERROR {e}")
    
    # Output JSON
    output = {
        'kz': kz,
        'signals': signals,
        'time': datetime.utcnow().isoformat(),
        'total_trades': len(signals)
    }
    print(f"\nSIGNALS_JSON:{json.dumps(output)}")
    
    with open('/tmp/lstm_signals.json', 'w') as f:
        json.dump(output, f)
    
    # Send Telegram
    if signals:
        msg = format_signal_msg(signals, kz)
        send_telegram(msg)
    
    print(f"[{datetime.utcnow().isoformat()}] LSTM 1HR {kz} DONE - {len(signals)} signals")

if __name__ == '__main__':
    main()