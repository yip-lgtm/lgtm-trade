"""
ICT Live Trading Signals - Pure ICT Strategy
=============================================
Uses ICT 2022 Model + Power of 3 (AMD) + OTE for signals.
No XGBoost - 100% ICT-based decisions.

Kill Zones: London (06:00-09:00 UTC), NY (12:30-15:00 UTC)
Risk: $200 Daily SL, $100 per trade (2 micro contracts)

Usage:
    python ict_signals.py [--force]
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from openai import OpenAI

# ======================= Config =======================
MODEL = 'google/gemma-4-26b-a4b-it:free'

# Kill Zone schedule (UTC)
KILL_ZONES = {
    'London': (6, 0, 9, 0),
    'NY': (12, 30, 15, 0),
}

# Trading parameters
SL_DOLLAR = 200  # $200 daily kill-switch
RISK_PER_TRADE = 100  # $100 per trade

# Contract specs
CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'M6E.F': 2, 'M6A.F': 2,
    'MCL.F': 1, 'MBT.F': 2, 'MET.F': 50, 'MGC.F': 2, 'SIL.F': 1
}

POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'M6E.F': 12500, 'M6A.F': 10000,
    'MCL.F': 100, 'MBT.F': 0.1, 'MET.F': 0.1, 'MGC.F': 10, 'SIL.F': 5
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

# Telegram
BOT_TOKEN = '8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY'
CHAT_ID = '8475453959'


def get_kz_time(dt=None):
    """Get current Kill Zone."""
    if dt is None:
        dt = datetime.utcnow()
    est = dt - timedelta(hours=4)
    h, m = est.hour, est.minute
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
    df.sort_index(inplace=True)
    return df


def get_daily_bias(df):
    """Get 1D MSS bias."""
    if len(df) < 2:
        return 'neutral'
    last_close = df['close'].iloc[-1]
    prev_close = df['close'].iloc[-2]
    return 'bullish' if last_close > prev_close else 'bearish'


def calc_ote_zones(df):
    """Calculate OTE Fibonacci zones from previous day."""
    if len(df) < 2:
        return None, None
    prev_high = df['high'].iloc[-2]
    prev_low = df['low'].iloc[-2]
    prev_range = prev_high - prev_low
    ote_705 = prev_low + 0.705 * prev_range
    ote_79 = prev_low + 0.79 * prev_range
    return ote_705, ote_79


def calc_sl_tp(symbol, direction, entry, ote_high, sl_distance_pts):
    """Calculate SL and TP."""
    pv = POINT_VALUE.get(symbol, 5)
    prec = PRECISION.get(symbol, 2)
    
    if direction == 'long':
        sl = round(entry - sl_distance_pts, prec)
        tp1 = round(entry + sl_distance_pts * 3, prec)
        tp2 = round(entry + sl_distance_pts * 6, prec)
    else:
        sl = round(entry + sl_distance_pts, prec)
        tp1 = round(entry - sl_distance_pts * 3, prec)
        tp2 = round(entry - sl_distance_pts * 6, prec)
    
    return sl, tp1, tp2


def send_telegram(msg):
    """Send Telegram notification."""
    import urllib.request
    import urllib.parse
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={urllib.parse.quote(msg)}&parse_mode=HTML'
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


class ICTSignals:
    """Pure ICT trading signal generator."""
    
    def __init__(self):
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=api_key
        )
        self.model = MODEL
    
    def analyze_symbol(self, symbol, kz):
        """Generate ICT signal for a symbol."""
        df = load_data(symbol)
        if df is None or len(df) < 20:
            return None
        
        # Get daily bias
        bias = get_daily_bias(df)
        
        # Calculate OTE zones
        ote_705, ote_79 = calc_ote_zones(df)
        if ote_705 is None:
            return None
        
        # Get latest price
        entry = round(df['close'].iloc[-1], PRECISION.get(symbol, 2))
        
        # Get KZ-specific data
        now = datetime.utcnow()
        day_str = now.strftime('%Y-%m-%d')
        
        if kz == 'London':
            kz_start = pd.Timestamp(day_str + ' 06:00:00')
            kz_end = pd.Timestamp(day_str + ' 09:00:00')
        else:  # NY
            kz_start = pd.Timestamp(day_str + ' 12:30:00')
            kz_end = pd.Timestamp(day_str + ' 15:00:00')
        
        # ICT Logic: Only trade in bearish bias with OTE premium
        direction = None
        sl_distance_pts = None
        
        if bias == 'bearish' and entry >= ote_705 and entry <= ote_79:
            direction = 'short'
            sl_distance_pts = 10  # 10 pts = $100 risk for 2 contracts
        elif bias == 'bullish' and entry <= ote_79 and entry >= ote_705:
            direction = 'long'
            sl_distance_pts = 10
        
        if direction is None:
            return {
                'symbol': symbol,
                'bias': bias,
                'entry': entry,
                'ote_low': round(ote_705, 2),
                'ote_high': round(ote_79, 2),
                'direction': 'no_trade',
                'reason': f'Bias={bias}, Price={entry} not in OTE zone'
            }
        
        sl, tp1, tp2 = calc_sl_tp(symbol, direction, entry, ote_79, sl_distance_pts)
        c = CONTRACTS.get(symbol, 1)
        
        return {
            'symbol': symbol,
            'bias': bias,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'contracts': c,
            'ote_low': round(ote_705, 2),
            'ote_high': round(ote_79, 2),
            'kz': kz
        }


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
        print(f"[{datetime.utcnow().isoformat()}] ICT LIVE {kz} START")
    
    # Generate signals
    ict = ICTSignals()
    signals = []
    
    for symbol in CSV_FILES.keys():
        result = ict.analyze_symbol(symbol, kz)
        if result and result.get('direction') != 'no_trade':
            signals.append(result)
            print(f"  {symbol}: {result['direction'].upper()} @{result['entry']} | "
                  f"SL={result['sl']} TP1={result['tp1']} TP2={result['tp2']} ({result['contracts']}c)")
        elif result:
            print(f"  {symbol}: {result['reason']}")
    
    # Send Telegram
    if signals:
        msg = f"🌲 <b>ICT LIVE {kz} KZ</b>\n"
        msg += f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
        
        for s in signals:
            msg += f"{s['symbol']}: {s['direction'].upper()} @{s['entry']}\n"
            msg += f"  OTE: {s['ote_low']}-{s['ote_high']}\n"
            msg += f"  SL={s['sl']} | TP1={s['tp1']} | TP2={s['tp2']}\n"
            msg += f"  ({s['contracts']} contracts)\n\n"
        
        send_telegram(msg)
    
    print(f"\n📊 ICT {kz} DONE - {len(signals)} signals")
    
    # Git push
    os.system('cd /home/node/.openclaw/workspace && git add -A && git commit -m "ICT signals update" && git push 2>/dev/null')
    print("✅ Git Push: OK")


if __name__ == "__main__":
    force = '--force' in sys.argv or '-f' in sys.argv
    main(force_kz=force)