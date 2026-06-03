#!/usr/bin/env python3
"""
BTC 5m Polymarket Bot v3 - Markov + ATR/Vol Filter (DRY_RUN)
- State window: 3 candles (streak-based)
- ATR(14) > 1.2x avg(20) filter
- Volume > 1.5x avg filter
- Auto-adjust MIN_PROB after 50 cycles
"""

import time
import json
import sys
import asyncio
import urllib.request
import urllib.parse
import os
from datetime import datetime, timezone
from collections import Counter
import ssl

# Auto-load .env file (must come before any os.environ.get calls)
def _load_env_file(path='/home/node/.openclaw/workspace/.env'):
    """Simple .env loader - reads KEY=VALUE lines into os.environ"""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # Only set if not already in environment
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv('/home/node/.openclaw/workspace/.env')
except ImportError:
    _load_env_file()  # Fallback to manual loader

# === CONFIG ===
DRY_RUN = True  # SIGNAL ONLY - User trades manually
MIN_PROB = 0.50
MIN_EDGE = 0.015  # Lowered from 0.03 to capture more signals in low-vol
MAX_POSITION = 5.0  # Max $5 per trade
MAX_DAILY_LOSS = 30.0  # Max $30 daily loss
CHECK_INTERVAL = 81
TARGET_CYCLES = 50
STATE_WINDOW = 4
ATR_MULT = 0.8
VOL_MULT = 0.6

# === DYNAMIC ADJUSTMENT ===
DYNAMIC_MODE = True  # Auto-relax filters when no signals
LAST_SIGNAL_TIME = datetime.now(timezone.utc)  # Initialize to start time so relax works from start
SIGNAL_FREE_MIN_THRESHOLD = 30  # Start relaxing after 30 min no signal
RELAX_STEP_MIN = 15  # Adjust every 15 min
MIN_PROB_FLOOR = 0.42  # Don't go below this
ATR_MULT_FLOOR = 0.4  # Don't go below this
VOL_MULT_FLOOR = 0.3  # Don't go below this
PROB_RELAX_AMOUNT = 0.02  # Lower MIN_PROB by this per step
MULT_RELAX_AMOUNT = 0.05  # Lower ATR/VOL_MULT by this per step

TELEGRAM_TOKEN = "8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY"
TELEGRAM_CHAT_ID = "8475453959"
GAMMA_API = "https://gamma-api.polymarket.com"

# State
# State files for persistence across script restarts
STATE_FILE = '/tmp/btc_5m_state.json'
CONFIG_FILE = '/tmp/btc_5m_config.json'
RELAX_FILE = '/tmp/btc_5m_relax.json'  # Persist relax state across restarts
BTC_KLINES = []
TRANSITION_MATRIX = {}
STATE_HISTORY = []
CYCLE_COUNT = 0
CONSECUTIVE_LOSSES = 0
TODAY_LOSS = 0.0
LAST_TRADE_DATE = None
PAUSED_TODAY = False

# Files
STATE_FILE = "/home/node/.openclaw/workspace/btc_5m_state_v3.json"
CONFIG_FILE = "/home/node/.openclaw/workspace/btc_5m_config_v3.json"

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

async def fetch_btc_klines():
    """Fetch BTC 5m candles from OKX"""
    global BTC_KLINES
    try:
        all_candles = []
        url_template = 'https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=200&after={}'
        after = None

        for page in range(8):
            url = url_template.format(after) if after else url_template.format('')
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode())
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

def get_avg_atr(klines, period=14, lookback=20):
    """Get average ATR over last N periods"""
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
    """Build Markov matrix with ATR and volume filters"""
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

