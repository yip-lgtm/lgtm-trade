#!/usr/bin/env python3
"""Fast LSTM backtest - runs one symbol at a time to avoid memory issues"""
import os, sys, warnings, time
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

import pandas as pd, numpy as np
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM
import ta
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from datetime import timedelta

POINT_VALUE = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'MYM.F':0.5,'M6E.F':12500,'M6A.F':10000,'MCL.F':100}
CONTRACTS = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'MYM.F':2,'M6E.F':2,'M6A.F':2,'MCL.F':1}

CSV_FILES = {
    'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv',
    'MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv'
}

def is_kill_zone(dt):
    dt_est = dt - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    return (3 <= h < 4) or (h == 9 and m >= 30) or (h == 10 and m < 30)

def compute_features(df):
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
    return df

def run_backtest(sym):
    print(f"  回測 {sym}...", end='', flush=True)
    t0 = time.time()
    df = pd.read_csv(CSV_FILES[sym], parse_dates=['datetime'])
    df.set_index('datetime', inplace=True); df.sort_index(inplace=True)
    df = compute_features(df.copy()); df.dropna(inplace=True)
    if len(df) < 120:
        print(f" 數據不足 ({len(df)} rows)")
        return []
    train_size = int(len(df) * 0.80)
    pv = POINT_VALUE[sym]; contracts = CONTRACTS[sym]
    scaler = MinMaxScaler(feature_range=(0,1))
    scaled_all = scaler.fit_transform(df.filter(['close']).values)
    train = scaled_all[:train_size]
    x_tr, y_tr = [], []
    for i in range(60, len(train)):
        x_tr.append(train[i-60:i,0]); y_tr.append(train[i,0])
    x_tr, y_tr = np.array(x_tr), np.array(y_tr)
    x_tr = x_tr.reshape(x_tr.shape[0], x_tr.shape[1], 1)
    model = Sequential([LSTM(128,return_sequences=True,input_shape=(60,1)),LSTM(64,return_sequences=False),Dense(25),Dense(1)])
    model.compile(optimizer='adam', loss='mse')
    model.fit(x_tr, y_tr, batch_size=1, epochs=1, verbose=0)
    results = []; in_trade = False
    sl_ticks, tp1_ticks, tp2_ticks = 10, 10, 20
    for i in range(train_size, len(df)):
        bar = df.iloc[i]
        last_60 = scaled_all[i-60:i].reshape(1,60,1)
        pred = scaler.inverse_transform(model.predict(last_60, verbose=0))[0][0]
        ml_sig = 1 if pred > bar['close'] + bar['ATR']*0.3 else (-1 if pred < bar['close'] - bar['ATR']*0.3 else 0)
        trend_bull = 1 if bar['EMA12'] > bar['EMA26'] else 0
        hybrid = 1 if (ml_sig==1 and trend_bull==1 and (bar['FVG_Bullish']==1 or bar['In_OTE_Bull']==1)) else (-1 if (ml_sig==-1 and trend_bull==0 and (bar['FVG_Bearish']==1 or bar['In_OTE_Bear']==1)) else 0)
        in_kz = is_kill_zone(bar.name)
        if not in_trade:
            if in_kz and hybrid != 0:
                in_trade = True
                entry_price, entry_bar, direction, entry_idx = bar['close'], bar.name, hybrid, i
        else:
            pnl_t = (bar['close'] - entry_price) * (1 if direction==1 else -1)
            pnl_d = pnl_t * pv * contracts
            if pnl_t <= -sl_ticks or pnl_t >= tp1_ticks or pnl_t >= tp2_ticks:
                exit_r = 'SL' if pnl_t <= -sl_ticks else ('TP1' if pnl_t >= tp1_ticks else 'TP2')
                results.append({'symbol':sym,'entry_time':entry_bar,'exit_time':bar.name,'direction':direction,'entry_price':entry_price,'exit_price':bar['close'],'pnl_ticks':round(pnl_t,4),'pnl_dollar':round(pnl_d,2),'contracts':contracts,'exit_reason':exit_r,'in_kill_zone':True})
                in_trade = False
    if in_trade:
        bar = df.iloc[-1]
        pnl_t = (bar['close'] - entry_price) * (1 if direction==1 else -1)
        results.append({'symbol':sym,'entry_time':entry_bar,'exit_time':bar.name,'direction':direction,'entry_price':entry_price,'exit_price':bar['close'],'pnl_ticks':round(pnl_t,4),'pnl_dollar':round(pnl_t*pv*contracts,2),'contracts':contracts,'exit_reason':'END','in_kill_zone':True})
    print(f" {len(results)} 筆交易 ({time.time()-t0:.1f}s)")
    return results

print("=" * 80)
print("🚀 LSTM 60天回測")
print("London KZ: 03:00-04:00 EST | NY KZ: 09:30-10:30 EST")
print("SL: 10t | TP1: 10t | TP2: 20t | MCL: 1 contract")
print("=" * 80)
all_trades = []
for sym in CSV_FILES:
    trades = run_backtest(sym)
    all_trades.extend(trades)

if all_trades:
    results_df = pd.DataFrame(all_trades)
    results_df.to_csv('backtest_results.csv', index=False)
    print("\n" + "=" * 80)
    print("📊 回測結果")
    print("=" * 80)
    for sym in CSV_FILES:
        s = results_df[results_df['symbol']==sym]
        if len(s) == 0: continue
        total = s['pnl_dollar'].sum()
        wins = len(s[s['pnl_dollar']>0])
        print(f"\n{sym}: {len(s)}筆 | 勝{wins} 輸{len(s)-wins} | 淨 ${total:.2f}")
        grp = s.groupby('exit_reason')['pnl_dollar'].agg(['count','sum'])
        for _, row in grp.iterrows():
            print(f"  {row['count']}筆 {row.name} = ${row['sum']:.2f}")
    total_pnl = results_df['pnl_dollar'].sum()
    total_trades = len(results_df)
    wr = len(results_df[results_df['pnl_dollar']>0]) / total_trades * 100
    print(f"\n📈 整體: {total_trades}筆 | 勝率 {wr:.1f}% | 總盈虧 ${total_pnl:.2f}")
    print(f"💾 儲存: backtest_results.csv")
else:
    print("無交易記錄")