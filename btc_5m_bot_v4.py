#!/usr/bin/env python3
"""
BTC 5m Polymarket Bot - Markov + Percentile ATR/Vol Filter
- State window: 3 candles (streak-based, capped at 3)
- ATR: 40th percentile filter (dynamic)
- Vol: 50th percentile filter (dynamic)
- MIN_PROB: 0.82
- State file: /home/ubuntu/lgtm-trade/btc_5m_state.json
"""

import time
import json
import sys
import asyncio
import httpx
import os
from datetime import datetime, timezone
from collections import Counter

# === CONFIG ===
DRY_RUN = False  # LIVE TRADING
MIN_PROB = 0.82
MIN_EDGE = 0.03
MAX_POSITION = 5.0
MAX_DAILY_LOSS = 30.0
CHECK_INTERVAL = 81
STATE_WINDOW = 3  # capped at 3 (streak cap)
MIN_SAMPLES = 12   # minimum samples for reliable p̂

TELEGRAM_TOKEN = "8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY"
TELEGRAM_CHAT_ID = "8475453959"
GAMMA_API = "https://gamma-api.polymarket.com"

# Files (FIXED paths)
STATE_FILE = "/home/ubuntu/lgtm-trade/btc_5m_state.json"
CONFIG_FILE = "/home/ubuntu/lgtm-trade/btc_5m_config.json"

# State
BTC_KLINES = []
TRANSITION_MATRIX = {}
STATE_HISTORY = []
CYCLE_COUNT = 0
CONSECUTIVE_LOSSES = 0
TODAY_LOSS = 0.0
LAST_TRADE_DATE = None
PAUSED_TODAY = False

def get_current_window_ts():
    return (int(time.time()) // 300) * 300

def get_next_window_ts():
    return get_current_window_ts() + 300

def construct_slug(window_ts):
    return f"btc-updown-5m-{window_ts}"

def parse_outcome_prices(opp_str):
    try:
        prices = json.loads(opp_str)
        return float(prices[0]), float(prices[1])
    except:
        return 0.5, 0.5

def get_percentile(values, percentile):
    """Get percentile value from a list"""
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * percentile / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]

async def fetch_btc_klines():
    """Fetch BTC 5m candles from OKX"""
    global BTC_KLINES
    try:
        all_candles = []
        url_template = 'https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=200&after={}'
        after = None
        
        for page in range(8):
            url = url_template.format(after) if after else url_template.format('')
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(url)
                data = resp.json()
                candles = data.get('data', [])
                if not candles:
                    break
                all_candles.extend(candles)
                after = candles[-1][0]
                if len(all_candles) >= 1440:
                    break
        
        all_candles.reverse()
        BTC_KLINES = all_candles[:1440]
        return len(BTC_KLINES)
    except Exception as e:
        print(f"[BTC] Error: {e}")
        return 0

def compute_directions(klines):
    return ['UP' if float(k[4]) > float(k[1]) else 'DOWN' for k in klines]

def compute_streaks(directions):
    """Compute streak values, cap at 3"""
    streaks = []
    current_streak = 1
    for i, d in enumerate(directions):
        if i == 0:
            streaks.append(1)
        elif directions[i-1] == d:
            current_streak += 1
            streaks.append(min(current_streak, 3))  # CAP AT 3
        else:
            current_streak = 1
            streaks.append(current_streak)
    return streaks