async def execute_live_trade(market, direction, prob_continue, edge, q, signal_msg):
    """Execute live trade with real money via PolyClaw L2 Client"""
    global CONSECUTIVE_LOSSES, TODAY_LOSS, LAST_TRADE_DATE, PAUSED_TODAY

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Reset daily loss if new day
    if LAST_TRADE_DATE != today:
        TODAY_LOSS = 0.0
        CONSECUTIVE_LOSSES = 0
        LAST_TRADE_DATE = today
        PAUSED_TODAY = False

    # Check pause conditions
    if PAUSED_TODAY:
        return {
            'message': signal_msg + "\n\n⛸️ TRADING PAUSED TODAY (loss limit reached)",
            'executed': False,
            'reason': 'paused'
        }

    # Check daily loss limit
    if TODAY_LOSS >= MAX_DAILY_LOSS:
        PAUSED_TODAY = True
        return {
            'message': signal_msg + f"\n\n🚫 DAILY LOSS LIMIT REACHED (${TODAY_LOSS:.2f} >= ${MAX_DAILY_LOSS:.2f})\nTrading paused for today.",
            'executed': False,
            'reason': 'daily_limit'
        }

    # Use minimum of MAX_POSITION or $1 for test
    position_size = min(MAX_POSITION, 1.0)  # $1 test trade

    # Prepare trade info
    if direction == 'UP':
        outcome = 'YES'
        entry_price = market['yes_price']
    else:
        outcome = 'NO'
        entry_price = market['no_price']

    # Execute real trade via PolyClaw L2
    try:
        from py_clob_client_v2 import ClobClient, SignatureTypeV2
        from py_clob_client_v2.order_builder.constants import BUY, SELL
        from py_clob_client_v2 import OrderArgs, PartialCreateOrderOptions

        private_key = os.environ.get('POLYCLAW_PRIVATE_KEY', '')
        funder = os.environ.get('RELAYER_API_KEY_ADDRESS', '')

        if not private_key or not funder:
            raise Exception('Missing POLYCLAW_PRIVATE_KEY or RELAYER_API_KEY_ADDRESS')

        # Create L2 client with POLY_1271 signature
        temp_client = ClobClient(
            host='https://clob.polymarket.com',
            key=private_key,
            chain_id=137
        )
        api_creds = temp_client.create_or_derive_api_key()

        client = ClobClient(
            host='https://clob.polymarket.com',
            key=private_key,
            chain_id=137,
            creds=api_creds,
            signature_type=SignatureTypeV2.POLY_1271,
            funder=funder
        )

        # Get token ID from market
        token_id = market.get('tokens', [None])[0] if market.get('tokens') else None
        if not token_id:
            raise Exception('No token_id in market')

        # Place order
        side = BUY if direction == 'UP' else SELL

        # Size = position_size / price (rough approximation)
        size = position_size / entry_price

        response = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=entry_price,
                size=size,
                side=side,
            ),
            options=PartialCreateOrderOptions(
                tick_size='0.01',
                neg_risk=False,
            ),
        )

        if response.get('orderID'):
            pnl = 0  # Unresolved
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

    # Check consecutive losses
    if CONSECUTIVE_LOSSES >= 3:
        PAUSED_TODAY = True
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

    return {
        'message': signal_msg + trade_msg,
        'executed': True,
        'direction': direction,
        'position_size': position_size
    }

async def fetch_polymarket_market(window_ts):
    slug = construct_slug(window_ts)
    url = f"{GAMMA_API}/markets?slug={urllib.parse.quote(slug)}"
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
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
    except:
        pass
    return None

