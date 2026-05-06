import pandas_ta as ta
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, LSTM

# ====================== 50K 帳戶嚴格設定 ======================
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


def is_kill_zone(dt_utc):
    dt_est = dt_utc - timedelta(hours=4)
    h, m = dt_est.hour, dt_est.minute
    if 3 <= h < 4:
        return True  # London Kill Zone
    if (h == 9 and m >= 30) or (h == 10 and m < 30):
        return True  # NY Kill Zone
    return False


def generate_lstm_signals():
    latest_signals = {}

    for sym, csv_file in CSV_FILES.items():
        try:
            print(f" 訓練 LSTM {sym}...")
            df = pd.read_csv(csv_file, parse_dates=['Datetime'])
            df.rename(columns={'Datetime': 'datetime'}, inplace=True)
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)

            # ICT + TA 特徵
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['EMA12'] = ta.ema(df['close'], length=12)
            df['EMA26'] = ta.ema(df['close'], length=26)
            macd = ta.macd(df['close'])
            df['MACD'] = macd['MACD_12_26_9']
            df['MACD_signal'] = macd['MACDs_12_26_9']
            bb = ta.bbands(df['close'])
            df['BB_upper'] = bb['BBU_5_2.0']
            df['BB_middle'] = bb['BBM_5_2.0']
            df['BB_lower'] = bb['BBL_5_2.0']
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['Volume_SMA'] = ta.sma(df['volume'], length=20)

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

            df.dropna(inplace=True)

            # LSTM 模型
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

            model = Sequential()
            model.add(LSTM(128, return_sequences=True, input_shape=(x_train.shape[1], 1)))
            model.add(LSTM(64, return_sequences=False))
            model.add(Dense(25))
            model.add(Dense(1))
            model.compile(optimizer='adam', loss='mean_squared_error')
            model.fit(x_train, y_train, batch_size=1, epochs=3, verbose=0)

            # 預測下一根
            last_60 = scaled_data[-60:]
            last_60 = np.reshape(last_60, (1, 60, 1))
            pred_scaled = model.predict(last_60, verbose=0)
            pred = scaler.inverse_transform(pred_scaled)[0][0]

            latest = df.iloc[-1].copy()
            ml_signal = 1 if (pred > latest['close'] + latest['ATR'] * 0.3) else 0
            trend_bull = 1 if latest['EMA12'] > latest['EMA26'] else 0

            hybrid = 0
            if ml_signal == 1 and trend_bull == 1 and (latest['FVG_Bullish'] == 1 or latest['In_OTE_Bull'] == 1):
                hybrid = 1
            elif ml_signal == 0 and trend_bull == 0 and (latest['FVG_Bearish'] == 1 or latest['In_OTE_Bear'] == 1):
                hybrid = -1

            in_kill = is_kill_zone(latest.name)
            pv = POINT_VALUE[sym]
            prec = PRECISION[sym]
            est_pnl = round((pred - latest['close']) * pv * 2 if hybrid == 1 else (latest['close'] - pred) * pv * 2, 2)

            latest_signals[sym] = {
                'Timestamp_EST': latest.name.strftime('%Y-%m-%d %H:%M EST'),
                'Close': round(latest['close'], prec),
                'Prediction': round(pred, prec),
                'Hybrid_Signal': hybrid,
                'In_KillZone': in_kill,
                'Est_PnL_2contracts': est_pnl
            }
        except Exception as e:
            print(f" {sym} 錯誤: {e}")
            latest_signals[sym] = {'Error': str(e)}

    summary = pd.DataFrame(latest_signals).T
    print(f"\n{'='*80}")
    print(f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S HKT')} LSTM 自動更新（已包含 MCL）")
    print(summary[['Timestamp_EST', 'Close', 'Prediction', 'Hybrid_Signal', 'In_KillZone', 'Est_PnL_2contracts']])
    summary.to_csv('7_Micro_15min_KillZone_LSTM_Auto_Signals.csv', mode='a', header=False)
    return summary


# ====================== 自動排程主循環 ======================
print("🚀 LSTM 自動排程版已啟動！（已加入 MCL.F）每 15 分鐘更新一次")
print("Profit Target $3,000 | 至少 5 個合格獲利日（每日淨利 ≥ $250） | $200 Daily SL kill-switch | Max Contracts: 2 micro")
print("London Kill Zone 03:00–04:00 EST / NY Kill Zone 09:30–10:30 EST")
print("MCL.F 風險提醒：2 contracts 波動 1 點 = $200（完美吻合 kill-switch）")
print("按 Ctrl+C 隨時停止\n")

while True:
    summary = generate_lstm_signals()

    in_zone = any(row['In_KillZone'] for _, row in summary.iterrows() if isinstance(row, pd.Series))
    if in_zone:
        print("🔥 🔥 🔥 KILL ZONE 內有訊號！立即檢查下單機會 🔥 🔥 🔥")
    else:
        print("⏳ 不在 Kill Zone，安全等待下一根 15min K 線...")

    time.sleep(900)
