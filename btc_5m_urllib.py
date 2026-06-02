#!/usr/bin/env python3
"""
BTC 5m Polymarket Bot v3 - urllib port
"""
import time, json, sys, os
from datetime import datetime, timezone
from collections import Counter
from urllib.request import urlopen, Request
from urllib.error import URLError

DRY_RUN = False
MIN_PROB = 0.87
MIN_EDGE = 0.03
MAX_POSITION = 5.0
MAX_DAILY_LOSS = 30.0
CHECK_INTERVAL = 81
TARGET_CYCLES = 50
STATE_WINDOW = 4
ATR_MULT = 0.8
VOL_MULT = 0.6

TELEGRAM_TOKEN = "8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY"
TELEGRAM_CHAT_ID = "8475453959"
GAMMA_API = "https://gamma-api.polymarket.com"

BTC_KLINES = []
TRANSITION_MATRIX = {}
STATE_HISTORY = []
CYCLE_COUNT = 0
CONSECUTIVE_LOSSES = 0
TODAY_LOSS = 0.0
LAST_TRADE_DATE = None
PAUSED_TODAY = False

STATE_FILE = "/home/node/.openclaw/workspace/btc_5m_state_v3.json"
CONFIG_FILE = "/home/node/.openclaw/workspace/btc_5m_config_v3.json"

def get_current_window_ts():
    return (int(time.time()) // 300) * 300

def get_next_window_ts():
    return get_current_window_ts() + 300

def construct_slug(window_ts):
    return f"btc-updown-5m-{window_ts}"

def http_get(url, timeout=15):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def fetch_btc_klines():
    global BTC_KLINES
    try:
        all_candles = []
        url_template = 'https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=200&after={}'
        after = None
        for page in range(8):
            url = url_template.format(after) if after else url_template.format('')
            data = http_get(url)
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
    streaks = []
    current_streak = 1
    for i, d in enumerate(directions):
        if i == 0:
            streaks.append(1)
        elif directions[i-1] == d:
            current_streak += 1
            streaks.append(current_streak)
        else:
            current_streak = 1
            streaks.append(current_streak)
    return streaks

def compute_atr(klines, index, period=14):
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

def get_avg_atr(klines, period=14, lookback=20):
    atrs = []
    for i in range(period, len(klines)):
        atr = compute_atr(klines, i, period)
        if atr > 0:
            atrs.append(atr)
    if len(atrs) < lookback:
        return sum(atrs) / len(atrs) if atrs else 50
    return sum(atrs[-lookback:]) / lookback

def get_volume(index, klines):
    if index < 0 or index >= len(klines):
        return 0
    return float(klines[index][5])

def get_avg_vol(klines, lookback=20):
    vols = [float(k[5]) for k in klines[-lookback:]]
    return sum(vols) / len(vols) if vols else 1

def build_filtered_matrix(directions, streaks, klines, atr_avg, vol_avg):
    global TRANSITION_MATRIX
    filtered_indices = []
    for i in range(STATE_WINDOW, len(klines) - 1):
        atr = compute_atr(klines, i)
        vol = get_volume(i, klines)
        if atr > atr_avg * ATR_MULT and vol > vol_avg * VOL_MULT:
            filtered_indices.append(i)
    transitions = {}
    for i in filtered_indices:
        state = ''.join(str(s) for s in streaks[i-STATE_WINDOW:i])
        next_dir = directions[i + 1]
        if state not in transitions:
            transitions[state] = {'UP': 0, 'DOWN': 0}
        transitions[state][next_dir] += 1
    TRANSITION_MATRIX = {}
    for state, counts in transitions.items():
        total = counts['UP'] + counts['DOWN']
        if total > 0:
            TRANSITION_MATRIX[state] = {
                'UP': counts['UP'] / total,
                'DOWN': counts['DOWN'] / total,
                'total': total
            }
    return len(filtered_indices), len(TRANSITION_MATRIX)

def get_state(state):
    if state is None or state not in TRANSITION_MATRIX:
        return 0.5, 0
    m = TRANSITION_MATRIX[state]
    last_char = state[-1]
    last_dir = 'UP' if last_char == '1' else 'DOWN'
    key = 'UP' if last_dir == 'UP' else 'DOWN'
    return m.get(key, 0.5), m.get('total', 0)

def fetch_polymarket_market(window_ts):
    slug = construct_slug(window_ts)
    try:
        data = http_get(f"{GAMMA_API}/markets?slug={slug}", timeout=30)
        if data:
            m = data[0]
            try:
                prices = json.loads(m.get("outcomePrices", '["0.5", "0.5"]'))
                yes_p, no_p = float(prices[0]), float(prices[1])
            except:
                yes_p, no_p = 0.5, 0.5
            return {
                "id": m.get("id"),
                "slug": m.get("slug"),
                "question": m.get("question"),
                "yes_price": yes_p,
                "no_price": no_p,
                "end_date": m.get("endDate"),
                "volume": m.get("volume", 0)
            }
    except Exception as e:
        print(f"[POLY] Error: {e}")
    return None

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}).encode()
    req = Request(url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except:
        return False

def load_state():
    global CYCLE_COUNT, STATE_HISTORY
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                data = json.load(f)
                CYCLE_COUNT = data.get('cycle_count', 0)
                STATE_HISTORY = data.get('history', [])
    except:
        pass

def save_state():
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({'cycle_count': CYCLE_COUNT, 'history': STATE_HISTORY[-100:]}, f)
    except:
        pass

def load_config():
    global MIN_PROB, MIN_EDGE
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                MIN_PROB = data.get('MIN_PROB', 0.87)
                MIN_EDGE = data.get('MIN_EDGE', 0.03)
    except:
        pass

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'MIN_PROB': MIN_PROB, 'MIN_EDGE': MIN_EDGE}, f, indent=2)
    except:
        pass