async def send_telegram(message, alert=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    if alert:
        # Disable silent notification, ring phone
        payload["disable_notification"] = False
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
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

TRADES_LOG = '/tmp/btc_5m_trades.jsonl'  # Persistent trade log
STATS_FILE = '/tmp/btc_5m_stats.json'   # Cumulative stats

def log_pending_trade(market, direction, prob_continue, edge, position_size):
    """Log a pending trade to the trades file"""
    try:
        trade = {
            'id': f"{market.get('slug', 'unknown')}_{int(time.time())}",
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'slug': market.get('slug', ''),
            'direction': direction,
            'state': STATE_HISTORY[-1].get('state', '') if STATE_HISTORY else '',
            'p_hat': round(prob_continue, 3),
            'edge': round(edge, 3),
            'position_size': position_size,
            'status': 'pending'
        }
        with open(TRADES_LOG, 'a') as f:
            f.write(json.dumps(trade) + '\n')
        print(f"[TRADE] Logged: {trade['id']} {direction} p̂={prob_continue:.3f} size=${position_size:.2f}")
    except Exception as e:
        print(f"[TRADE] Log error: {e}")

async def fetch_market_by_slug(slug):
    """Fetch market data by slug, return outcome prices"""
    try:
        url = f"{GAMMA_API}/markets?slug={slug}"
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())
        if data and len(data) > 0:
            market = data[0]
            tokens_str = market.get('clobTokenIds', '[]')
            tokens = json.loads(tokens_str) if isinstance(tokens_str, str) else tokens_str
            outcome_prices = market.get('outcomePrices', '[]')
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            return {
                'slug': slug,
                'closed': market.get('closed', False),
                'yes_price': float(prices[0]) if len(prices) > 0 else 0.5,
                'no_price': float(prices[1]) if len(prices) > 1 else 0.5,
                'tokens': tokens,
            }
    except Exception as e:
        return None
    return None

async def settle_pending_trades_async():
    """Check pending trades and mark WIN/LOSS based on actual market result.
    Returns dict with settled/win/loss counts."""
    if not os.path.exists(TRADES_LOG):
        return None

    try:
        trades = []
        with open(TRADES_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))

        now_ts = time.time()
        settled = 0
        wins = 0
        losses = 0
        new_pending = 0

        for t in trades:
            if t['status'] == 'pending':
                trade_time = datetime.fromisoformat(t['timestamp']).timestamp()
                if now_ts > trade_time + 300:  # 5 min passed, market should be settled
                    # Fetch actual market result
                    market = await fetch_market_by_slug(t['slug'])
                    if market and market.get('closed'):
                        # Determine winner
                        # If YES price is 1.0 (or close), UP won
                        # If NO price is 1.0 (or close), DOWN won
                        yes_p = market.get('yes_price', 0.5)
                        no_p = market.get('no_price', 0.5)
                        if yes_p > 0.95:
                            actual_dir = 'UP'
                        elif no_p > 0.95:
                            actual_dir = 'DOWN'
                        else:
                            actual_dir = 'UNKNOWN'
                        if actual_dir == 'UNKNOWN':
                            continue  # skip for now
                        t['result'] = 'WIN' if t['direction'] == actual_dir else 'LOSS'
                        # P&L (binary R:R 1:2, $0.495 win, $0.505 loss per $1)
                        if t['result'] == 'WIN':
                            t['pnl'] = 0.495 * t['position_size']
                            wins += 1
                        else:
                            t['pnl'] = -0.505 * t['position_size']
                            losses += 1
                        t['status'] = 'settled'
                        t['settled_at'] = datetime.now(timezone.utc).isoformat()
                        t['actual_dir'] = actual_dir
                        t['final_yes'] = yes_p
                        t['final_no'] = no_p
                        settled += 1
                        print(f"[SETTLE] {t['id']}: {t['direction']} vs actual {actual_dir} → {t['result']} (P&L ${t['pnl']:+.2f})")
                    else:
                        new_pending += 1
                else:
                    new_pending += 1

        if settled > 0:
            with open(TRADES_LOG, 'w') as f:
                for t in trades:
                    f.write(json.dumps(t) + '\n')
            print(f"[SETTLE] {settled} trades settled ({wins}W / {losses}L), {new_pending} still pending")

        return {'total': len(trades), 'settled': settled, 'wins': wins, 'losses': losses, 'pending': new_pending}
    except Exception as e:
        print(f"[SETTLE] Error: {e}")
        return None

def settle_pending_trades():
    """Sync wrapper for backward compat"""
    return None  # Use settle_pending_trades_async instead

