#!/usr/bin/env python3
"""
LSTM Live Trading Signals v6 - Corrected $200 SL Version
"""
import os
import sys
import json
import urllib.parse
from datetime import datetime, timedelta

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

POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MYM.F': 0.5,
    'M6E.F': 12500, 'M6A.F': 10000, 'MCL.F': 100,
    'MBT.F': 0.1, 'MET.F': 0.1,
    'MGC.F': 10, 'SIL.F': 5
}

CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 2, 'M6A.F': 2, 'MCL.F': 1,
    'MBT.F': 1, 'MET.F': 1,
    'MGC.F': 2, 'SIL.F': 1
}

PRECISION = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 4, 'M6A.F': 4, 'MCL.F': 2,
    'MBT.F': 1, 'MET.F': 1,
    'MGC.F': 2, 'SIL.F': 3
}

# ====================== Helpers ======================
def load_1hr_csv(fpath):
    if not os.path.exists(fpath): return None
    df = pd.read_csv(fpath)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    return df

def calc_ema(df, fast=12, slow=26):
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean().iloc[-1]
    return ema_fast, ema_slow

def check_fvg(df):
    if len(df) < 5: return False, False, 0
    fvg_bull = False
    fvg_bear = False
    fvg_strength = 0
    for i in range(2, len(df)):
        if df['low'].iloc[i-1] > df['high'].iloc[i-2]:
            fvg_bull = True
            fvg_strength += 1
        if df['high'].iloc[i-1] < df['low'].iloc[i-2]:
            fvg_bear = True
            fvg_strength += 1
    return fvg_bull, fvg_bear, fvg_strength

def calc_atr(high, low, close, period=14):
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
    direction = 'long' if pred_price > actual_price else 'short'
    return direction, pred_price, actual_price

def get_kz_time():
    now = datetime.utcnow()
    est = now - timedelta(hours=4)
    h, m = est.hour, est.minute
    if h >= 3 and h < 4: return 'London'
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return 'NY'
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
    if not signals: return f"📊 LSTM 1HR {kz}: No signals"
    msg = f"📊 LSTM 1HR {kz} Signals\n━━━━━━━━━━━━━━━━\n"
    for sym, s in signals.items():
        direction = "🔴 SHORT" if s['direction'] == 'short' else "🟢 LONG"
        msg += f"{sym}: {direction} @{s['entry']}\n"
        msg += f" SL={s['sl']} | TP1={s['tp1']} TP2={s['tp2']}\n"
        msg += f" {s['contracts']} contract{'s' if s['contracts']>1 else ''}\n\n"
    msg += f"━━━━━━━━━━━━━━━━\nTotal: {len(signals)} signals"
    return msg

# ====================== Main ======================
def main():
    kz = get_kz_time()
    print(f"[{datetime.utcnow().isoformat()}] LSTM 1HR {kz} START")
    signals = {}

    for symbol, fpath in CSV_FILES.items():
        if not os.path.exists(fpath): continue
        try:
            df = load_1hr_csv(fpath)
            if df is None or len(df) < 50: continue
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            atr = calc_atr(highs, lows, closes)
            ema_fast, ema_slow = calc_ema(df)
            fvg_bull, fvg_bear, fvg_strength = check_fvg(df)

            result = train_and_predict(closes)
            if result:
                direction, pred_price, actual_price = result
                # Hybrid logic
                threshold = atr * 0.4
                lstm_dir = 'long' if pred_price > actual_price + threshold else 'short' if pred_price < actual_price - threshold else 'no_signal'
                trend_bull = ema_fast > ema_slow
                if lstm_dir == 'long' and (trend_bull or fvg_bull):
                    signal = 'long'
                elif lstm_dir == 'short' and (not trend_bull or fvg_bear):
                    signal = 'short'
                else:
                    signal = 'no_signal'

                if signal != 'no_signal':
                    contracts = CONTRACTS.get(symbol, 2)
                    pv = POINT_VALUE.get(symbol, 5)
                    prec = PRECISION.get(symbol, 2)
                    sl_distance = 200 / (pv * contracts)  # 關鍵修正
                    entry = round(actual_price, prec)
                    if signal == 'short':
                        sl = round(entry + sl_distance, prec)
                        tp1 = round(entry - sl_distance * 3, prec)
                        tp2 = round(entry - sl_distance * 6, prec)
                    else:
                        sl = round(entry - sl_distance, prec)
                        tp1 = round(entry + sl_distance * 3, prec)
                        tp2 = round(entry + sl_distance * 6, prec)

                    signals[symbol] = {
                        'direction': signal, 'entry': entry, 'sl': sl,
                        'tp1': tp1, 'tp2': tp2, 'contracts': contracts,
                        'predicted': round(pred_price, prec),
                        'actual': round(actual_price, prec),
                    }
                    print(f"  {symbol}: {signal.upper()} @{entry} | SL={sl} TP1={tp1} TP2={tp2} | {contracts}c")
                else:
                    print(f"  {symbol}: no_signal (pred={pred_price:.4f}, close={actual_price:.4f})")
        except Exception as e:
            print(f"  {symbol}: ERROR {e}")

    output = {'kz': kz, 'signals': signals, 'time': datetime.utcnow().isoformat(), 'total_trades': len(signals)}
    print(f"\nSIGNALS_JSON:{json.dumps(output)}")
    with open('/tmp/lstm_signals.json', 'w') as f: json.dump(output, f)

    if signals:
        msg = format_signal_msg(signals, kz)
        send_telegram(msg)
    print(f"[{datetime.utcnow().isoformat()}] LSTM 1HR {kz} DONE - {len(signals)} signals")

if __name__ == '__main__':
    main()