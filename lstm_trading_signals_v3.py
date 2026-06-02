#!/usr/bin/env python3
"""
LSTM Trading Signals v3
- 每小時跑一次（減少刷屏）
- 只在 Kill Zone 內顯示完整入場價 / SL / TP1 / TP2 + 美元金額
- MCL.F 強制 1 contract | $200 Daily SL kill-switch
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
PRECISION  = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2}
CONTRACTS  = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1}
SL_TICKS   = {'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10}
TP1_TICKS  = {'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10}
TP2_TICKS  = {'MES.F':20, 'MNQ.F':20, 'M2K.F':20, 'MYM.F':20, 'M6E.F':20, 'M6A.F':20, 'MCL.F':20}
CSV_FILES  = {k: f"{k}.csv" for k in POINT_VALUE.keys()}
SCAN_FILE  = '7_Micro_15min_KillZone_LSTM_Auto.csv'
JOURNAL_FILE = 'daily_journal.csv'

def is_kill_zone(dt_utc):
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4: return "London"
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return "NY"
    return None

def run_lstm_scan():
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')
    print(f"\n{'='*70}")
    print(f"🕒 {now_str} LSTM 掃描開始（每小時一次）")
    print(f"Profit Target $3,000 | $200 Daily SL kill-switch | Max 2 micro")
    print(f"{'='*70}")

    latest_signals = {}

    for sym, fname in CSV_FILES.items():
        try:
            print(f"  訓練 {sym}...", end='', flush=True)
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
            df['OTE_079_Bull'] = df['Swing_Low'] + df['Fib_Range'] * 0.79
            df['OTE_079_Bear'] = df['Swing_High'] - df['Fib_Range'] * 0.79
            df['In_OTE_Bull'] = ((df['close'] >= df['Swing_Low'] + df['Fib_Range'] * 0.62) & (df['close'] <= df['OTE_079_Bull'])).astype(int)
            df['In_OTE_Bear'] = ((df['close'] <= df['Swing_High'] - df['Fib_Range'] * 0.62) & (df['close'] >= df['OTE_079_Bear'])).astype(int)

            df.dropna(inplace=True)

            # LSTM
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
            if ml_signal == 1 and trend_bull == 1 and (latest['FVG_Bullish'] == 1 or latest['In_OTE_Bull'] == 1):
                hybrid = 1
            elif ml_signal == -1 and trend_bull == 0 and (latest['FVG_Bearish'] == 1 or latest['In_OTE_Bear'] == 1):
                hybrid = -1

            kz = is_kill_zone(latest.name)
            pv = POINT_VALUE[sym]
            contracts = CONTRACTS[sym]
            prec = PRECISION[sym]
            sl_t = SL_TICKS[sym]
            tp1_t = TP1_TICKS[sym]
            tp2_t = TP2_TICKS[sym]

            if hybrid == 1:
                entry = latest['close'] - latest['ATR'] * 0.3
                sl = entry - sl_t * pv / contracts
                tp1 = entry + tp1_t * pv / contracts
                tp2 = entry + tp2_t * pv / contracts
            elif hybrid == -1:
                entry = latest['close'] + latest['ATR'] * 0.3
                sl = entry + sl_t * pv / contracts
                tp1 = entry - tp1_t * pv / contracts
                tp2 = entry - tp2_t * pv / contracts
            else:
                entry = sl = tp1 = tp2 = None

            latest_signals[sym] = {
                'Timestamp_EST': latest.name.strftime('%Y-%m-%d %H:%M EST'),
                'Close': round(latest['close'], prec),
                'Prediction': round(pred, prec),
                'Hybrid_Signal': hybrid,
                'In_KillZone': kz,
                'Contracts': contracts,
                'SL_ticks': sl_t, 'TP1_ticks': tp1_t, 'TP2_ticks': tp2_t,
                'Entry': round(entry, prec) if entry else None,
                'SL': round(sl, prec) if sl else None,
                'TP1': round(tp1, prec) if tp1 else None,
                'TP2': round(tp2, prec) if tp2 else None,
                'Est_PnL': round((pred - latest['close']) * pv * contracts if hybrid == 1
                           else (latest['close'] - pred) * pv * contracts, 2)
            }
            print(f" ✅ Close={latest['close']} Signal={hybrid} KZ={kz}")

        except Exception as e:
            print(f" ❌ {sym}: {e}")
            import traceback; traceback.print_exc(file=sys.stdout)

    # Summary
    summary = pd.DataFrame(latest_signals).T

    if latest_signals:
        print(f"\n{'='*70}")
        print(f"📊 LSTM 訊號總覽")
        print(f"{'='*70}")

        # KZ rows get full detail
        kz_rows = summary[summary['In_KillZone'].notna() & (summary['Hybrid_Signal'] != 0)]
        non_kz_rows = summary[~(summary['In_KillZone'].notna() & (summary['Hybrid_Signal'] != 0))]

        if len(kz_rows) > 0:
            print(f"\n🔥🔥🔥 KILL ZONE 訊號 🔥🔥🔥")
            for sym, row in kz_rows.iterrows():
                direction = "Long" if row['Hybrid_Signal'] == 1 else "Short"
                contracts_disp = row['Contracts']
                print(f"  {sym}: {direction} | @ {row['Entry']}")
                print(f"    SL: {row['SL']} ({row['SL_ticks']}t = ${round(row['SL_ticks'] * POINT_VALUE[sym] / row['Contracts'], 2)})")
                print(f"    TP1: {row['TP1']} ({row['TP1_ticks']}t = ${round(row['TP1_ticks'] * POINT_VALUE[sym] / row['Contracts'], 2)})")
                print(f"    TP2: {row['TP2']} ({row['TP2_ticks']}t = ${round(row['TP2_ticks'] * POINT_VALUE[sym] / row['Contracts'], 2)})")
                print(f"    Est PnL: ${row['Est_PnL']} ({contracts_disp} contract(s))")
        else:
            print(f"\n⏳ 不在 Kill Zone，安全等待...")

        # Non-KZ signals - just show signal type, no price details
        if len(non_kz_rows) > 0:
            brief_cols = ['Timestamp_EST', 'Close', 'Prediction', 'Hybrid_Signal', 'In_KillZone', 'Est_PnL']
            print(f"\n其餘訊號（不在 KZ）：")
            print(non_kz_rows[brief_cols].to_string())

    # Save scan
    summary.to_csv(SCAN_FILE, mode='a', header=False)

    # Journal
    today = datetime.now().date()
    total_pnl = summary['Est_PnL'].sum()
    journal_entry = pd.DataFrame([{'Date': today, 'Total_PnL': round(total_pnl, 2), 'WinRate': 0}])
    journal_entry.to_csv(JOURNAL_FILE, mode='a', header=False, index=False)
    print(f"\n💾 daily_journal.csv 已更新 | Total Est: ${round(total_pnl, 2)}")

    return summary

# ====================== 主程式 ======================
if __name__ == '__main__':
    print("🚀 LSTM 每小時版已啟動 | London KZ 15:00-16:00 HKT | NY KZ 21:30-22:30 HKT")
    print("MCL.F 只用 1 contract | $200 Daily SL kill-switch | 按 Ctrl+C 停止\n")

    run_count = 0
    while True:
        run_count += 1
        print(f"\n{'#'*70}")
        print(f"第 {run_count} 次掃描")
        summary = run_lstm_scan()

        in_zone = any(row['In_KillZone'] is not None for _, row in summary.iterrows())
        if in_zone:
            print("🔥 🔥 🔥 KILL ZONE 內有訊號！立即檢查下單機會 🔥 🔥 🔥")

        time.sleep(3600)  # 1 小時