def compute_atr(klines, index, period=14):
    """Compute ATR at specific index"""
    if index < period:
        return 0
    trs = []
    for j in range(1, period + 1):
        if index - j < 0:
            break
        high = float(klines[index - j + 1][2])
        low = float(klines[index - j + 1][3])
        prev_close = float(klines[index - j][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0

def get_volume(index, klines):
    if index < 0 or index >= len(klines):
        return 0
    return float(klines[index][5])

def get_markov_state(streaks, index):
    """Build 3-char capped state from streaks"""
    if index < STATE_WINDOW:
        return None
    # Take last STATE_WINDOW values, cap each at 3
    state_vals = [min(streaks[i], 3) for i in range(index - STATE_WINDOW, index)]
    return ''.join(str(v) for v in state_vals)

def build_filtered_matrix(directions, streaks, klines):
    """Build Markov matrix with percentile-based ATR and Vol filters"""
    global TRANSITION_MATRIX
    
    # Collect all ATR and Vol values for percentile calculation
    all_atrs = []
    all_vols = []
    for i in range(STATE_WINDOW, len(klines) - 1):
        atr = compute_atr(klines, i)
        vol = get_volume(i, klines)
        if atr > 0:
            all_atrs.append(atr)
        if vol > 0:
            all_vols.append(vol)
    
    # Calculate 40th percentile for ATR and 50th for Vol
    atr_threshold = get_percentile(all_atrs, 40)
    vol_threshold = get_percentile(all_vols, 50)
    
    filtered_indices = []
    for i in range(STATE_WINDOW, len(klines) - 1):
        atr = compute_atr(klines, i)
        vol = get_volume(i, klines)
        if atr >= atr_threshold and vol >= vol_threshold:
            filtered_indices.append(i)
    
    transitions = {}
    for i in filtered_indices:
        state = get_markov_state(streaks, i)
        if state is None:
            continue
        next_dir = directions[i + 1]
        if state not in transitions:
            transitions[state] = {'UP': 0, 'DOWN': 0}
        transitions[state][next_dir] += 1
    
    TRANSITION_MATRIX = {}
    for state, counts in transitions.items():
        total = counts['UP'] + counts['DOWN']
        if total >= MIN_SAMPLES:
            TRANSITION_MATRIX[state] = {
                'UP': counts['UP'] / total,
                'DOWN': counts['DOWN'] / total,
                'total': total
            }
    
    return len(filtered_indices), len(TRANSITION_MATRIX), atr_threshold, vol_threshold

def get_state(state):
    """Get p̂ for a state, fallback to 0.5 if insufficient samples"""
    if state is None or state not in TRANSITION_MATRIX:
        return 0.5, 0
    m = TRANSITION_MATRIX[state]
    last_char = state[-1]
    last_dir = 'UP' if last_char == '1' else 'DOWN'
    key = 'UP' if last_dir == 'UP' else 'DOWN'
    return m.get(key, 0.5), m.get('total', 0)

async def execute_live_trade(market, direction, prob_continue, edge, q, signal_msg):
    """Execute live trade with real money via PolyClaw L2 Client"""
    global CONSECUTIVE_LOSSES, TODAY_LOSS, LAST_TRADE_DATE, PAUSED_TODAY
    
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    if LAST_TRADE_DATE != today:
        TODAY_LOSS = 0.0
        CONSECUTIVE_LOSSES = 0
        LAST_TRADE_DATE = today
        PAUSED_TODAY = False
    
    if PAUSED_TODAY:
        return {'message': signal_msg + "\n\n⛸️ TRADING PAUSED TODAY (loss limit reached)", 'executed': False, 'reason': 'paused'}
    
    if TODAY_LOSS >= MAX_DAILY_LOSS:
        PAUSED_TODAY = True
        return {'message': signal_msg + f"\n\n🚫 DAILY LOSS LIMIT REACHED (${TODAY_LOSS:.2f} >= ${MAX_DAILY_LOSS:.2f})\nTrading paused for today.", 'executed': False, 'reason': 'daily_limit'}
    
    position_size = min(MAX_POSITION, 1.0)
    
    if direction == 'UP':
        outcome = 'YES'
        entry_price = market['yes_price']
    else:
        outcome = 'NO'
        entry_price = market['no_price']
    
    try:
        from py_clob_client_v2 import ClobClient, SignatureTypeV2
        from py_clob_client_v2.order_builder.constants import BUY, SELL
        from py_clob_client_v2 import OrderArgs, PartialCreateOrderOptions
        
        private_key = os.environ.get('POLYCLAW_PRIVATE_KEY', '')
        funder = os.environ.get('RELAYER_API_KEY_ADDRESS', '')
        
        if not private_key or not funder:
            raise Exception('Missing POLYCLAW_PRIVATE_KEY or RELAYER_API_KEY_ADDRESS')
        
        temp_client = ClobClient(host='https://clob.polymarket.com', key=private_key, chain_id=137)
        api_creds = temp_client.create_or_derive_api_key()
        
        client = ClobClient(
            host='https://clob.polymarket.com',
            key=private_key,
            chain_id=137,
            creds=api_creds,
            signature_type=SignatureTypeV2.POLY_1271,
            funder=funder
        )
        
        token_id = market.get('tokens', [None])[0] if market.get('tokens') else None
        if not token_id:
            raise Exception('No token_id in market')
        
        side = BUY if direction == 'UP' else SELL
        size = position_size / entry_price
        
        response = client.create_and_post_order(
            OrderArgs(token_id=token_id, price=entry_price, size=size, side=side),
            options=PartialCreateOrderOptions(tick_size='0.01', neg_risk=False),
        )
        
        if response.get('orderID'):
            CONSECUTIVE_LOSSES = 0
            result_text = f"ORDER PLACED: {response.get('orderID')[:20]}..."
            result_emoji = "✅"
        else:
            raise Exception(str(response))
        
    except Exception as e:
        pnl = 0
        CONSECUTIVE_LOSSES += 1
        TODAY_LOSS += position_size
        result_emoji = "❌"
        result_text = f"ERROR: {str(e)[:100]}"
    
    if CONSECUTIVE_LOSSES >= 3:
        pause_msg = f"\n\n⚠️ 3 CONSECUTIVE LOSSES - Trading paused for today"
    else:
        pause_msg = ""
    
    trade_msg = f"""

💰 <b>LIVE TRADE EXECUTED</b>
🔹 Direction: <b>{direction}</b> ({outcome})
🔹 Entry Price: <code>{entry_price:.3f}</code>
🔹 Position: <b>${position_size:.2f}</b>
🔹 Expected Prob: <code>{prob_continue:.3f}</code>
🔹 Edge: <code>{edge:.3f}</code>
{result_emoji} <b>Result:</b> {result_text}
📊 Today P&L: <code>${-TODAY_LOSS:.2f}</code>
📊 Consecutive Losses: {CONSECUTIVE_LOSSES}{pause_msg}"""
    
    return {'message': signal_msg + trade_msg, 'executed': True, 'direction': direction, 'position_size': position_size}

async def fetch_polymarket_market(window_ts):
    slug = construct_slug(window_ts)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(f"{GAMMA_API}/markets", params={"slug": slug})
        if resp.status_code == 200:
            data = resp.json()
            if data:
                m = data[0]
                yes_p, no_p = parse_outcome_prices(m.get("outcomePrices", '["0.5", "0.5"]'))
                return {
                    "id": m.get("id"),
                    "slug": m.get("slug"),
                    "question": m.get("question"),
                    "yes_price": yes_p,
                    "no_price": no_p,
                    "end_date": m.get("endDate"),
                    "volume": m.get("volume", 0)
                }
    return None

async def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            await http.post(url, json=payload)
            return True
    except:
        return False

def load_state():
    global CYCLE_COUNT, STATE_HISTORY, TRANSITION_MATRIX
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                data = json.load(f)
                CYCLE_COUNT = data.get('cycle_count', 0)
                STATE_HISTORY = data.get('history', [])
                TRANSITION_MATRIX = data.get('transition_matrix', {})
    except:
        pass

def save_state():
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'cycle_count': CYCLE_COUNT,
                'history': STATE_HISTORY[-100:],
                'transition_matrix': TRANSITION_MATRIX
            }, f)
    except:
        pass