def get_cumulative_stats():
    """Get cumulative win rate, P&L, by direction"""
    if not os.path.exists(TRADES_LOG):
        return None

    try:
        trades = []
        with open(TRADES_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))

        # Filter settled trades with result
        completed = [t for t in trades if t.get('result') in ('WIN', 'LOSS')]
        if not completed:
            return {'total': len(trades), 'completed': 0, 'pending': len([t for t in trades if t['status']=='pending'])}

        wins = sum(1 for t in completed if t['result'] == 'WIN')
        losses = len(completed) - wins
        wr = wins / len(completed) * 100
        pnl = sum(t.get('pnl', 0) for t in completed)

        up_trades = [t for t in completed if t['direction'] == 'UP']
        down_trades = [t for t in completed if t['direction'] == 'DOWN']

        stats = {
            'total_logged': len(trades),
            'completed': len(completed),
            'pending': len([t for t in trades if t['status']=='pending']),
            'wins': wins,
            'losses': losses,
            'wr': wr,
            'pnl': pnl,
            'up_count': len(up_trades),
            'up_wr': sum(1 for t in up_trades if t['result']=='WIN')/len(up_trades)*100 if up_trades else 0,
            'down_count': len(down_trades),
            'down_wr': sum(1 for t in down_trades if t['result']=='WIN')/len(down_trades)*100 if down_trades else 0,
        }

        # Save to stats file
        with open(STATS_FILE, 'w') as f:
            json.dump(stats, f, indent=2)

        return stats
    except Exception as e:
        print(f"[STATS] Error: {e}")
        return None

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
                MIN_PROB = data.get('MIN_PROB', 0.50)
                MIN_EDGE = data.get('MIN_EDGE', 0.03)
    except:
        pass

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'MIN_PROB': MIN_PROB, 'MIN_EDGE': MIN_EDGE}, f, indent=2)
    except:
        pass

def dynamic_relax_filters():
    """If no signals for a while, gradually relax thresholds.
    State is persisted to disk to survive bash loop restarts."""
    global MIN_PROB, ATR_MULT, VOL_MULT, LAST_SIGNAL_TIME

    if not DYNAMIC_MODE:
        return None

    # Load persisted state (last signal time, accumulated no-signal minutes)
    state = {}
    try:
        if os.path.exists(RELAX_FILE):
            with open(RELAX_FILE) as f:
                state = json.load(f)
    except:
        pass

    no_signal_min = state.get('no_signal_min', 0)
    last_signal_iso = state.get('last_signal_time')
    if last_signal_iso:
        try:
            LAST_SIGNAL_TIME = datetime.fromisoformat(last_signal_iso)
        except:
            pass

    # If we just had a signal (within 30 min), no relax needed
    if last_signal_iso:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_signal_iso)).total_seconds() / 60
            if elapsed < SIGNAL_FREE_MIN_THRESHOLD:
                # Reset accumulator
                state['no_signal_min'] = 0
                try:
                    with open(RELAX_FILE, 'w') as f:
                        json.dump(state, f)
                except:
                    pass
                return None
            no_signal_min = elapsed
        except:
            pass

    # Increment by 81s (one cycle) and persist
    no_signal_min = max(no_signal_min, 0) + 81.0 / 60.0
    state['no_signal_min'] = no_signal_min
    state['last_signal_time'] = datetime.now(timezone.utc).isoformat() if LAST_SIGNAL_TIME is None else state.get('last_signal_time')
    try:
        with open(RELAX_FILE, 'w') as f:
            json.dump(state, f)
    except:
        pass

    if no_signal_min < SIGNAL_FREE_MIN_THRESHOLD:
        return None

    # Calculate relaxation steps (one per RELAX_STEP_MIN)
    steps = int(no_signal_min / RELAX_STEP_MIN)

    # Relax from initial config values, not from current (cumulative)
    old_min_prob = MIN_PROB
    old_atr_mult = ATR_MULT
    old_vol_mult = VOL_MULT

    MIN_PROB = max(MIN_PROB_FLOOR, 0.50 - PROB_RELAX_AMOUNT * steps)
    ATR_MULT = max(ATR_MULT_FLOOR, 0.80 - MULT_RELAX_AMOUNT * steps)
    VOL_MULT = max(VOL_MULT_FLOOR, 0.60 - MULT_RELAX_AMOUNT * steps)

    if (MIN_PROB != old_min_prob or ATR_MULT != old_atr_mult or VOL_MULT != old_vol_mult):
        return {
            'elapsed_min': no_signal_min,
            'steps': steps,
            'old_min_prob': old_min_prob,
            'new_min_prob': MIN_PROB,
            'old_atr_mult': old_atr_mult,
            'new_atr_mult': ATR_MULT,
            'old_vol_mult': old_vol_mult,
            'new_vol_mult': VOL_MULT,
        }
    return None

