#!/usr/bin/env python3
"""
LSTM Live Trading Signals v5 - Hybrid LSTM+ICT with ATR Confirmation
Run via cron or manually for live KZ signals
"""
import os
import sys
import json
import urllib.parse
from datetime import datetime, timedelta

# Add workspace to path
sys.path.insert(0, '/home/node/.openclaw/workspace')

# Suppress TF warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf

# ====================== Config ======================
BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY'
CHAT_ID = '8475453959'

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

# POINT_VALUE = $/point (dollar value per price point)
# SL Distance (price units) = 200 / (POINT_VALUE × contracts)
POINT_VALUE = {
    'MES.F': 5,
    'MNQ.F': 2,
    'M2K.F': 5,
    'M6E.F': 12500,   # $12500/point → SL=0.008 price units
    'M6A.F': 10000,    # verified by user: 10000*2=20000 → SL=0.01
    'MCL.F': 100,
    'MBT.F': 0.1,      # $0.1/point → SL=2000 price units
    'MET.F': 0.1,      # $0.1/point → SL=2000 price units
    'SIL.F': 1000,  # $1000/point → SL=0.20 price, 40 ticks = $200 risk
    'MGC.F': 10,  # $10/point → 2 contracts = $20/point → SL=10pts
}
CONTRACTS = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'M6E.F':2,'M6A.F':2,'MCL.F':1,'MBT.F':1,'MET.F':1,'SIL.F':1,'MGC.F':2}

PRECISION = {
    'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'M6E.F':5, 'M6A.F':4,
    'MCL.F':2, 'MBT.F':2, 'MET.F':2, 'SIL.F':4, 'MGC.F':2
}

# ====================== Helpers ======================
def parseCSV(fname):
    if not os.path.exists(fname): return None
    df = pd.read_csv(fname)
    df = df.dropna(subset=['close'])
    return df

def calc_ema(df, fast=12, slow=26):
    """Calculate EMA12 and EMA26 for trend confirmation"""
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean().iloc[-1]
    return ema_fast, ema_slow

def check_fvg(df):
    """Check for Fair Value Gap (last 3 bars)"""
    if len(df) < 3:
        return False, False
    low1 = df['low'].iloc[-2]
    high2 = df['high'].iloc[-2]
    low2 = df['low'].iloc[-3]
    high1 = df['high'].iloc[-2]
    # Bullish FVG: low of bar2 > high of bar3
    fvg_bull = low1 > df['high'].iloc[-3]
    # Bearish FVG: high of bar2 < low of bar3
    fvg_bear = high1 < df['low'].iloc[-3]
    return fvg_bull, fvg_bear

def get_kz_time():
    """Return 'London' or 'NY' based on current UTC time"""
    now = datetime.utcnow()
    est = now - timedelta(hours=4)
    h, m = est.hour, est.minute
    if h >= 3 and h < 4: return 'London'
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return 'NY'
    return None

def calc_atr(df, period=14):
    """Calculate Average True Range"""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
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
    """Train LSTM and predict"""
    if len(closes) < seq_len + 30: return None
    
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled = scaler.fit_transform(closes.reshape(-1, 1)).flatten()
    
    X, y = create_sequences(scaled, seq_len)
    if len(X) < 20: return None
    
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
    
    # Correct direction logic
    direction = 'long' if pred_price > actual_price else 'short'
    
    return direction, pred_price, actual_price

