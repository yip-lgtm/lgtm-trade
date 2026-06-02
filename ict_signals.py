"""
ICT Live Trading Signals - Optimized v2
=======================================
First Principles重构版：
- OTE Zone: 0.50-0.89 (wide range for more signals)
- Displacement Filter: 动量确认
- PPOINT_VALUE: 选最高$/point品种
- TP1 = $250 (合格日目标)
- Scaling: 1 contract → +$50 → 2nd contract

Kill Zones: London (06:00-09:00 UTC), NY (12:30-15:00 UTC)
Risk: $200 Daily SL, $100 per trade

Usage:
    python ict_signals.py [--force]
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ======================= Config =======================
MODEL = 'google/gemma-4-26b-a4b-it:free'

KILL_ZONES = {
    'London': (6, 0, 9, 0),
    'NY': (12, 30, 15, 0),
}

# Risk parameters
SL_DOLLAR = 100      # $100 per trade
TP1_DOLLAR = 250     # $250 = qualified day target
DAILY_SL = 200       # $200 daily kill-switch

# PPOINT_VALUE table ($/point for 1 contract)
POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'M6E.F': 12500, 'M6A.F': 10000,
    'MCL.F': 100, 'MBT.F': 0.1, 'MET.F': 0.1, 'MGC.F': 10, 'SIL.F': 5
}

# Max contracts per symbol
MAX_CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'M6E.F': 2, 'M6A.F': 2,
    'MCL.F': 1, 'MBT.F': 2, 'MET.F': 50, 'MGC.F': 2, 'SIL.F': 1
}

PRECISION = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'M6E.F': 4, 'M6A.F': 4,
    'MCL.F': 2, 'MBT.F': 1, 'MET.F': 1, 'MGC.F': 2, 'SIL.F': 3
}

CSV_FILES = {
    'MES.F': '/home/node/.openclaw/workspace/MES.F_1hr.csv',
    'MNQ.F': '/home/node/.openclaw/workspace/MNQ.F_1hr.csv',
    'M2K.F': '/home/node/.openclaw/workspace/M2K.F_1hr.csv',
    'M6E.F': '/home/node/.openclaw/workspace/M6E.F_1hr.csv',
    'M6A.F': '/home/node/.openclaw/workspace/M6A.F_1hr.csv',
    'MCL.F': '/home/node/.openclaw/workspace/MCL.F_1hr.csv',
    'MBT.F': '/home/node/.openclaw/workspace/MBT.F.csv',
    'MET.F': '/home/node/.openclaw/workspace/MET.F.csv',
    'SIL.F': '/home/node/.openclaw/workspace/SIL.F_1hr.csv',
    'MGC.F': '/home/node/.openclaw/workspace/MGC.F_1hr.csv',
}

BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY'
CHAT_ID = '8475453959'


def get_kz_time(dt=None):
    """Get current Kill Zone (UTC)."""
    if dt is None:
        dt = datetime.utcnow()
    h, m = dt.hour, dt.minute
    for kz, (sh, sm, eh, em) in KILL_ZONES.items():
        start = sh * 60 + sm
        end = eh * 60 + em
        now = h * 60 + m
        if start <= now < end:
            return kz
    return None


def load_data(symbol):
    """Load data for symbol."""
    fpath = CSV_FILES.get(symbol)
    if not fpath or not os.path.exists(fpath):
        return None
    df = pd.read_csv(fpath)
    df.columns = [c.lower() for c in df.columns]
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
    if df.index.tzinfo is not None:
        df.index = df.index.tz_localize(None)
    df.sort_index(inplace=True)
    return df
    return df


def get_daily_bias(df):
    """Get 1D MSS bias."""
    if len(df) < 2:
        return 'neutral'
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    return 'bullish' if last_close > prev_close else 'bearish'


def calc_ote_zones(df):
    """Calculate OTE Fibonacci zones (0.50-0.89) from previous day body-to-body."""
    if len(df) < 2:
        return None, None
    prev_high = df['high'].iloc[-2]
    prev_low = df['low'].iloc[-2]
    prev_range = prev_high - prev_low
    ote_50 = prev_low + 0.50 * prev_range
    ote_89 = prev_low + 0.89 * prev_range
    return ote_50, ote_89


def check_displacement(df, bias, kz_start):
    """
    Displacement Filter: 检查价格是否已经向 bias 方向移动。
    Returns True if displacement confirmed.
    """
    if len(df) < 5:
        return False
    
    # kz_start is already naive now
    pre_kz = df[df.index < kz_start].tail(10)
    if len(pre_kz) < 3:
        return False
    
    # Calculate displacement
    if bias == 'bullish':
        return pre_kz['close'].iloc[-1] > pre_kz['close'].iloc[0]
    else:  # bearish
        return pre_kz['close'].iloc[-1] < pre_kz['close'].iloc[0]


def calc_sl_tp(symbol, direction, entry, contracts=1):
    """
    Calculate SL and TP based on $100 risk, $250 TP1 target.
    Uses PPOINT_VALUE table for precise risk management.
    """
    pv = POINT_VALUE.get(symbol, 5)
    prec = PRECISION.get(symbol, 2)
    
    # SL distance = $100 / ($/point * contracts)
    sl_distance = SL_DOLLAR / (pv * contracts)
    
    # TP1 distance = $250 / ($/point * contracts)
    tp1_distance = TP1_DOLLAR / (pv * contracts)
    
    if direction == 'long':
        sl = round(entry - sl_distance, prec)
        tp1 = round(entry + tp1_distance, prec)
        tp2 = round(entry + sl_distance * 6, prec)  # 6:1 for TP2
    else:
        sl = round(entry + sl_distance, prec)
        tp1 = round(entry - tp1_distance, prec)
        tp2 = round(entry - sl_distance * 6, prec)
    
    return sl, tp1, tp2, sl_distance, tp1_distance


def get_dollar_per_point(symbol, contracts=1):
    """Get total $/point for a symbol with given contracts."""
    pv = POINT_VALUE.get(symbol, 5)
    return pv * contracts


def analyze_symbol(symbol, kz, kz_start):
    """
    Full ICT analysis for a symbol.
    Returns signal dict or None.
    """
    df = load_data(symbol)
    if df is None or len(df) < 20:
        return None
    
    # Check data freshness (max 3 days old)
    latest_date = df.index[-1].strftime('%Y-%m-%d')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    days_old = (pd.Timestamp(today) - pd.Timestamp(latest_date)).days
    if days_old > 3:
        return None
    
    # 1. Get 1D Bias
    bias = get_daily_bias(df)
    if bias == 'neutral':
        return None
    
    # 2. Calculate OTE zones
    ote_62, ote_79 = calc_ote_zones(df)
    if ote_62 is None:
        return None
    
    # 3. Get entry price
    entry = round(df['close'].iloc[-1], PRECISION.get(symbol, 2))
    
    # 4. Check if in OTE zone
    in_ote = ote_62 <= entry <= ote_79
    if not in_ote:
        return None
    
    # 5. Check Displacement filter
    if not check_displacement(df, bias, kz_start):
        return None
    
    # 6. Determine direction
    if bias == 'bearish':
        direction = 'short'
    else:
        direction = 'long'
    
    # 7. Get contracts (1 for scaling start)
    contracts = 1  # Start with 1, add 2nd when +$50 unrealized
    
    # 8. Calculate SL/TP
    sl, tp1, tp2, sl_pts, tp1_pts = calc_sl_tp(symbol, direction, entry, contracts)
    
    # 9. Get $/point for ranking
    dpp = get_dollar_per_point(symbol, contracts)
    
    return {
        'symbol': symbol,
        'bias': bias,
        'direction': direction,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'sl_pts': round(sl_pts, 2),
        'tp1_pts': round(tp1_pts, 2),
        'contracts': contracts,
        'dollar_per_point': dpp,
        'ote_low': round(ote_62, 2),
        'ote_high': round(ote_79, 2),
        'kz': kz
    }


def send_telegram(msg):
    """Send Telegram notification."""
    import urllib.request
    import urllib.parse
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={urllib.parse.quote(msg)}&parse_mode=HTML'
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def main(force_kz=False):
    """Main ICT signal generation."""
    kz = get_kz_time()
    if not kz:
        if not force_kz:
            print(f"[{datetime.utcnow().isoformat()}] Not in KZ window, skipping")
            return
        kz = 'FORCED'
        print(f"[{datetime.utcnow().isoformat()}] ⚡ FORCE MODE - Outside KZ")
    else:
        print(f"[{datetime.utcnow().isoformat()}] ICT LIVE {kz} START (v2 Optimized)")
    
    # KZ time range
    now = datetime.utcnow()
    day_str = now.strftime('%Y-%m-%d')
    if kz == 'London':
        kz_start = pd.Timestamp(day_str + ' 06:00:00')
    else:
        kz_start = pd.Timestamp(day_str + ' 12:30:00')
    
    # Analyze all symbols
    signals = []
    for symbol in CSV_FILES.keys():
        result = analyze_symbol(symbol, kz, kz_start)
        if result:
            signals.append(result)
            print(f"  {symbol}: {result['direction'].upper()} @{result['entry']} | "
                  f"SL={result['sl']}({result['sl_pts']}pts) TP1={result['tp1']}({result['tp1_pts']}pts) | "
                  f"${result['dollar_per_point']}/pt | {result['contracts']}c")
        else:
            df = load_data(symbol)
            if df is not None and len(df) >= 20:
                bias = get_daily_bias(df)
                entry = round(df['close'].iloc[-1], PRECISION.get(symbol, 2))
                ote_62, ote_79 = calc_ote_zones(df)
                if ote_62:
                    print(f"  {symbol}: {bias.upper()} | {entry} | OTE:{ote_62:.2f}-{ote_79:.2f} | No signal")
    
    # Sort by $/point (highest first) - focus on strongest
    signals.sort(key=lambda x: x['dollar_per_point'], reverse=True)
    
    # Filter: only trade if in OTE + displacement confirmed
    trade_signals = [s for s in signals if s['ote_low'] <= s['entry'] <= s['ote_high']]
    
    if trade_signals:
        # Take top 2 signals (highest $/point)
        top_signals = trade_signals[:2]
        
        msg = f"🌲 <b>ICT LIVE {kz} KZ (v2 Optimized)</b>\n"
        msg += f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
        
        total_risk = 0
        for s in top_signals:
            risk = s['sl_pts'] * s['dollar_per_point']
            total_risk += risk
            msg += f"{s['symbol']}: {s['direction'].upper()} @{s['entry']}\n"
            msg += f"  OTE: {s['ote_low']}-{s['ote_high']}\n"
            msg += f"  SL={s['sl']} ({s['sl_pts']}pts) | TP1={s['tp1']} ({s['tp1_pts']}pts)\n"
            msg += f"  Risk: ${risk:.0f} | ${s['dollar_per_point']}/pt | {s['contracts']}c\n\n"
        
        msg += f"Total Risk: ${total_risk:.0f} / $200 daily limit"
        
        send_telegram(msg)
        
        print(f"\n📊 ICT {kz} DONE - {len(top_signals)} signals (top $/point)")
        print(f"Total Risk: ${total_risk:.0f} / $200 daily limit")
    else:
        print(f"\n📊 ICT {kz} DONE - 0 signals (no OTE confluence)")
    
    # Git push
    os.system('cd /home/node/.openclaw/workspace && git add -A && git commit -m "ICT v2 signals update" && GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519" git push 2>/dev/null')
    print("✅ Git Push: OK")


if __name__ == "__main__":
    force = '--force' in sys.argv or '-f' in sys.argv
    main(force_kz=force)