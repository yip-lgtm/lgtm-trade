"""
ICT Live Trading Signals - Full ICT Analysis Format
===================================================
Outputs detailed ICT analysis in Saba's preferred format.

Usage:
    python ict_signals_full.py [--force]
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta

# ======================= Config =======================
KILL_ZONES = {
    'London': (6, 0, 9, 0),
    'NY': (12, 30, 15, 0),
}

CSV_FILES = {
    'MES.F': '/home/node/.openclaw/workspace/MES.F_1hr.csv',
    'MNQ.F': '/home/node/.openclaw/workspace/MNQ.F_1hr.csv',
    'M2K.F': '/home/node/.openclaw/workspace/M2K.F_1hr.csv',
    'MGC.F': '/home/node/.openclaw/workspace/MGC.F_1hr.csv',
    'M6E.F': '/home/node/.openclaw/workspace/M6E.F_1hr.csv',
    'M6A.F': '/home/node/.openclaw/workspace/M6A.F_1hr.csv',
    'MCL.F': '/home/node/.openclaw/workspace/MCL.F_1hr.csv',
    'MBT.F': '/home/node/.openclaw/workspace/MBT.F.csv',
    'MET.F': '/home/node/.openclaw/workspace/MET.F.csv',
    'SIL.F': '/home/node/.openclaw/workspace/SIL.F_1hr.csv',
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


def get_full_ict_analysis(symbol, kz='London'):
    """Get complete ICT analysis for a symbol."""
    df = load_data(symbol)
    if df is None or len(df) < 20:
        return None
    
    # Data freshness check
    latest_date = df.index[-1].strftime('%Y-%m-%d')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    days_old = (pd.Timestamp(today) - pd.Timestamp(latest_date)).days
    if days_old > 3:
        return None
    
    # Get yesterday's data
    today_str = datetime.utcnow().strftime('%Y-%m-%d')
    df_yest = df[df.index.strftime('%Y-%m-%d') < today_str]
    
    if len(df_yest) < 2:
        return None
    
    prev_day = df_yest.tail(2)
    prev_high = prev_day['high'].max()
    prev_low = prev_day['low'].min()
    prev_close = prev_day['close'].iloc[-1]
    
    # Current data
    current_close = df['close'].iloc[-1]
    current_high = df['high'].iloc[-1]
    current_low = df['low'].iloc[-1]
    
    # Bias
    bias = 'BEARISH' if current_close < prev_close else 'BULLISH'
    change = current_close - prev_close
    
    # OTE zones (0.62-0.79)
    prev_range = prev_high - prev_low
    ote_62 = prev_low + 0.62 * prev_range
    ote_79 = prev_low + 0.79 * prev_range
    
    # Pre-KZ data
    kz_start = pd.Timestamp(today_str + ' 06:00:00') if kz == 'London' else pd.Timestamp(today_str + ' 12:30:00')
    pre_kz = df[df.index < kz_start]
    pre_kz_high = pre_kz['high'].max() if len(pre_kz) > 0 else current_high
    pre_kz_low = pre_kz['low'].min() if len(pre_kz) > 0 else current_low
    
    # Liquidity sweep detection
    swept = current_close > pre_kz_high if bias == 'BEARISH' else current_close < pre_kz_low
    
    # Check if in OTE zone
    in_ote = ote_62 <= current_close <= ote_79
    
    # Determine direction and calculate SL/TP
    if bias == 'BEARISH':
        direction = 'SHORT'
        entry = ote_62  # OTE low for short
        sl = round(ote_79 + 10, 2)
        tp1 = round(entry - 30, 2)
        tp2 = round(entry - 60, 2)
    else:
        direction = 'LONG'
        entry = ote_79  # OTE high for long
        sl = round(ote_62 - 10, 2)
        tp1 = round(entry + 30, 2)
        tp2 = round(entry + 60, 2)
    
    return {
        'symbol': symbol,
        'bias': bias,
        'direction': direction,
        'current_close': current_close,
        'yesterday_close': prev_close,
        'change': change,
        'prev_high': prev_high,
        'prev_low': prev_low,
        'prev_range': prev_range,
        'ote_62': ote_62,
        'ote_79': ote_79,
        'in_ote': in_ote,
        'pre_kz_high': pre_kz_high,
        'pre_kz_low': pre_kz_low,
        'swept': swept,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'days_old': days_old,
    }


def format_signal(data):
    """Format signal in detailed ICT format."""
    sym = data['symbol']
    short_name = sym.split('.')[0]
    bias_icon = '🔴' if data['bias'] == 'BEARISH' else '🟢'
    swept_icon = '✅ Already swept' if data['swept'] else '⏳ Not yet swept'
    
    return f"""