def load_config():
    global MIN_PROB, MIN_EDGE
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                MIN_PROB = data.get('MIN_PROB', 0.82)
                MIN_EDGE = data.get('MIN_EDGE', 0.03)
    except:
        pass

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'MIN_PROB': MIN_PROB, 'MIN_EDGE': MIN_EDGE}, f)
    except:
        pass

async def run_trading_cycle():
    global BTC_KLINES, CYCLE_COUNT, STATE_HISTORY
    
    now = datetime.now(timezone.utc)
    current_window = get_current_window_ts()
    next_window = get_next_window_ts()
    
    # 1. Fetch candles
    count = await fetch_btc_klines()
    if count == 0:
        print("[BTC] No candles fetched")
        return None
    
    CYCLE_COUNT += 1
    directions = compute_directions(BTC_KLINES)
    streaks = compute_streaks(directions)
    
    # 2. Build Markov matrix with percentile filters
    filtered_count, num_states, atr_thresh, vol_thresh = build_filtered_matrix(directions, streaks, BTC_KLINES)
    
    # 3. Current state
    current_idx = len(BTC_KLINES) - 1
    current_state = get_markov_state(streaks, current_idx)
    current_atr = compute_atr(BTC_KLINES, current_idx)
    current_vol = get_volume(current_idx, BTC_KLINES)
    
    prob_continue, state_n = get_state(current_state)
    
    last_dir = directions[-1] if directions else 'UP'
    
    # 4. Market
    market = await fetch_polymarket_market(next_window)
    if market is None:
        print(f"[POLY] Market not found for {next_window}")
        return None
    
    # 5. Signal logic
    q = market['no_price'] if last_dir == 'UP' else market['yes_price']
    edge = prob_continue - q
    
    passes_atr = current_atr >= atr_thresh
    passes_vol = current_vol >= vol_thresh
    
    if not passes_atr:
        reason = f"Low ATR ({current_atr:.2f} < {atr_thresh:.2f})"
        signal_active = False
    elif not passes_vol:
        reason = f"Low Vol ({current_vol:.4f} < {vol_thresh:.4f})"
        signal_active = False
    elif prob_continue < MIN_PROB:
        reason = f"p̂ {prob_continue:.3f} < {MIN_PROB}"
        signal_active = False
    elif edge < MIN_EDGE:
        reason = f"Δ {edge:.3f} < {MIN_EDGE}"
        signal_active = False
    else:
        reason = "SIGNAL!"
        signal_active = True
    
    print(f"[SIGNAL] {last_dir}, p̂={prob_continue:.3f}, q={q:.3f}, Δ={edge:.3f} → {reason}")
    
    # 6. Telegram
    msg = f"""📊 <b>BTC 5m Cycle #{CYCLE_COUNT}</b>

🔹 State: <code>{current_state}</code> (n={state_n})
🔹 Last Dir: <b>{last_dir}</b>
🔹 p̂: <code>{prob_continue:.3f}</code>

📊 <b>Filters (Percentile):</b>
🔸 ATR: <code>{current_atr:.2f}</code> {'✅' if passes_atr else '❌'} (need &gt;{atr_thresh:.2f})
🔸 Vol: <code>{current_vol:.4f}</code> {'✅' if passes_vol else '❌'} (need &gt;{vol_thresh:.4f})

📈 <b>Market:</b> {market['question']}
🔹 YES: <code>{market['yes_price']:.3f}</code> / NO: <code>{market['no_price']:.3f}</code>

📐 <b>Signal:</b> q={q:.3f}, Δ={edge:.3f}
🔸 Result: <b>{last_dir if signal_active else 'NONE'}</b>
🔸 Reason: {reason}

⏰ <code>btc-updown-5m-{next_window}</code>"""

    if DRY_RUN:
        msg += "\n\n[DRY_RUN]"
    else:
        trade_result = await execute_live_trade(market, last_dir, prob_continue, edge, q, msg)
        msg = trade_result['message']
    
    await send_telegram(msg)
    
    # 7. Log
    STATE_HISTORY.append({
        'time': now.isoformat(),
        'cycle': CYCLE_COUNT,
        'state': current_state,
        'last_dir': last_dir,
        'prob_continue': prob_continue,
        'atr': current_atr,
        'vol': current_vol,
        'direction': last_dir,
        'edge': edge,
        'signal': signal_active,
        'reason': reason
    })
    
    save_state()
    
    return {'cycle': CYCLE_COUNT, 'state': current_state, 'prob': prob_continue, 'signal': signal_active}

async def main():
    global CYCLE_COUNT
    load_state()
    load_config()
    
    print(f"BTC 5m Bot - Percentile Filters")
    print(f"MIN_PROB={MIN_PROB}, MIN_EDGE={MIN_EDGE}")
    print(f"STATE_WINDOW={STATE_WINDOW} (capped)")
    print(f"STATE_FILE={STATE_FILE}")
    print(f"Cycle {CYCLE_COUNT}")
    
    result = await run_trading_cycle()
    
    if result:
        next_time = datetime.fromtimestamp(time.time() + CHECK_INTERVAL, tz=timezone.utc)
        print(f"\n✓ #{result['cycle']} p̂={result['prob']:.3f}, Signal={result['signal']}")
        print(f"⏰ Next: {next_time.strftime('%H:%M:%S')}")
    
    return result

if __name__ == "__main__":
    asyncio.run(main())