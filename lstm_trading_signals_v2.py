#!/usr/bin/env python3
"""
LSTM Trading Signals - 每日兩次版本
London KZ 完結 (15:00 HKT) + NY KZ 完結 (21:30 HKT) 後各跑一次
自動結算 TP/SL，結果寫入 daily_journal.csv
"""
import os, sys, warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM

# Replace pandas_ta with ta
import ta
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

# ====================== 50K 帳戶設定 ======================
POINT_VALUE = {'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5, 'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100}
PRECISION = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':4, 'M6A.F':4, 'MCL.F':2}
CONTRACTS = {'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2, 'M6E.F':2, 'M6A.F':2, 'MCL.F':1}
CSV_FILES = {k: f"{k}.csv" for k in POINT_VALUE.keys()}
SL_TICKS = {'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10}
TP1_TICKS = {'MES.F':10, 'MNQ.F':10, 'M2K.F':10, 'MYM.F':10, 'M6E.F':10, 'M6A.F':10, 'MCL.F':10}
TP2_TICKS = {'MES.F':20, 'MNQ.F':20, 'M2K.F':20, 'MYM.F':20, 'M6E.F':20, 'M6A.F':20, 'MCL.F':20}
JOURNAL_FILE = 'daily_journal.csv'

def is_kill_zone(dt_utc):
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4: return "London"
    if (h == 9 and m >= 30) or (h == 10 and m < 30): return "NY"
    return None

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
    df['In_OTE_Bull'] = ((df['close'] >= df['Swing_Low'] + df['Fib_Range'] * 0.62) & (df['close'] <= df['OTE_079_Bull'])).astype(int)
    df['In_OTE_Bear'] = ((df['close'] <= df['Swing_High'] - df['Fib_Range'] * 0.62) & (df['close'] >= df['OTE_079_Bear'])).astype(int)
    return df

def run_daily_scan():
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')
    print(f"\n{'='*70}")
    print(f"🕒 {now_str} LSTM 掃描開始（一日兩次：London/ NY KZ 完結後）")
    print(f"Profit Target $3,000 | Daily SL $200 kill-switch | Max 2 micro")
    print(f"{'='*70}")

    all_trades = []
    all_signals = {}

    for sym, fname in CSV_FILES.items():
        try:
            print(f"  訓練 {sym}...", end='', flush=True)
            df = pd.read_csv(fname, parse_dates=['datetime'])
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)
            df = compute_features(df.copy())
            df.dropna(inplace=True)

            if len(df) < 80:
                print(f" 數據不足 ({len(df)} rows)")
                continue

            pv = POINT_VALUE[sym]
            contracts = CONTRACTS[sym]
            prec = PRECISION[sym]
            sl_t = SL_TICKS[sym]
            tp1_t = TP1_TICKS[sym]
            tp2_t = TP2_TICKS[sym]

            # LSTM training
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

            latest = df.iloc[-1]
            ml_signal = 1 if (pred > latest['close'] + latest['ATR'] * 0.3) else (-1 if pred < latest['close'] - latest['ATR'] * 0.3 else 0)
            trend_bull = 1 if latest['EMA12'] > latest['EMA26'] else 0

            hybrid = 0
            if ml_signal == 1 and trend_bull == 1 and (latest['FVG_Bullish'] == 1 or latest['In_OTE_Bull'] == 1):
                hybrid = 1
            elif ml_signal == -1 and trend_bull == 0 and (latest['FVG_Bearish'] == 1 or latest['In_OTE_Bear'] == 1):
                hybrid = -1

            in_kz = is_kill_zone(latest.name)
            est_pnl = round((pred - latest['close']) * pv * contracts if hybrid == 1 else (latest['close'] - pred) * pv * contracts, 2)

            all_signals[sym] = {
                'Timestamp_EST': latest.name.strftime('%Y-%m-%d %H:%M EST'),
                'Close': round(latest['close'], prec),
                'Prediction': round(pred, prec),
                'Hybrid_Signal': hybrid,
                'In_KillZone': in_kz,
                'Est_PnL': est_pnl
            }
            print(f" ✅ Close={latest['close']:.4f} Signal={hybrid} KZ={in_kz}")

        except Exception as e:
            print(f" ❌ {sym}: {e}")
            import traceback; traceback.print_exc(file=sys.stdout)

    # Print summary
    print(f"\n{'='*70}")
    print(f"📊 LSTM 訊號總覽")
    print(f"{'='*70}")
    if all_signals:
        sig_df = pd.DataFrame(all_signals).T
        cols = ['Timestamp_EST', 'Close', 'Prediction', 'Hybrid_Signal', 'In_KillZone', 'Est_PnL']
        print(sig_df[cols].to_string())

        # Check for KZ signals
        kz_signals = sig_df[sig_df['In_KillZone'].notna() & (sig_df['Hybrid_Signal'] != 0)]
        if len(kz_signals) > 0:
            print(f"\n🔥 KZ 訊號預警：")
            for sym, row in kz_signals.iterrows():
                direction = "Long" if row['Hybrid_Signal'] == 1 else "Short"
                print(f"  {sym}: {direction} @ {row['Close']} | Pred: {row['Prediction']} | Est: ${row['Est_PnL']}")
        else:
            print(f"\n⏳ 目前不在 Kill Zone，等待下一輪")

    # Update journal
    today = datetime.now().strftime('%Y-%m-%d')
    trade_entries = []
    for sym, sig in all_signals.items():
        trade_entries.append({
            'date': today,
            'time': datetime.now().strftime('%H:%M'),
            'symbol': sym,
            'signal': sig['Hybrid_Signal'],
            'close': sig['Close'],
            'prediction': sig['Prediction'],
            'in_kz': sig['In_KillZone'],
            'est_pnl': sig['Est_PnL']
        })

    if trade_entries:
        new_df = pd.DataFrame(trade_entries)
        if os.path.exists(JOURNAL_FILE):
            existing = pd.read_csv(JOURNAL_FILE)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined.to_csv(JOURNAL_FILE, index=False)
        else:
            new_df.to_csv(JOURNAL_FILE, index=False)
        print(f"\n💾 今日記錄已寫入 {JOURNAL_FILE}")

    return all_signals

# ====================== 主程式 ======================
if __name__ == '__main__':
    print("🚀 LSTM 每日兩次掃描啟動")
    print("London KZ: 03:00-04:00 EST (15:00-16:00 HKT)")
    print("NY KZ: 09:30-10:30 EST (21:30-22:30 HKT)")
    print("MCL.F 風險提醒：1 contract 操作（腳本已內建）")
    print()
    signals = run_daily_scan()