#!/usr/bin/env python3
"""
ICT Kill Zone Signal Scanner — 純 Python 簡化版（無需 ML 庫）
示範用：展示 Kill Zone 邏輯 + OTE 結構 + 入場訊號
"""
import csv
import random
from datetime import datetime, timedelta
from collections import defaultdict

# ====================== 50K 帳戶設定 ======================
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


def is_kill_zone(dt_str):
    """判斷是否在 London / NY Kill Zone"""
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except:
        return False
    est = dt - timedelta(hours=4)  # UTC → EST
    h, m = est.hour, est.minute
    # London: 03:00-04:00 EST, NY: 09:30-10:30 EST
    if 3 <= h < 4:
        return 'London'
    if (h == 9 and m >= 30) or (h == 10 and m < 30):
        return 'NY'
    return False


def calc_ote(high, low, close):
    """計算 OTE Fibonacci 區間"""
    fib_range = high - low
    ote_62 = low + fib_range * 0.62
    ote_79 = low + fib_range * 0.79
    return ote_62, ote_79


def analyze_symbol(sym, csv_file):
    """分析單一合約"""
    try:
        rows = []
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        
        if len(rows) < 60:
            return {'error': f'資料不足（{len(rows)} rows，需要 60+）'}
        
        closes = [float(r['close']) for r in rows]
        highs = [float(r['high']) for r in rows]
        lows = [float(r['low']) for r in rows]
        datetimes = [r['Datetime'] for r in rows]
        
        # 取最近 20 根做 Swing High/Low
        recent_closes = closes[-20:]
        recent_highs = highs[-20:]
        recent_lows = lows[-20:]
        
        swing_high = max(recent_highs)
        swing_low = min(recent_lows)
        
        # ATR (簡化版：取最近 14 根平均波幅)
        tr_list = []
        for i in range(-15, 0):
            tr = max(
                highs[i+1] - lows[i+1],
                abs(highs[i+1] - closes[i]),
                abs(lows[i+1] - closes[i])
            )
            tr_list.append(tr)
        atr = sum(tr_list) / len(tr_list) if tr_list else 0
        
        current_close = closes[-1]
        dt_last = datetimes[-1]
        
        # OTE 計算
        ote_62, ote_79 = calc_ote(swing_high, swing_low, current_close)
        
        # Kill Zone 判斷
        kill_zone = is_kill_zone(dt_last)
        
        # 簡化趨勢判斷（EMA12 vs EMA26 需要多個資料，這裡用價格相對均線）
        sma20 = sum(closes[-20:]) / 20
        trend_bull = 1 if current_close > sma20 else -1
        
        # OTE 區間內判斷
        in_ote_zone = 'Bull' if ote_62 <= current_close <= ote_79 else ('Bear' if ote_79 <= current_close <= ote_62 else 'None')
        
        # 進場訊號（簡化版：基於 Kill Zone + 趨勢 + OTE 位置）
        signal = 0
        if kill_zone and in_ote_zone == 'Bull' and trend_bull == 1:
            signal = 1  # Long
        elif kill_zone and in_ote_zone == 'Bear' and trend_bull == -1:
            signal = -1  # Short
        
        # 估算 P&L（假設 2 contracts，SL = ATR * 2）
        pv = POINT_VALUE[sym]
        prec = PRECISION[sym]
        sl_distance = atr * 2
        risk_dollars = sl_distance * pv * 2
        tp_distance = atr * 3
        tp1_dollars = tp_distance * pv * 2
        tp2_dollars = tp_distance * 2 * pv * 2
        
        return {
            'symbol': sym,
            'datetime': dt_last,
            'kill_zone': kill_zone if kill_zone else 'None',
            'close': round(current_close, prec),
            'swing_high': round(swing_high, prec),
            'swing_low': round(swing_low, prec),
            'ote_62': round(ote_62, prec),
            'ote_79': round(ote_79, prec),
            'in_ote': in_ote_zone,
            'trend': 'Bull' if trend_bull == 1 else 'Bear',
            'signal': signal,
            'atr': round(atr, prec),
            'sl_ticks': round(sl_distance, prec),
            'risk_usd': round(risk_dollars, 2),
            'tp1_usd': round(tp1_dollars, 2),
            'tp2_usd': round(tp2_dollars, 2),
        }
    except Exception as e:
        return {'symbol': sym, 'error': str(e)}


def main():
    print("=" * 80)
    print("🚀 ICT Kill Zone Signal Scanner（純 Python 示範版）")
    print("   50K Prop Firm | $3,000 Target | 5 Qualifying Days | $200 Daily SL")
    print("   London Kill Zone: 03:00-04:00 EST | NY Kill Zone: 09:30-10:30 EST")
    print("=" * 80)
    
    results = []
    for sym, csv_file in CSV_FILES.items():
        result = analyze_symbol(sym, csv_file)
        results.append(result)
        print(f"\n{sym}:")
        if 'error' in result:
            print(f"  ❌ {result['error']}")
        else:
            print(f"  🕐 {result['datetime']} EST")
            print(f"  📍 Kill Zone: {result['kill_zone']}")
            print(f"  💰 Close: {result['close']}")
            print(f"  📈 Trend: {result['trend']} | OTE Zone: {result['in_ote']}")
            print(f"  🔮 OTE 0.62: {result['ote_62']} | OTE 0.79: {result['ote_79']}")
            print(f"  🎯 Signal: {'LONG 📈' if result['signal'] == 1 else 'SHORT 📉' if result['signal'] == -1 else 'WAIT ⏳'}")
            print(f"  🛡️  ATR: {result['atr']} | SL: {result['sl_ticks']} ticks | Risk: ${result['risk_usd']}")
            print(f"  🎯 TP1: ${result['tp1_usd']} | TP2: ${result['tp2_usd']}")
    
    # 總結
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    
    in_zone = [r for r in results if 'kill_zone' in r and r['kill_zone'] != 'None']
    long_signals = [r for r in results if 'signal' in r and r['signal'] == 1]
    short_signals = [r for r in results if 'signal' in r and r['signal'] == -1]
    
    print(f"Kill Zone 內合約: {len(in_zone)}")
    print(f"Long 訊號: {len(long_signals)} — {[r['symbol'] for r in long_signals]}")
    print(f"Short 訊號: {len(short_signals)} — {[r['symbol'] for r in short_signals]}")
    print(f"Wait 觀望: {len(results) - len(long_signals) - len(short_signals)}")
    
    if in_zone:
        print("\n🔥 🔥 🔥 KILL ZONE 內有合約 — 等待精準入場 🔥 🔥 🔥")
    else:
        print("\n⏳ 目前不在 Kill Zone — 等待下一個機會")


if __name__ == '__main__':
    main()