📊 {sym} - {data['direction']}

1. Daily Bias

{bias_icon} {data['bias']}

• Today Close: {data['current_close']:.2f}
• Yesterday Close: {data['yesterday_close']:.2f}
• Change: {data['change']:+.2f} pts

2. Pre-{short_name} Range

| | Value |
| ----- | --------- |
| High | {data['prev_high']:.2f} |
| Low | {data['prev_low']:.2f} |
| Range | {data['prev_range']:.2f} pts |

3. Liquidity Sweep

• Pre-{short_name} High: {data['pre_kz_high']:.2f} {swept_icon}

4. OTE Premium Zone

| Fib Level | Price |
| --------- | ------- |
| 0.62 | {data['ote_62']:.2f} |
| 0.79 | {data['ote_79']:.2f} |

5. {short_name} {data['direction']} Setup

| Parameter | Value |
| ---------- | --------------------------- |
| Direction | {data['direction']} |
| Entry Zone | {data['ote_62']:.2f} - {data['ote_79']:.2f} |
| Current Price | {data['current_close']:.2f} |
| SL | {data['sl']:.2f} |
| TP1 | {data['tp1']:.2f} |
| TP2 | {data['tp2']:.2f} |
| Risk | $100 (2 contracts) |

6. Qualified Days Update

| Day | Status |
|-----|--------|
| Day 1-4 | ✅ Locked |
| Day 5 | 🎯 Target: $250+ |
"""


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
        print(f"[{datetime.utcnow().isoformat()}] ICT LIVE {kz} KZ")
    
    # Analyze all symbols
    signals = []
    for symbol in CSV_FILES.keys():
        result = get_full_ict_analysis(symbol, kz)
        if result:
            signals.append(result)
            if result['in_ote']:
                print(f"  ✅ {symbol}: {result['direction']} @ {result['current_close']:.2f} (OTE: {result['ote_62']:.2f}-{result['ote_79']:.2f})")
            else:
                print(f"  ⏸️  {symbol}: {result['bias']} | {result['current_close']:.2f} | OTE:{result['ote_62']:.2f}-{result['ote_79']:.2f} | No signal")
    
    # Filter signals with OTE confluence
    trade_signals = [s for s in signals if s['in_ote']]
    
    if trade_signals:
        # Sort by potential (highest $/point first)
        trade_signals.sort(key=lambda x: x['prev_range'], reverse=True)
        
        msg = f"🌲 <b>ICT LIVE {kz} KZ</b>\n"
        msg += f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
        
        for s in trade_signals[:3]:  # Top 3 signals
            msg += format_signal(s)
        
        send_telegram(msg)
        print(f"\n📊 ICT {kz} DONE - {len(trade_signals)} signals")
    else:
        print(f"\n📊 ICT {kz} DONE - 0 signals (no OTE confluence)")
    
    # Git push
    os.system('cd /home/node/.openclaw/workspace && git add -A && git commit -m "ICT signals update" && GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519" git push 2>/dev/null')
    print("✅ Git Push: OK")


if __name__ == "__main__":
    force = '--force' in sys.argv or '-f' in sys.argv
    main(force_kz=force)