def run_trading_cycle():
    global STATE_HISTORY, CYCLE_COUNT
    load_state()
    load_config()
    
    next_window = get_next_window_ts()
    now = datetime.now(timezone.utc)
    CYCLE_COUNT += 1
    
    print(f"\n{'='*60}")
    print(f"Cycle #{CYCLE_COUNT} | {now.strftime('%H:%M:%S')} UTC")
    
    btc_count = fetch_btc_klines()
    print(f"[BTC] {btc_count} candles")
    
    if btc_count < 100:
        return None
    
    directions = compute_directions(BTC_KLINES)
    streaks = compute_streaks(directions)
    
    atr_avg = get_avg_atr(BTC_KLINES)
    vol_avg = get_avg_vol(BTC_KLINES)
    current_atr = compute_atr(BTC_KLINES, len(BTC_KLINES) - 1)
    current_vol = get_volume(len(BTC_KLINES) - 1, BTC_KLINES)
    
    print(f"[FILTER] ATR={current_atr:.2f} (avg={atr_avg:.2f}, threshold={atr_avg*ATR_MULT:.2f})")
    print(f"[FILTER] Vol={current_vol:.4f} (avg={vol_avg:.4f}, threshold={vol_avg*VOL_MULT:.4f})")
    print(f"[BTC] Last streaks: {streaks[-5:]}")
    
    filtered_count, state_count = build_filtered_matrix(directions, streaks, BTC_KLINES, atr_avg, vol_avg)
    print(f"[MARKOV] Filtered={filtered_count} candles, {state_count} states")
    
    state = ''.join(str(s) for s in streaks[-STATE_WINDOW:]) if len(streaks) >= STATE_WINDOW else None
    last_dir = directions[-1] if directions else 'UNKNOWN'
    
    prob_continue, state_n = get_state(state)
    
    print(f"[MARKOV] State={state}, last_dir={last_dir}, p̂={prob_continue:.3f} (n={state_n})")
    
    market = fetch_polymarket_market(next_window)
    if not market:
        print("[POLY] No market")
        return None
    
    print(f"[POLY] YES={market['yes_price']:.3f}, NO={market['no_price']:.3f}")
    
    direction = last_dir
    q = market['no_price'] if direction == 'UP' else market['yes_price']
    edge = prob_continue - q
    
    passes_vol = current_vol > vol_avg * VOL_MULT
    passes_atr = current_atr > atr_avg * ATR_MULT
    
    if not passes_atr:
        reason = f"Low ATR ({current_atr:.2f} < {atr_avg*ATR_MULT:.2f})"
        signal_active = False
    elif not passes_vol:
        reason = f"Low Vol ({current_vol:.4f} < {vol_avg*VOL_MULT:.4f})"
        signal_active = False
    elif prob_continue < MIN_PROB:
        reason = f"p̂ {prob_continue:.3f} < {MIN_PROB}"
        signal_active = False
    elif edge < MIN_EDGE:
        reason = f"Δ {edge:.3f} < {MIN_EDGE}"
        signal_active = False
    else:
        reason = "OK"
        signal_active = True
    
    print(f"[SIGNAL] {direction}, p̂={prob_continue:.3f}, q={q:.3f}, Δ={edge:.3f} → {reason}")
    
    msg = f"""📊 <b>BTC 5m Cycle #{CYCLE_COUNT}</b>

🔹 State: <code>{state}</code> (n={state_n})
🔹 Last Dir: <b>{last_dir}</b>
🔹 p̂: <code>{prob_continue:.3f}</code>

📊 <b>Filters:</b>
🔸 ATR: <code>{current_atr:.2f}</code> {'✅' if passes_atr else '❌'} (need &gt;{atr_avg*ATR_MULT:.2f})
🔸 Vol: <code>{current_vol:.4f}</code> {'✅' if passes_vol else '❌'} (need &gt;{vol_avg*VOL_MULT:.4f})

📈 <b>Market:</b> {market['question']}
🔹 YES: <code>{market['yes_price']:.3f}</code> / NO: <code>{market['no_price']:.3f}</code>

📐 <b>Signal:</b> q={q:.3f}, Δ={edge:.3f}
🔸 Result: <b>{direction if signal_active else 'NONE'}</b>
🔸 Reason: {reason}

⏰ <code>btc-updown-5m-{next_window}</code>"""

    if DRY_RUN:
        msg += "\n\n[DRY_RUN]"
    
    send_telegram(msg)
    
    STATE_HISTORY.append({
        'time': now.isoformat(),
        'cycle': CYCLE_COUNT,
        'state': state,
        'last_dir': last_dir,
        'prob_continue': prob_continue,
        'atr': current_atr,
        'vol': current_vol,
        'direction': direction,
        'edge': edge,
        'signal': signal_active,
        'reason': reason
    })
    
    save_state()
    
    return {'cycle': CYCLE_COUNT, 'state': state, 'prob': prob_continue, 'signal': signal_active}

if __name__ == "__main__":
    load_state()
    load_config()
    print("BTC 5m Bot v3 - urllib port")
    print(f"MIN_PROB={MIN_PROB}, ATR>{ATR_MULT}x avg, Vol>{VOL_MULT}x avg")
    result = run_trading_cycle()
    if result:
        print(f"\n✓ #{result['cycle']} p̂={result['prob']:.3f}, Signal={result['signal']}")
