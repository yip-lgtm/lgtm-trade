#!/usr/bin/env python3
"""
LSTM Backtest - 60 days historical
Walk-forward: train once per symbol, predict each bar
Only trade in Kill Zone when hybrid signal fires.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

import ta
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

from sklearn.preprocessing import MinMaxScaler
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM

POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MYM.F': 0.5,
    'M6E.F': 12500, 'M6A.F': 10000, 'MCL.F': 100
}
PRECISION = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 4, 'M6A.F': 4, 'MCL.F': 2
}
CSV_FILES = {
    'MES.F': 'MES.F.csv', 'MNQ.F': 'MNQ.F.csv', 'M2K.F': 'M2K.F.csv',
    'MYM.F': 'MYM.F.csv', 'M6E.F': 'M6E.F.csv', 'M6A.F': 'M6A.F.csv',
    'MCL.F': 'MCL.F.csv'
}
RESULTS_FILE = 'backtest_results.csv'

def is_kill_zone(dt_utc):
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4:
        return True
    if (h == 9 and m >= 30) or (h == 10 and m < 30):
        return True
    return False

def compute_features(df):
    df['RSI'] = RSIIndicator(df['close'], window=14).rsi()
    df['EMA12'] = EMAIndicator(df['close'], window=12).ema_indicator()
    df['EMA26'] = EMAIndicator(df['close'], window=26).ema_indicator()
    macd = MACD(df['close'])
    df['MACD'] = macd.macd
    df['MACD_signal'] = macd.macd_signal
    bb = BollingerBands(df['close'])
    df['BB_upper'] = bb.bollinger_hband()
    df['BB_middle'] = bb.bollinger_mavg()
    df['BB_lower'] = bb.bollinger_lband()
    df['ATR'] = AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    df['Volume_SMA'] = SMAIndicator(df['volume'], window=20).sma_indicator()
    df['FVG_Bullish'] = (df['low'].shift(1) > df['high'].shift(2)).astype(int)
    df['FVG_Bearish'] = (df['high'].shift(1) < df['low'].shift(2)).astype(int)
    df['Swing_High'] = df['high'].rolling(20).max().shift(1)
    df['Swing_Low'] = df['low'].rolling(20).min().shift(1)
    df['Fib_Range'] = df['Swing_High'] - df['Swing_Low']
    df['OTE_079_Bull'] = df['Swing_Low'] + df['Fib_Range'] * 0.79
    df['OTE_079_Bear'] = df['Swing_High'] - df['Fib_Range'] * 0.79
    df['In_OTE_Bull'] = ((df['close'] >= df['Swing_Low'] + df['Fib_Range'] * 0.62) &
                          (df['close'] <= df['OTE_079_Bull'])).astype(int)
    df['In_OTE_Bear'] = ((df['close'] <= df['Swing_High'] - df['Fib_Range'] * 0.62) &
                          (df['close'] >= df['OTE_079_Bear'])).astype(int)
    return df

def train_model(scaled_data, train_size):
    """Train LSTM once on training portion"""
    train = scaled_data[:train_size]
    x_train, y_train = [], []
    for i in range(60, len(train)):
        x_train.append(train[i-60:i, 0])
        y_train.append(train[i, 0])
    x_train, y_train = np.array(x_train), np.array(y_train)
    x_train = np.reshape(x_train, (x_train.shape[0], x_train.shape[1], 1))

    model = Sequential()
    model.add(LSTM(128, return_sequences=True, input_shape=(x_train.shape[1], 1)))
    model.add(LSTM(64, return_sequences=False))
    model.add(Dense(25))
    model.add(Dense(1))
    model.compile(optimizer='adam', loss='mean_squared_error')
    model.fit(x_train, y_train, batch_size=1, epochs=3, verbose=0)
    return model

def predict(model, last_60, scaler):
    last_60 = np.reshape(last_60, (1, 60, 1))
    pred_scaled = model.predict(last_60, verbose=0)
    return scaler.inverse_transform(pred_scaled)[0][0]

def run_backtest(sym, csv_file):
    print(f"  回測 {sym}...")
    df = pd.read_csv(csv_file)
    df.columns = [c.lower() for c in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    df.sort_index(inplace=True)
    df.dropna(inplace=True)
    
    if len(df) < 60:
        print(f"  {sym}: 數據不足 ({len(df)} rows),跳過")
        return []

    pv = POINT_VALUE[sym]
    contracts = 1 if sym == 'MCL.F' else 2

    # Prepare scaled data
    data = df.filter(['close']).values
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_all = scaler.fit_transform(data)

    train_size = int(len(scaled_all) * 0.80)  # use 80% for training
    model = train_model(scaled_all, train_size)

    results = []
    in_trade = False
    entry_price = 0
    entry_bar = None
    direction = 0
    sl_ticks = 10
    tp1_ticks = 10
    tp2_ticks = 20

    # Walk forward through remaining 20%
    for i in range(train_size, len(df)):
        bar = df.iloc[i]
        last_60 = scaled_all[i-60:i]

        try:
            pred = predict(model, last_60, scaler)
        except:
            pred = bar['close']

        ml_signal = 1 if (pred > bar['close'] + bar['ATR'] * 0.3) else (-1 if pred < bar['close'] - bar['ATR'] * 0.3 else 0)
        trend_bull = 1 if bar['EMA12'] > bar['EMA26'] else 0

        hybrid = 0
        if ml_signal == 1 and trend_bull == 1 and (bar['FVG_Bullish'] == 1 or bar['In_OTE_Bull'] == 1):
            hybrid = 1
        elif ml_signal == -1 and trend_bull == 0 and (bar['FVG_Bearish'] == 1 or bar['In_OTE_Bear'] == 1):
            hybrid = -1

        in_kill = is_kill_zone(bar.name)

        if not in_trade:
            if in_kill and hybrid != 0:
                in_trade = True
                entry_price = bar['close']
                entry_bar = bar.name
                direction = hybrid
                print(f"  [{sym}] {'LONG' if direction == 1 else 'SHORT'} {entry_price} @ {bar.name.strftime('%m-%d %H:%M')}")
        else:
            pnl_ticks = (bar['close'] - entry_price) * (1 if direction == 1 else -1)
            pnl_dollar = pnl_ticks * pv * contracts
            hit_sl = pnl_ticks <= -sl_ticks
            hit_tp1 = pnl_ticks >= tp1_ticks
            hit_tp2 = pnl_ticks >= tp2_ticks

            if hit_sl or hit_tp1 or hit_tp2:
                exit_reason = 'SL' if hit_sl else ('TP1' if hit_tp1 else 'TP2')
                results.append({
                    'symbol': sym, 'entry_time': entry_bar, 'exit_time': bar.name,
                    'direction': direction, 'entry_price': entry_price, 'exit_price': bar['close'],
                    'pnl_ticks': round(pnl_ticks, 4), 'pnl_dollar': round(pnl_dollar, 2),
                    'contracts': contracts, 'exit_reason': exit_reason, 'in_kill_zone': True
                })
                in_trade = False

    if in_trade:
        bar = df.iloc[-1]
        pnl_ticks = (bar['close'] - entry_price) * (1 if direction == 1 else -1)
        pnl_dollar = pnl_ticks * pv * contracts
        results.append({
            'symbol': sym, 'entry_time': entry_bar, 'exit_time': bar.name,
            'direction': direction, 'entry_price': entry_price, 'exit_price': bar['close'],
            'pnl_ticks': round(pnl_ticks, 4), 'pnl_dollar': round(pnl_dollar, 2),
            'contracts': contracts, 'exit_reason': 'END', 'in_kill_zone': True
        })

    print(f"  {sym}: {len(results)} 筆交易")
    return results

# 主程式
print("=" * 80)
print("🚀 LSTM 60天回測(Train once, Walk-Forward predict)")
print("London KZ: 03:00-04:00 EST | NY KZ: 09:30-10:30 EST")
print("SL: 10t | TP1: 10t | TP2: 20t | MCL: 1 contract")
print("=" * 80)

all_trades = []
for sym, csv_file in CSV_FILES.items():
    trades = run_backtest(sym, csv_file)
    all_trades.extend(trades)

if all_trades:
    results_df = pd.DataFrame(all_trades)
    results_df.to_csv(RESULTS_FILE, index=False)

    print("\n" + "=" * 80)
    print("📊 回測結果")
    print("=" * 80)

    for sym in CSV_FILES:
        s = results_df[results_df['symbol'] == sym]
        if len(s) == 0:
            continue
        total = s['pnl_dollar'].sum()
        wins = len(s[s['pnl_dollar'] > 0])
        print(f"\n{sym}: {len(s)}筆 | 勝{wins} 輸{len(s)-wins} | 淨 ${total:.2f}")
        by_exit = s.groupby('exit_reason')['pnl_dollar'].agg(['count','sum'])
        print(f"  {by_exit.to_string()}")

    total_pnl = results_df['pnl_dollar'].sum()
    total_trades = len(results_df)
    win_rate = len(results_df[results_df['pnl_dollar'] > 0]) / total_trades * 100
    print(f"\n📈 整體: {total_trades}筆 | 勝率 {win_rate:.1f}% | 總盈虧 ${total_pnl:.2f}")
    print(f"💾 儲存: {RESULTS_FILE}")
else:
    print("無交易記錄")