#!/usr/bin/env python3
"""
Backtest BTC 5m with NEW aggressive config:
- MIN_PROB = 0.42
- MIN_EDGE = 0.015
- ATR_MULT = 0.4
- VOL_MULT = 0.3
"""
import json
import sys
import os
from datetime import datetime, timezone
import urllib.request

# === NEW AGGRESSIVE CONFIG ===
MIN_PROB = 0.42
MIN_EDGE = 0.015
ATR_MULT = 0.4
VOL_MULT = 0.3
STATE_WINDOW = 4

def fetch_btc_klines(start_ts, end_ts):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1={start_ts}&period2={end_ts}&interval=5m'
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
            if quotes['close'][i] is not None:
                klines.append({
                    't': timestamps[i],
                    'o': quotes['open'][i],
                    'h': quotes['high'][i],
                    'l': quotes['low'][i],
                    'c': quotes['close'][i],
                    'v': quotes['volume'][i] or 0
                })
        return klines
    except Exception as e:
        print(f"Error: {e}")
        return []

def compute_directions(klines):
    return [1 if klines[i]['c'] > klines[i-1]['c'] else 0 for i in range(1, len(klines))]

def compute_streaks(directions):
    streaks = []
    current = 1
    for i in range(len(directions)):
        if i > 0 and directions[i] == directions[i-1]:
            current += 1
        else:
            current = 1
        streaks.append(current)
    return streaks

def compute_atr(klines, index, period=14):
    if index < period:
        return None
    trs = []
    for i in range(index-period+1, index+1):
        if i == 0:
            continue
        h, l, pc = klines[i]['h'], klines[i]['l'], klines[i-1]['c']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0

def get_avg_atr(klines, index, period=14, lookback=20):
    atrs = [compute_atr(klines, i, period) for i in range(max(14, index-lookback+1), index+1)]
    atrs = [a for a in atrs if a is not None]
    return sum(atrs) / len(atrs) if atrs else 0

def get_volume(index, klines):
    return klines[index]['v']

def get_avg_vol(klines, index, lookback=20):
    vols = [klines[i]['v'] for i in range(max(0, index-lookback+1), index+1)]
    return sum(vols) / len(vols) if vols else 0