async def run_trading_cycle():
    global STATE_HISTORY, CYCLE_COUNT, LAST_SIGNAL_TIME

    load_state()
    load_config()

    # Check and settle pending trades from previous signals
    settle_result = await settle_pending_trades_async()
    if settle_result and settle_result.get('settled', 0) > 0:
        print(f"[SETTLE] Settled {settle_result['settled']} trades, {settle_result['pending']} pending")

    # Print cumulative stats every 10 cycles
    if CYCLE_COUNT % 10 == 0:
        stats = get_cumulative_stats()
        if stats and stats.get('completed', 0) > 0:
            print(f"\n📊 CUMULATIVE STATS:")
            print(f"   Total: {stats['total_logged']} logged, {stats['completed']} completed, {stats['pending']} pending")
            print(f"   WR: {stats['wr']:.1f}% ({stats['wins']}W / {stats['losses']}L)")
            print(f"   P&L: ${stats['pnl']:+.2f}")
            print(f"   UP:   {stats['up_count']} signals, {stats['up_wr']:.1f}% WR")
            print(f"   DOWN: {stats['down_count']} signals, {stats['down_wr']:.1f}% WR\n")

    # Dynamic relax - if no signals for a while, lower thresholds
    relax_info = dynamic_relax_filters()
    if relax_info:
        print(f"🔧 DYNAMIC RELAX: {relax_info['elapsed_min']:.0f}min no signal → "
              f"MIN_PROB {relax_info['old_min_prob']:.2f}→{relax_info['new_min_prob']:.2f}, "
              f"ATR_MULT {relax_info['old_atr_mult']:.2f}→{relax_info['new_atr_mult']:.2f}, "
              f"VOL_MULT {relax_info['old_vol_mult']:.2f}→{relax_info['new_vol_mult']:.2f}")

    next_window = get_next_window_ts()
    now = datetime.now(timezone.utc)
    CYCLE_COUNT += 1

    print(f"\n{'='*60}")
    print(f"Cycle #{CYCLE_COUNT} | {now.strftime('%H:%M:%S')} UTC")

    # 1. Fetch BTC
    btc_count = await fetch_btc_klines()
    print(f"[BTC] {btc_count} candles")

    if btc_count < 100:
        return None

    # 2. Compute indicators
    directions = compute_directions(BTC_KLINES)
    streaks = compute_streaks(directions)

    atr_avg = get_avg_atr(BTC_KLINES)
    vol_avg = get_avg_vol(BTC_KLINES)
    current_atr = compute_atr(BTC_KLINES, len(BTC_KLINES) - 1)
    current_vol = get_volume(len(BTC_KLINES) - 1, BTC_KLINES)

    print(f"[FILTER] ATR={current_atr:.2f} (avg={atr_avg:.2f}, threshold={atr_avg*ATR_MULT:.2f})")
    print(f"[FILTER] Vol={current_vol:.4f} (avg={vol_avg:.4f}, threshold={vol_avg*VOL_MULT:.4f})")
    print(f"[BTC] Last streaks: {streaks[-5:]}")

    # 3. Build filtered matrix
    filtered_count, state_count = build_filtered_matrix(directions, streaks, BTC_KLINES, atr_avg, vol_avg)
    print(f"[MARKOV] Filtered={filtered_count} candles, {state_count} states")

    # 4. Get current state
    state = ''.join(str(s) for s in streaks[-STATE_WINDOW:]) if len(streaks) >= STATE_WINDOW else None
    last_dir = directions[-1] if directions else 'UNKNOWN'

    prob_continue, state_n = get_state(state)

    print(f"[MARKOV] State={state}, last_dir={last_dir}, p̂={prob_continue:.3f} (n={state_n})")

    # 5. Fetch Polymarket
    market = await fetch_polymarket_market(next_window)
    if not market:
        print("[POLY] No market")
        return None

    print(f"[POLY] YES={market['yes_price']:.3f}, NO={market['no_price']:.3f}")

    # 6. Signal check
    direction = last_dir
    q = market['no_price'] if direction == 'UP' else market['yes_price']
    edge = prob_continue - q

    # Filters
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
        LAST_SIGNAL_TIME = datetime.now(timezone.utc)  # Track for dynamic relax
        # Persist to relax state file
        try:
            state = {}
            if os.path.exists(RELAX_FILE):
                with open(RELAX_FILE) as f:
                    state = json.load(f)
            state['last_signal_time'] = LAST_SIGNAL_TIME.isoformat()
            state['no_signal_min'] = 0  # Reset accumulator
            with open(RELAX_FILE, 'w') as f:
                json.dump(state, f)
        except:
            pass

    print(f"[SIGNAL] {direction}, p̂={prob_continue:.3f}, q={q:.3f}, Δ={edge:.3f} → {reason}")

    # 7. Telegram
    if signal_active:
        # High-priority alert format
        msg = f"""🚨🚨🚨 <b>SIGNAL NOW!</b> 🚨🚨🚨

📊 <b>BTC 5m Cycle #{CYCLE_COUNT}</b>

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

    if DRY_RUN and signal_active:
        # Manual trading mode - clear actionable signal
        # Determine outcome and entry price
        if direction == 'UP':
            outcome = 'YES'
            entry_price = market['yes_price']
            # UP signals historically less accurate (47.9% WR) - half size
            position_size = min(MAX_POSITION, 0.50)  # $0.50 base
        else:
            outcome = 'NO'
            entry_price = market['no_price']
            # DOWN signals more accurate (60.3% WR) - bigger size
            position_size = min(MAX_POSITION, 1.50)  # $1.50 base

        msg += f"\n\n📱 <b>MANUAL TRADE</b>"
        msg += f"\n🔹 <b>Action: Buy {outcome} @ {entry_price:.3f}</b>"
        msg += f"\n🔹 Sizing: ${position_size:.2f}"
        msg += f"\n🔹 Market ends: ~5 min"
        msg += f"\n🔹 Target: Win → ${entry_price:.3f}→$1.00 = +${1-entry_price:.3f}"
        msg += f"\n🔹 Risk: Lose → -${entry_price:.3f}"
        msg += f"\n🔹 R:R: 1:{((1-entry_price)/entry_price):.2f}"
        msg += f"\n\n⏰ <code>{market.get('slug', 'btc-updown-5m')}</code>"
    elif not DRY_RUN and signal_active:
        # LIVE TRADING - execute if signal active
        trade_result = await execute_live_trade(market, direction, prob_continue, edge, q, msg)
        msg = trade_result['message']

    if signal_active:
        await send_telegram(msg, alert=True)  # Ring phone on signal!
        # Log signal to trades file for settlement tracking
        await log_pending_trade(market, direction, prob_continue, edge, position_size)
    else:
        print(f"[SIGNAL] {direction}, p̂={prob_continue:.3f}, q={q:.3f}, Δ={edge:.3f} → {reason} (no alert)")

    # 8. Log
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

    # 9. Auto-adjust at 50 cycles
    if CYCLE_COUNT > 0 and CYCLE_COUNT % TARGET_CYCLES == 0:
        await nightly_review()

    return {'cycle': CYCLE_COUNT, 'state': state, 'prob': prob_continue, 'signal': signal_active}

async def nightly_review():
    global MIN_PROB, STATE_HISTORY

    # === 50-Cycle Dynamic Auto-Adjust ===
    print(f"\n🔄 50-CYCLE AUTO-ADJUST after {len(STATE_HISTORY)} cycles")

    # 1. Stats on recent cycles
    recent = STATE_HISTORY[-TARGET_CYCLES:]
    probs = [e.get('prob_continue', 0) for e in recent]
    max_prob = max(probs) if probs else 0
    avg_prob = sum(probs) / len(probs) if probs else 0

    # 2. Signal rate
    signal_count = sum(1 for e in recent if e.get('signal'))
    signal_rate = signal_count / len(recent) if recent else 0

    # 3. Filter reasons (what's blocking signals)
    reasons = {}
    for e in recent:
        if not e.get('signal'):
            r = e.get('reason', 'Unknown')
            reasons[r] = reasons.get(r, 0) + 1

    print(f"[ADJUST] p̂ max={max_prob:.3f} avg={avg_prob:.3f} signal_rate={signal_rate*100:.1f}%")
    print(f"[ADJUST] Blocked by: {reasons}")

    old_prob = MIN_PROB
    adjustment_reason = ""

    # === ADJUSTMENT RULES ===

    # Rule 1: If max p̂ is very low vs current threshold, lower it
    if max_prob < MIN_PROB * 0.7:
        new_prob = max(0.45, MIN_PROB - 0.03)
        if new_prob < MIN_PROB:
            MIN_PROB = new_prob
            adjustment_reason = f"max p̂ {max_prob:.3f} too low, lower to {MIN_PROB:.2f}"

    # Rule 2: If signal rate is too high (>30%), raise threshold
    elif signal_rate > 0.30:
        new_prob = min(0.75, MIN_PROB + 0.02)
        if new_prob > MIN_PROB:
            MIN_PROB = new_prob
            adjustment_reason = f"signal rate {signal_rate*100:.1f}% too high, raise to {MIN_PROB:.2f}"

    # Rule 3: If max p̂ is well above threshold AND signal rate is low, can lower
    elif max_prob > MIN_PROB * 1.3 and signal_rate < 0.10:
        new_prob = max(0.45, MIN_PROB - 0.02)
        if new_prob < MIN_PROB:
            MIN_PROB = new_prob
            adjustment_reason = f"max p̂ {max_prob:.3f} high, signal rate low, lower to {MIN_PROB:.2f}"

    # Rule 4: If no signals at all, lower more aggressively
    elif signal_count == 0 and len(recent) >= 30:
        new_prob = max(0.45, MIN_PROB - 0.05)
        if new_prob < MIN_PROB:
            MIN_PROB = new_prob
            adjustment_reason = f"0 signals in 50 cycles, lower to {MIN_PROB:.2f}"

    if adjustment_reason:
        print(f"[ADJUST] {old_prob:.2f} → {MIN_PROB:.2f} ({adjustment_reason})")
        save_config()
    else:
        print(f"[ADJUST] No change needed, MIN_PROB={MIN_PROB:.2f}")

    msg = f"""🔄 <b>50-Cycle Auto-Adjust</b>

