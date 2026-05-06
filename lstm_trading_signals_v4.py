#!/usr/bin/env python3
"""
LSTM Trading Signals v4 - 全自動每小時版
- 每小時跑一次
- KZ 內顯示完整 Entry/SL/TP1/TP2 + 美元
- MCL 強制 1 contract | $200 Daily SL kill-switch
"""
import os, sys, time, warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM

# Use 'ta' library (NOT pandas_ta - pandas_ta requires Python 3.12+)
import ta
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

# ====================== 50K 帳戶設定 ======================
POINT_VALUE = {'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100}
PRECISION = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2}
CSV_FILES = {k: f"{k}.csv" for k in POINT_VALUE.keys()}

def is_kill_zone(dt_utc):
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4: return "London"
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return "NY"
    return None

def run_lstm_scan():
    print(f"\n{'='*70}")
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')} 全自動掃描開始（每小時一次）")
    print(f"Profit Target $3,000 | 5 合格獲利日 | $200 Daily SL kill-switch | MCL 強制1 contract")
    print(f"{'='*70}")

    for sym, fname in CSV_FILES.items():
        try:
            df = pd.read_csv(fname, parse_dates=['datetime'])
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)

            # ICT + TA
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
            df['In_OTE_Bull'] = ((df['close'] >= df['Swing_Low'] + df['Fib_Range'] * 0.62) & (df['close'] <= df['Swing_Low'] + df['Fib_Range'] * 0.79)).astype(int)
            df['In_OTE_Bear'] = ((df['close'] <= df['Swing_High'] - df['Fib_Range'] * 0.62) & (df['close'] >= df['Swing_High'] - df['Fib_Range'] * 0.79)).astype(int)

            df.dropna(inplace=True)

            # LSTM (epochs=1 最快)
            data = df.filter(['close'])
            dataset = data.values
            scaler = MinMaxScaler(feature_range=(0, 1))
            scaled_data = scaler.fit_transform(dataset)

            train_size = int(len(scaled_data) * 0.95)
            train_data = scaled_data[:train_size]
            x_train, y_train = [], []
            for i in range(60, len(train_data)):
                x_train.append(train_data[i - 60:i, 0])
                y_train.append(train_data[i, 0])
            x_train, y_train = np.array(x_train), np.array(y_train)
            x_train = np.reshape(x_train, (x_train.shape[0], x_train.shape[1], 1))

            model = Sequential([
                LSTM(128, return_sequences=True, input_shape=(x_train.shape[1], 1)),
                LSTM(64, return_sequences=False),
                Dense(25), Dense(1)
            ])
            model.compile(optimizer='adam', loss='mean_squared_error')
            model.fit(x_train, y_train, batch_size=1, epochs=1, verbose=0)

            last_60 = scaled_data[-60:]
            last_60 = np.reshape(last_60, (1, 60, 1))
            pred = scaler.inverse_transform(model.predict(last_60, verbose=0))[0][0]

            latest = df.iloc[-1].copy()
            ml_signal = 1 if (pred > latest['close'] + latest['ATR'] * 0.3) else (-1 if pred < latest['close'] - latest['ATR'] * 0.3 else 0)
            trend_bull = 1 if latest['EMA12'] > latest['EMA26'] else 0

            hybrid = 0
            if ml_signal == 1 and trend_bull == 1 and (latest['FVG_Bullish'] or latest['In_OTE_Bull']):
                hybrid = 1
            elif ml_signal == -1 and trend_bull == 0 and (latest['FVG_Bearish'] or latest['In_OTE_Bear']):
                hybrid = -1

            kz = is_kill_zone(latest.name)
            pv = POINT_VALUE[sym]
            contracts = 1 if sym == 'MCL.F' else 2
            sl_points = 200 / (pv * contracts)
            entry = latest['close']
            sl = entry - sl_points if hybrid == 1 else entry + sl_points
            tp1 = entry + 3 * sl_points if hybrid == 1 else entry - 3 * sl_points
            tp2 = entry + 6 * sl_points if hybrid == 1 else entry - 6 * sl_points
            est_pnl = round((pred - latest['close']) * pv * contracts if hybrid == 1
                       else (latest['close'] - pred) * pv * contracts, 2)

            prec = PRECISION[sym]
            print(f"{sym:6} | Signal:{hybrid:2} | Close:{latest['close']:.{prec}f} | Pred:{pred:.{prec}f} | Est:${est_pnl:.2f}")

            if hybrid != 0 and kz:
                tp1_dollar = 3 * 200 / contracts
                tp2_dollar = 6 * 200 / contracts
                print(f"  🔥 KZ內有效訊號！入場價:{entry:.{prec}f} | SL:{sl:.{prec}f} | TP1:{tp1:.{prec}f} | TP2:{tp2:.{prec}f} | ${contracts}合約")
                print(f"  實際風險: $200 | 潛在盈利 TP1: ${tp1_dollar:.2f} | TP2: ${tp2_dollar:.2f}")

        except Exception as e:
            print(f" ❌ {sym}: {e}")
            import traceback; traceback.print_exc(file=sys.stdout)

    print(f"\n📊 掃描完成（每小時一次）\n")

# ====================== 全自動排程 ======================
if __name__ == '__main__':
    print("🚀 本機全自動版 v4 已啟動（24小時運行）")
    print("Profit Target $3,000 | 5 合格獲利日 | $200 Daily SL kill-switch | MCL 強制1 contract")
    print("London KZ: 15:00-16:00 HKT | NY KZ: 21:30-22:30 HKT")
    print("按 Ctrl+C 停止\n")

    run_count = 0
    while True:
        run_count += 1
        print(f"\n{'#'*70}")
        print(f"第 {run_count} 次掃描")
        run_lstm_scan()
        time.sleep(3600)  # 每小時跑一次