def main():
    end_ts = int(datetime(2026, 6, 3, tzinfo=timezone.utc).timestamp())
    start_ts = int(datetime(2026, 5, 27, tzinfo=timezone.utc).timestamp())  # 7 days only

    print("Fetching BTC 5m data (May 27 - Jun 3, 7 days)...", flush=True)
    klines = fetch_btc_klines(start_ts, end_ts)
    print(f"Got {len(klines)} candles")

    if len(klines) < 200:
        print("Not enough data")
        return

    directions = compute_directions(klines)
    streaks = compute_streaks(directions)

    print(f"\nBacktesting with config:")
    print(f"  MIN_PROB   = {MIN_PROB}")
    print(f"  MIN_EDGE   = {MIN_EDGE}")
    print(f"  ATR_MULT   = {ATR_MULT}")
    print(f"  VOL_MULT   = {VOL_MULT}")
    print(f"  STATE_WIN  = {STATE_WINDOW}")
    print()

    results = []

    for i in range(STATE_WINDOW + 14, len(klines) - 1):
        atr = compute_atr(klines, i, 14)
        atr_avg = get_avg_atr(klines, i, 14, 20)
        vol = get_volume(i, klines)
        vol_avg = get_avg_vol(klines, i, 20)

        if atr is None or atr < atr_avg * ATR_MULT or vol < vol_avg * VOL_MULT:
            continue

        state = ''.join(str(s) for s in streaks[i-STATE_WINDOW+1:i+1])

        transitions = {}
        for j in range(STATE_WINDOW + 14, i):
            j_atr = compute_atr(klines, j, 14)
            j_vol = get_volume(j, klines)
            j_atr_avg = get_avg_atr(klines, j, 14, 20)
            j_vol_avg = get_avg_vol(klines, j, 20)
            if j_atr is None or j_atr < j_atr_avg * ATR_MULT or j_vol < j_vol_avg * VOL_MULT:
                continue
            j_state = ''.join(str(s) for s in streaks[j-STATE_WINDOW+1:j+1])
            next_dir = directions[j]
            if j_state not in transitions:
                transitions[j_state] = []
            transitions[j_state].append(next_dir)

        if state not in transitions or len(transitions[state]) < 5:
            continue

        next_dirs = transitions[state]
        last_dir = directions[i]
        same = sum(1 for d in next_dirs if d == last_dir)
        prob_continue = same / len(next_dirs)

        q = 0.505
        edge = prob_continue - q if last_dir == 1 else (1 - prob_continue) - q

        if prob_continue < MIN_PROB:
            continue
        if edge < MIN_EDGE:
            continue

        actual_next = directions[i+1]
        won = (last_dir == actual_next)

        if won:
            pnl = 1 - q
        else:
            pnl = -q

        results.append({
            'i': i,
            'state': state,
            'prob': prob_continue,
            'last_dir': 'UP' if last_dir == 1 else 'DOWN',
            'won': won,
            'pnl': pnl
        })

    if not results:
        print("No signals triggered")
        return

    wins = sum(1 for r in results if r['won'])
    losses = len(results) - wins
    wr = wins / len(results) * 100
    total_pnl = sum(r['pnl'] for r in results)
    avg_pnl = total_pnl / len(results)

    print(f"{'='*60}")
    print(f"RESULTS ({len(results)} signals):")
    print(f"  Wins:    {wins}")
    print(f"  Losses:  {losses}")
    print(f"  WR:      {wr:.2f}%")
    print(f"  Total P&L: ${total_pnl:+.2f}")
    print(f"  Avg P&L:   ${avg_pnl:+.4f}")
    print(f"  Edge vs 50% (random):  +{wr-50:.2f}pp")
    print(f"  Break-even WR: 33.1% (binary R:R 1:2)")
    print(f"  Edge vs break-even:    +{wr-33.1:.2f}pp")

    print(f"\n{'='*60}")
    print(f"PROJECTIONS (at $1/trade):")
    print(f"  Per signal:              ${avg_pnl:+.4f}")
    print(f"  Per day (~{len(results)/30:.1f} signals):    ${avg_pnl*len(results)/30:+.2f}")
    print(f"  Per week (~{len(results)/4:.1f} signals):   ${avg_pnl*len(results)/4:+.2f}")
    print(f"  Per month (~{len(results):.0f} signals):  ${avg_pnl*len(results):+.2f}")

    up_trades = [r for r in results if r['last_dir'] == 'UP']
    down_trades = [r for r in results if r['last_dir'] == 'DOWN']
    if up_trades:
        print(f"\n  UP signals:   {len(up_trades)}, WR: {sum(1 for r in up_trades if r['won'])/len(up_trades)*100:.1f}%, P&L: ${sum(r['pnl'] for r in up_trades):+.2f}")
    if down_trades:
        print(f"  DOWN signals: {len(down_trades)}, WR: {sum(1 for r in down_trades if r['won'])/len(down_trades)*100:.1f}%, P&L: ${sum(r['pnl'] for r in down_trades):+.2f}")

    # Save
    with open('/tmp/btc_5m_backtest_aggressive.json', 'w') as f:
        json.dump({
            'config': {
                'MIN_PROB': MIN_PROB, 'MIN_EDGE': MIN_EDGE,
                'ATR_MULT': ATR_MULT, 'VOL_MULT': VOL_MULT,
                'STATE_WINDOW': STATE_WINDOW
            },
            'n_signals': len(results),
            'wins': wins, 'losses': losses,
            'wr': wr, 'total_pnl': total_pnl, 'avg_pnl': avg_pnl
        }, f, indent=2)
    print(f"\nSaved to /tmp/btc_5m_backtest_aggressive.json")

if __name__ == '__main__':
    main()