📊 Cycles: {len(recent)}
📈 p̂ max: {max_prob:.3f} avg: {avg_prob:.3f}
🎯 Signal rate: {signal_rate*100:.1f}% ({signal_count}/{len(recent)})
🔧 MIN_PROB: {old_prob:.2f} → {MIN_PROB:.2f}
{f"📝 {adjustment_reason}" if adjustment_reason else "✅ No change"}

Top block reasons:
{chr(10).join(f"  • {k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:3])}"""

    await send_telegram(msg, alert=True)  # Daily summary also alerts

    STATE_HISTORY = []
    save_state()

async def main():
    global CYCLE_COUNT
    load_state()
    load_config()

    print("BTC 5m Bot v3 - ATR+Vol Filter")
    print(f"MIN_PROB={MIN_PROB}, ATR>{ATR_MULT}x avg, Vol>{VOL_MULT}x avg")
    print(f"Cycle {CYCLE_COUNT}/{TARGET_CYCLES}")

    result = await run_trading_cycle()

    if result:
        next_time = datetime.fromtimestamp(time.time() + CHECK_INTERVAL, tz=timezone.utc)
        print(f"\n✓ #{result['cycle']} p̂={result['prob']:.3f}, Signal={result['signal']}")
        print(f"⏰ Next: {next_time.strftime('%H:%M:%S')}")

    return result

if __name__ == "__main__":
    asyncio.run(main())