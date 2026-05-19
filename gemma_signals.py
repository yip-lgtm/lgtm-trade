"""
Gemma Trading Signals - Pure LLM-based Trading
================================================
Uses Gemma 4 26B via OpenRouter for direction signals.
No XGBoost - 100% LLM-based decisions.

Requires: OPENAI_API_KEY environment variable (OpenRouter API key)

Usage:
    export OPENAI_API_KEY=sk-or-v1-...
    python gemma_signals.py [--force]
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
    'London': (6, 0, 9, 0),   # 06:00-09:00 UTC
    'NY': (12, 30, 15, 0),    # 12:30-15:00 UTC
}

# Trading parameters
SL_DOLLAR = 200  # $200 kill-switch

# Contract specs
CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'M6E.F': 2, 'M6A.F': 2,
    'MCL.F': 1, 'MBT.F': 2, 'MET.F': 50, 'MGC.F': 2, 'SIL.F': 1
}

POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'M6E.F': 12500, 'M6A.F': 10000,
    'MCL.F': 100, 'MBT.F': 0.1, 'MET.F': 0.1, 'MGC.F': 10, 'SIL.F': 5
}

TICK_SIZE = {
    'MES.F': 1.0, 'MNQ.F': 1.0, 'M2K.F': 1.0, 'M6E.F': 1.0, 'M6A.F': 1.0,
    'MCL.F': 0.01, 'MBT.F': 1.0, 'MET.F': 0.5, 'MGC.F': 1.0, 'SIL.F': 0.005
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


def calc_sl_tp(symbol, direction, entry):
    """Calculate SL and TP based on $200 kill-switch."""
    pv = POINT_VALUE.get(symbol, 5)
    c = CONTRACTS.get(symbol, 1)
    prec = PRECISION.get(symbol, 2)
    
    # SL distance in price terms: $200 / (pv * c)
    sl_dist = SL_DOLLAR / (pv * c)
    
    # For SIL.F special case
    if symbol == 'SIL.F':
        sl_dist = 0.2
    
    if direction == 'long':
        sl = round(entry - sl_dist, prec)
        tp1 = round(entry + sl_dist * 3, prec)
        tp2 = round(entry + sl_dist * 6, prec)
    else:
        sl = round(entry + sl_dist, prec)
        tp1 = round(entry - sl_dist * 3, prec)
        tp2 = round(entry - sl_dist * 6, prec)
    
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


class LLMSignals:
    def __init__(self):
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=api_key
        )
        self.model = MODEL
    
    def get_direction(self, symbol, price, kz):
        """Get trading direction from LLM."""
        prompt = f"""You are a professional futures trader.

Symbol: {symbol}
Current Price: {price}
Kill Zone: {kz}

Based on technical analysis, should I go LONG or SHORT today?

Respond with ONLY one word:
LONG
or
SHORT"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a professional futures trader.'},
                    {'role': 'user', 'content': prompt}
                ],
                max_tokens=10,
                temperature=0.3
            )
            direction = response.choices[0].message.content.strip().upper()
            return 'long' if 'LONG' in direction else 'short' if 'SHORT' in direction else None
        except Exception as e:
            print(f"  {symbol}: LLM error - {e}")
            return None
    
    def analyze_trade(self, symbol, direction, entry, sl, tp1, tp2):
        """Get LLM approval for a trade."""
        prompt = f"""You are a professional futures trader.

Symbol: {symbol}
Direction: {direction.upper()}
Entry: {entry}
Stop Loss: {sl}
Take Profit 1: {tp1}
Take Profit 2: {tp2}

Analyze this trade setup and respond with ONLY this format:
APPROVE - [Confidence] - [1 sentence]
or
REJECT - [Confidence] - [1 sentence]"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': 'You are a professional futures trader.'},
                    {'role': 'user', 'content': prompt}
                ],
                max_tokens=80,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"ERROR: {e}"


def main(force_kz=False):
    """Main trading signal generation."""
    kz = get_kz_time()
    if not kz:
        if not force_kz:
            print(f"[{datetime.utcnow().isoformat()}] Not in KZ window, skipping")
            return
        kz = 'FORCED'
        print(f"[{datetime.utcnow().isoformat()}] ⚡ FORCE MODE - Outside KZ")
    else:
        print(f"[{datetime.utcnow().isoformat()}] Gemma LIVE {kz} START")
    
    # Initialize LLM
    llm = LLMSignals()
    
    signals = []
    
    # Analyze each symbol
    for symbol in CSV_FILES.keys():
        df = load_data(symbol)
        if df is None or len(df) < 10:
            print(f"  {symbol}: No data, skipping")
            continue
        
        # Get latest close
        entry = round(df['close'].iloc[-1], PRECISION.get(symbol, 2))
        
        # Get direction from LLM
        direction = llm.get_direction(symbol, entry, kz)
        if not direction:
            continue
        
        # Calculate SL/TP
        sl, tp1, tp2 = calc_sl_tp(symbol, direction, entry)
        c = CONTRACTS.get(symbol, 1)
        
        # Get approval
        analysis = llm.analyze_trade(symbol, direction, entry, sl, tp1, tp2)
        
        signals.append({
            'symbol': symbol,
            'direction': direction,
            'entry': entry,
            'sl': sl,
            'tp1': tp1,
            'tp2': tp2,
            'contracts': c,
            'analysis': analysis
        })
        
        sl_dist = abs(entry - sl)
        print(f"  {symbol}: {direction.upper()} @{entry} | SL={sl} ({sl_dist:.4f}) | TP1={tp1} TP2={tp2} ({c}c)")
    
    # Send Telegram
    if signals:
        msg = f"🌲 <b>Gemma LIVE {kz} KZ</b>\n"
        msg += f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
        
        for s in signals:
            msg += f"{s['symbol']}: {s['direction'].upper()} @{s['entry']}\n"
            msg += f"  SL={s['sl']} | TP1={s['tp1']} | TP2={s['tp2']}\n"
            msg += f"  ({s['contracts']} contracts)\n\n"
        
        send_telegram(msg)
    
    print(f"\n📊 Gemma {kz} DONE - {len(signals)} signals")
    
    # Git push
    os.system('cd /home/node/.openclaw/workspace && git add -A && git commit -m "Gemma signals update" && git push 2>/dev/null')
    print("✅ Git Push: OK")


if __name__ == "__main__":
    force = '--force' in sys.argv or '-f' in sys.argv
    main(force_kz=force)