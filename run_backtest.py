#!/usr/bin/env python3
import os, sys, warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np, time
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM
import ta
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from datetime import timedelta

PV = {'MES.F':5,'MNQ.F':2,'M2K.F':5,'MYM.F':0.5,'M6E.F':12500,'M6A.F':10000,'MCL.F':100}
CON = {'MES.F':2,'MNQ.F':2,'M2K.F':2,'MYM.F':2,'M6E.F':2,'M6A.F':2,'MCL.F':1}
FILES = {'MES.F':'MES.F.csv','MNQ.F':'MNQ.F.csv','M2K.F':'M2K.F.csv','MYM.F':'MYM.F.csv','M6E.F':'M6E.F.csv','M6A.F':'M6A.F.csv','MCL.F':'MCL.F.csv'}

def kz(dt):
    est = dt - timedelta(hours=4); h, m = est.hour, est.minute
    return (3<=h<4) or (h==9 and m>=30) or (h==10 and m<30)

def feat(df):
    df['RSI'] = RSIIndicator(df['close'],14).rsi()
    df['EMA12'] = EMAIndicator(df['close'],12).ema_indicator()
    df['EMA26'] = EMAIndicator(df['close'],26).ema_indicator()
    m = MACD(df['close']); df['MACD'] = m.macd; df['MACD_signal'] = m.macd_signal
    bb = BollingerBands(df['close'])
    df['BB_upper'] = bb.bollinger_hband(); df['BB_middle'] = bb.bollinger_mavg(); df['BB_lower'] = bb.bollinger_lband()
    df['ATR'] = AverageTrueRange(df['high'],df['low'],df['close'],14).average_true_range()
    df['Volume_SMA'] = SMAIndicator(df['volume'],20).sma_indicator()
    df['FVG_Bullish'] = (df['low'].shift(1)>df['high'].shift(2)).astype(int)
    df['FVG_Bearish'] = (df['high'].shift(1)<df['low'].shift(2)).astype(int)
    df['Swing_High'] = df['high'].rolling(20).max().shift(1)
    df['Swing_Low'] = df['low'].rolling(20).min().shift(1)
    df['Fib_Range'] = df['Swing_High'] - df['Swing_Low']
    df['OTE_079_Bull'] = df['Swing_Low'] + df['Fib_Range']*0.79
    df['OTE_079_Bear'] = df['Swing_High'] - df['Fib_Range']*0.79
    df['In_OTE_Bull'] = ((df['close']>=df['Swing_Low']+df['Fib_Range']*0.62)&(df['close']<=df['OTE_079_Bull'])).astype(int)
    df['In_OTE_Bear'] = ((df['close']<=df['Swing_High']-df['Fib_Range']*0.62)&(df['close']>=df['OTE_079_Bear'])).astype(int)
    return df

total_pnl = 0; total_trades = 0
all_results = []

for sym in ['MES.F','MNQ.F','M2K.F','MYM.F','M6E.F','M6A.F','MCL.F']:
    df = pd.read_csv(FILES[sym], parse_dates=['datetime'])
    df.set_index('datetime', inplace=True); df.sort_index(inplace=True)
    df = feat(df.copy()); df.dropna(inplace=True)
    if len(df) < 120: continue
    ts = int(len(df)*0.8)
    scaler = MinMaxScaler(feature_range=(0,1))
    scaled = scaler.fit_transform(df.filter(['close']).values)
    train = scaled[:ts]
    x_tr, y_tr = [], []
    for i in range(60, len(train)):
        x_tr.append(train[i-60:i,0]); y_tr.append(train[i,0])
    x_tr, y_tr = np.array(x_tr), np.array(y_tr)
    x_tr = x_tr.reshape(x_tr.shape[0], x_tr.shape[1], 1)
    model = Sequential([LSTM(128,return_sequences=True,input_shape=(60,1)),LSTM(64,return_sequences=False),Dense(25),Dense(1)])
    model.compile(optimizer='adam', loss='mse')
    model.fit(x_tr, y_tr, batch_size=1, epochs=1, verbose=0)
    trades = []; in_trade = False; sl_t, tp1, tp2 = 10, 10, 20
    for i in range(ts, len(df)):
        bar = df.iloc[i]
        pred = scaler.inverse_transform(model.predict(scaled[i-60:i].reshape(1,60,1), verbose=0))[0][0]
        ml = 1 if pred > bar['close']+bar['ATR']*0.3 else (-1 if pred < bar['close']-bar['ATR']*0.3 else 0)
        bull = 1 if bar['EMA12']>bar['EMA26'] else 0
        hy = 1 if (ml==1 and bull==1 and (bar['FVG_Bullish']==1 or bar['In_OTE_Bull']==1)) else (-1 if (ml==-1 and bull==0 and (bar['FVG_Bearish']==1 or bar['In_OTE_Bear']==1)) else 0)
        if not in_trade:
            if kz(bar.name) and hy!=0:
                in_trade=True; ep, eb, d, ei = bar['close'], bar.name, hy, i
        else:
            pnl_t = (bar['close']-ep)*(1 if d==1 else -1)
            pnl_d = pnl_t*PV[sym]*CON[sym]
            if pnl_t<=-sl_t or pnl_t>=tp1 or pnl_t>=tp2:
                er = 'SL' if pnl_t<=-sl_t else ('TP1' if pnl_t>=tp1 else 'TP2')
                trades.append({'symbol':sym,'direction':d,'entry':ep,'exit':bar['close'],'pnl_t':round(pnl_t,4),'pnl_d':round(pnl_d,2),'exit':er})
                in_trade=False
    if in_trade:
        bar = df.iloc[-1]; pnl_t = (bar['close']-ep)*(1 if d==1 else -1)
        trades.append({'symbol':sym,'direction':d,'entry':ep,'exit':bar['close'],'pnl_t':round(pnl_t,4),'pnl_d':round(pnl_t*PV[sym]*CON[sym],2),'exit':'END'})
    all_results.append((sym, trades))
    print(f'{sym}: {len(trades)}筆')

print()
print('='*60)
print('📊 60天回測結果（Train 80% / Test 20%）')
print('London KZ: 03:00-04:00 EST | NY KZ: 09:30-10:30 EST')
print('SL: 10t | TP1: 10t | TP2: 20t | MCL: 1 contract')
print('='*60)
for sym, trades in all_results:
    if not trades: continue
    tp = sum(t['pnl_d'] for t in trades)
    wins = sum(1 for t in trades if t['pnl_d']>0)
    print(f'\n{sym}: {len(trades)}筆 | 勝{wins} 輸{len(trades)-wins} | 淨 ${tp:.2f}')
    by_exit = {}
    for t in trades:
        by_exit.setdefault(t['exit'], []).append(t['pnl_d'])
    for ex, ps in sorted(by_exit.items()):
        print(f'  {ex}: {len(ps)}筆 = ${sum(ps):.2f}')
    total_pnl += tp; total_trades += len(trades)
wr = len([t for sym,trades in all_results for t in trades if t['pnl_d']>0])/total_trades*100 if total_trades>0 else 0
print(f'\n📈 整體: {total_trades}筆 | 勝率 {wr:.1f}% | 總盈虧 ${total_pnl:.2f}')

# Save
df_out = pd.DataFrame([t for _,trades in all_results for t in trades])
df_out.to_csv('backtest_results.csv', index=False)
print('💾 儲存: backtest_results.csv')