def get_hybrid_signal(pred, actual_price, atr, ema_fast=None, ema_slow=None, fvg_bull=None, fvg_bear=None):
    """Hybrid LSTM+ICT signal with ATR confirmation + ICT filters
    
    Long if: pred > actual + ATR*threshold AND (ema_bull OR fvg_bull)
    Short if: pred < actual - ATR*threshold AND (ema_bear OR fvg_bear)
    """
    threshold = atr * 0.4  # Raised from 0.3 to 0.4 for stricter signals
    
    # LSTM direction
    if pred > actual_price + threshold:
        lstm_dir = 'long'
    elif pred < actual_price - threshold:
        lstm_dir = 'short'
    else:
        return 'no_signal'
    
    # ICT confirmation: trend must confirm LSTM direction
    # If no ICT data provided, rely on LSTM alone
    if ema_fast is not None and ema_slow is not None:
        # EMA confirm: fast > slow = bull, fast < slow = bear
        trend_bull = ema_fast > ema_slow
        trend_bear = ema_fast < ema_slow
    else:
        trend_bull = True
        trend_bear = True
    
    # ICT FVG confirm (if provided)
    if fvg_bull is not None and fvg_bear is not None:
        has_fvg_bull = fvg_bull
        has_fvg_bear = fvg_bear
    else:
        has_fvg_bull = True
        has_fvg_bear = True
    
    # Final confirmation
    if lstm_dir == 'long' and (trend_bull or has_fvg_bull):
        return 'long'
    elif lstm_dir == 'short' and (trend_bear or has_fvg_bear):
        return 'short'
    else:
        return 'no_signal'  # ICT doesn't confirm

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
        return f"LSTM {kz}: No signals"
    msg = f"📊 LSTM {kz} Signals\n━━━━━━━━━━━━━━━━\n"
    for sym, s in signals.items():
        direction = "🔴 SHORT" if s['direction'] == 'short' else "🟢 LONG"
        msg += f"{sym}: {direction} @{s['entry']}\n"
        msg += f"   SL={s['sl']} | TP1={s['tp1']} TP2={s['tp2']}\n"
        msg += f"   {s['contracts']} contract{'s' if s['contracts']>1 else ''}\n\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"Total: {len(signals)} signals"
    return msg

# ====================== Main ======================
def main():
    kz = get_kz_time()
    print(f"[{datetime.utcnow().isoformat()}] LSTM {kz} START")
    
    signals = {}
    trades = []  # For journal
    
    for symbol, fpath in CSV_FILES.items():
        if not os.path.exists(fpath):
            print(f"  {symbol}: CSV not found")
            continue
        
        try:
            df = parseCSV(fpath)
            if df is None or len(df) < 50:
                print(f"  {symbol}: Insufficient data")
                continue
            
            closes = df['close'].values
            atr = calc_atr(df)
            ema_fast, ema_slow = calc_ema(df)
            fvg_bull, fvg_bear = check_fvg(df)
            result = train_and_predict(closes)
            
            if result:
                direction, pred_price, actual_price = result
                signal = get_hybrid_signal(pred_price, actual_price, atr, ema_fast, ema_slow, fvg_bull, fvg_bear)
                
                if signal != 'no_signal':
                    contracts = CONTRACTS.get(symbol, 2)
                    pv = POINT_VALUE.get(symbol, 5)
                    prec = PRECISION.get(symbol, 2)
                    
                    # SL Distance (price units) = 200 / (POINT_VALUE × contracts)
                    sl_price = 200 / (pv * contracts)
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
                    trades.append({
                        'symbol': symbol,
                        'direction': signal,
                        'entry': entry,
                        'sl': sl,
                        'tp1': tp1,
                        'tp2': tp2,
                        'contracts': contracts,
                        'atr': round(atr, 4)
                    })
                    print(f"  {symbol}: {signal} @{entry} | SL={sl} TP1={tp1} TP2={tp2} | {contracts}c")
                else:
                    print(f"  {symbol}: no_signal (pred={pred_price:.4f}, close={actual_price:.4f})")
            else:
                print(f"  {symbol}: No result")
        except Exception as e:
            print(f"  {symbol}: ERROR {e}")
    
    # Output
    output = {
        'kz': kz,
        'signals': signals,
        'time': datetime.utcnow().isoformat(),
        'total_trades': len(trades)
    }
    print(f"\nSIGNALS_JSON:{json.dumps(output)}")
    
    with open('/tmp/lstm_signals.json', 'w') as f:
        json.dump(output, f)
    
    # Send Telegram notification
    if signals:
        msg = format_signal_msg(signals, kz)
        send_telegram(msg)
    
    print(f"[{datetime.utcnow().isoformat()}] LSTM {kz} DONE - {len(signals)} signals")

if __name__ == '__main__':
    main()
