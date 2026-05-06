#!/usr/bin/env python3
import os, sys, warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

print("Starting...", flush=True)
sys.stdout.flush()

import pandas as pd
print("pandas imported", flush=True)
sys.stdout.flush()

from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
print("ta imported", flush=True)
sys.stdout.flush()

from sklearn.preprocessing import MinMaxScaler
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM
print("all imports done, TF:", tf.__version__, flush=True)
sys.stdout.flush()

CSV_FILES = {
    'MES.F': 'MES.F.csv', 'MNQ.F': 'MNQ.F.csv', 'M2K.F': 'M2K.F.csv',
    'MYM.F': 'MYM.F.csv', 'M6E.F': 'M6E.F.csv', 'M6A.F': 'M6A.F.csv',
    'MCL.F': 'MCL.F.csv'
}
POINT_VALUE = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'MYM.F':0.5,'M6E.F':12500,'M6A.F':10000,'MCL.F':100}
PRECISION = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'MYM.F':2,'M6E.F':4,'M6A.F':4,'MCL.F':2}

def is_kill_zone(dt_utc):
    from datetime import timedelta
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4: return True
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return True
    return False

print("Starting training...", flush=True)
sys.stdout.flush()

for sym, csv_file in CSV_FILES.items():
    print(f"  Training {sym}...", flush=True)
    sys.stdout.flush()
    try:
        df = pd.read_csv(csv_file, parse_dates=['datetime'])
        df.set_index('datetime', inplace=True); df.sort_index(inplace=True)
        print(f"    Loaded {len(df)} rows", flush=True)
        sys.stdout.flush()
        
        df['RSI'] = RSIIndicator(df['close'], window=14).rsi()
        df['EMA12'] = EMAIndicator(df['close'], window=12).ema_indicator()
        df['EMA26'] = EMAIndicator(df['close'], window=26).ema_indicator()
        macd = MACD(df['close']); df['MACD'] = macd.macd; df['MACD_signal'] = macd.macd_signal
        bb = BollingerBands(df['close'])
        df['BB_upper'] = bb.bollinger_hband(); df['BB_middle'] = bb.bollinger_mavg(); df['BB_lower'] = bb.bollinger_lband()
        df['ATR'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
        df['Volume_SMA'] = SMAIndicator(df['volume'], window=20).sma_indicator()
        df['FVG_Bullish'] = (df['low'].shift(1) > df['high'].shift(2)).astype(int)
        df['FVG_Bearish'] = (df['high'].shift(1) < df['low'].shift(2)).astype(int)
        df['Swing_High'] = df['high'].rolling(20).max().shift(1)
        df['Swing_Low'] = df['low'].rolling(20).min().shift(1)
        df['Fib_Range'] = df['Swing_High'] - df['Swing_Low']
        df['OTE_079_Bull'] = df['Swing_Low'] + df['Fib_Range'] * 0.79
        df['OTE_079_Bear'] = df['Swing_High'] - df['Fib_Range'] * 0.79
        df['In_OTE_Bull'] = ((df['close'] >= df['Swing_Low'] + df['Fib_Range'] * 0.62) & (df['close'] <= df['OTE_079_Bull'])).astype(int)
        df['In_OTE_Bear'] = ((df['close'] <= df['Swing_High'] - df['Fib_Range'] * 0.62) & (df['close'] >= df['OTE_079_Bear'])).astype(int)
        df.dropna(inplace=True)
        print(f"    Features done, {len(df)} rows", flush=True)
        sys.stdout.flush()
        
        data = df.filter(['close']).values
        scaler = MinMaxScaler(feature_range=(0, 1))
        scaled_data = scaler.fit_transform(data)
        train_size = int(len(scaled_data) * 0.95)
        train_data = scaled_data[:train_size]
        x_train, y_train = [], []
        for i in range(60, len(train_data)):
            x_train.append(train_data[i - 60:i, 0])
            y_train.append(train_data[i, 0])
        x_train, y_train = np.array(x_train), np.array(y_train)
        x_train = np.reshape(x_train, (x_train.shape[0], x_train.shape[1], 1))
        print(f"    Training LSTM ({x_train.shape[0]} samples)...", flush=True)
        sys.stdout.flush()
        
        model = Sequential()
        model.add(LSTM(128, return_sequences=True, input_shape=(x_train.shape[1], 1)))
        model.add(LSTM(64, return_sequences=False))
        model.add(Dense(25))
        model.add(Dense(1))
        model.compile(optimizer='adam', loss='mean_squared_error')
        model.fit(x_train, y_train, batch_size=1, epochs=3, verbose=0)
        print(f"    ✅ {sym} done", flush=True)
        sys.stdout.flush()
    except Exception as e:
        print(f"    ❌ {sym} error: {e}", flush=True)
        import traceback; traceback.print_exc(file=sys.stdout); sys.stdout.flush()

print("All done!", flush=True)