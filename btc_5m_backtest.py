#!/usr/bin/env python3
"""
BTC 5m Backtest - 5 Days
Using urllib (no extra dependencies)
"""

import json
import urllib.request
from datetime import datetime, timedelta

# Config
MIN_PROB = 0.87
STATE_WINDOW = 4

def get_btc_data():
    """Fetch BTC last 5 days minute data from Yahoo"""
    now = datetime.now()
    start = int((now - timedelta(days=5)).timestamp())
    end = int(now.timestamp())
    
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1={start}&period2={end}&interval=5m'
    
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        quotes = result['indicators']['quote'][0]
        
        klines = []
        for i in range(len(timestamps)):
            klines.append({
                't': timestamps[i],
                'o': quotes['open'][i],
                'h': quotes['high'][i],
                'l': quotes['low'][i],
                'c': quotes['close'][i],
                'v': quotes['volume'][i]
            })
        return klines
    except Exception as e:
        print(f'Fetch error: {e}')
        return []

def compute_atr(klines, period=14):
    if len(klines) < period + 1:
        return None
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]['h']
        low = klines[i]['l']
        prev_close = klines[i-1]['c']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs[-period:]) / period

def build_transitions(klines):
    """Build Markov transition matrix"""
    transitions = {}
    
    for i in range(STATE_WINDOW, len(klines) - 1):
        # Build state from last STATE_WINDOW directions
        state_parts = []
        for j in range(i - STATE_WINDOW, i):
            if klines[j]['c'] > klines[j-1]['c']:
                state_parts.append('1')
            else:
                state_parts.append('0')
        state = ''.join(state_parts)
        
        # Next direction
        next_dir = 'UP' if klines[i+1]['c'] > klines[i]['c'] else 'DOWN'
        
        if state not in transitions:
            transitions[state] = {'UP': 0, 'DOWN': 0, 'total': 0}
        
        transitions[state][next_dir] += 1
        transitions[state]['total'] += 1
    
    return transitions

def get_prob(transitions, state):
    if state not in transitions:
        return 0.5, 0
    m = transitions[state]
    total = m['total']
    if total == 0:
        return 0.5, 0
    up_prob = m['UP'] / total
    return up_prob, total

def main():
    print('BTC 5m Backtest - 5 Days')
    print('=' * 50)
    
    klines = get_btc_data()
    print(f'Fetched {len(klines)} 5m candles')
    
    if len(klines) < 100:
        print('Not enough data')
        return
    
    atr = compute_atr(klines)
    atr_avg = atr
    vol_avg = sum(k['v'] for k in klines[-100:]) / 100 if len(klines) >= 100 else 1
    
    print(f'ATR: {atr:.2f}' if atr else 'ATR: N/A')
    print(f'Vol avg: {vol_avg:.0f}')
    print()
    
    transitions = build_transitions(klines)
    print(f'States: {len(transitions)}')
    
    # Backtest
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    
    for i in range(STATE_WINDOW, len(klines) - 1):
        # Get state
        state_parts = []
        for j in range(i - STATE_WINDOW, i):
            if klines[j]['c'] > klines[j-1]['c']:
                state_parts.append('1')
            else:
                state_parts.append('0')
        state = ''.join(state_parts)
        
        prob, n = get_prob(transitions, state)
        prob = max(0.3, min(0.9, prob))  # Bound
        
        # Direction
        last_dir = 'UP' if klines[i]['c'] > klines[i-1]['c'] else 'DOWN'
        
        # Check filters
        current_vol = klines[i]['v']
        passes_vol = current_vol > vol_avg * 0.6
        
        if passes_vol and prob >= MIN_PROB:
            # Simulate trade
            direction = last_dir
            entry = klines[i]['c']
            
            # Next candle direction
            actual_dir = 'UP' if klines[i+1]['c'] > klines[i]['c'] else 'DOWN'
            
            trades += 1
            if actual_dir == direction:
                wins += 1
                pnl += 100
            else:
                losses += 1
                pnl -= 100
            
            if trades <= 10 or trades % 100 == 0:
                d = datetime.fromtimestamp(klines[i]['t']).strftime('%Y-%m-%d %H:%M')
                print(f'{d} | State:{state} | p̂:{prob:.3f} | {direction} | Actual:{actual_dir} | PnL:{pnl}')
    
    print()
    print(f'=== Results ===')
    print(f'Trades: {trades}')
    print(f'Wins: {wins} | Losses: {losses}')
    print(f'Win Rate: {wins/trades*100:.1f}%' if trades > 0 else 'N/A')
    print(f'PnL: ${pnl}')

if __name__ == '__main__':
    main()
