#!/usr/bin/env python3
"""
BTC 5m Backtest - Win Rate & R:R Analysis
Uses Polymarket binary options payoff structure
"""

import json
import urllib.request
import csv
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict


MIN_PROB = 0.50  # Current production setting
STATE_WINDOW = 4
POSITION_SIZE = 1.00  # $1 per trade


def load_cached_btc():
    """Try to load from cache first"""
    paths = [
        '/home/node/.openclaw/workspace/BTC-USD-5m.csv',
        '/tmp/btc_5m_data.csv',
    ]
    for path in paths:
        if os.path.exists(path):
            candles = []
            with open(path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        candles.append({
                            't': int(row.get('timestamp', row.get('t', 0))),
                            'o': float(row['open']),
                            'h': float(row['high']),
                            'l': float(row['low']),
                            'c': float(row['close']),
                            'v': float(row.get('volume', 0))
                        })
                    except (KeyError, ValueError):
                        continue
            if candles:
                return candles
    return None


def get_btc_data():
    """Fetch BTC 5m data from Yahoo Finance"""
    try:
        now = datetime.now()
        start = int((now - timedelta(days=6)).timestamp())
        end = int(now.timestamp())
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1={start}&period2={end}&interval=5m'
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
        print(f'Yahoo fetch failed: {e}')
        return None


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
    transitions = {}
    for i in range(STATE_WINDOW, len(klines) - 1):
        state_parts = []
        for j in range(i - STATE_WINDOW, i):
            state_parts.append('1' if klines[j]['c'] > klines[j-1]['c'] else '0')
        state = ''.join(state_parts)
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
    return m['UP'] / total, total


def main():
    print("=" * 60)
    print("🎲 BTC 5m Backtest - Win Rate & R:R Analysis")
    print(f"   Strategy: Markov State (window={STATE_WINDOW}) + Vol Filter")
    print(f"   MIN_PROB: {MIN_PROB}")
    print(f"   Position: ${POSITION_SIZE}/trade")
    print("=" * 60)

    klines = load_cached_btc()
    if not klines:
        klines = get_btc_data()
    if not klines:
        print("❌ No data available")
        return

    print(f"📊 Loaded {len(klines)} 5m candles")
    if klines:
        first = datetime.fromtimestamp(klines[0]['t']).strftime('%Y-%m-%d %H:%M')
        last = datetime.fromtimestamp(klines[-1]['t']).strftime('%Y-%m-%d %H:%M')
        print(f"   Range: {first} → {last}")

    # Compute ATR for filter
    atr = compute_atr(klines)
    vol_avg = sum(k['v'] for k in klines[-100:]) / 100 if len(klines) >= 100 else 1
    print(f"   ATR: {atr:.2f}" if atr else "   ATR: N/A")
    print(f"   Vol avg: {vol_avg:.0f}")
    print()

    # Build transitions
    transitions = build_transitions(klines)
    print(f"🧠 Markov transitions: {len(transitions)} states")
    print()

    # Backtest with binary options payoff
    trades = []
    for i in range(STATE_WINDOW, len(klines) - 1):
        # Get state
        state_parts = []
        for j in range(i - STATE_WINDOW, i):
            state_parts.append('1' if klines[j]['c'] > klines[j-1]['c'] else '0')
        state = ''.join(state_parts)
        prob, n = get_prob(transitions, state)
        prob = max(0.3, min(0.9, prob))

        last_dir = 'UP' if klines[i]['c'] > klines[i-1]['c'] else 'DOWN'
        current_vol = klines[i]['v']
        passes_vol = current_vol > vol_avg * 0.6

        if not (passes_vol and prob >= MIN_PROB):
            continue

        # Simulate trade with binary options payoff
        direction = last_dir  # Bet on continuation
        # Entry price = 0.50 (assume even money at signal)
        # Actually use probabilistic entry: P(win) drives price
        entry_price = 0.495  # 0.5% spread

        actual_dir = 'UP' if klines[i+1]['c'] > klines[i]['c'] else 'DOWN'
        won = (actual_dir == direction)

        # Binary options payoff
        if won:
            profit_per_unit = 1.00 - entry_price  # $0.505
            pnl = profit_per_unit * POSITION_SIZE
        else:
            pnl = -entry_price * POSITION_SIZE  # -$0.495

        trades.append({
            'time': datetime.fromtimestamp(klines[i]['t']).strftime('%Y-%m-%d %H:%M'),
            'state': state,
            'p_hat': prob,
            'direction': direction,
            'actual': actual_dir,
            'won': won,
            'pnl': pnl
        })

    if not trades:
        print("❌ No trades triggered")
        return

    # ==================== Results ====================
    wins = sum(1 for t in trades if t['won'])
    losses = len(trades) - wins
    win_rate = wins / len(trades) * 100

    win_pnls = [t['pnl'] for t in trades if t['won']]
    loss_pnls = [t['pnl'] for t in trades if not t['won']]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    total_pnl = sum(t['pnl'] for t in trades)

    # R:R calculations
    rr_dollar = abs(avg_win / avg_loss) if avg_loss else 0  # $ won / $ lost
    rr_unit = 1.02  # Binary options: 0.505 / 0.495

    # Break-even win rate
    be_wr = entry_price / 1.0 * 100  # Need >49.5% to profit

    # Expectancy
    expectancy = (win_rate / 100) * avg_win + ((100 - win_rate) / 100) * avg_loss

    # Profit factor
    gross_profit = sum(win_pnls)
    gross_loss = abs(sum(loss_pnls))
    profit_factor = gross_profit / gross_loss if gross_loss else 0

    print("📊 BACKTEST RESULTS")
    print("=" * 60)
    print(f"Trades:           {len(trades)}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print()
    print(f"🎯 WIN RATE:      {win_rate:.2f}%")
    print(f"⚖️  Break-even:    {be_wr:.2f}%")
    print(f"📈 Edge:          {win_rate - be_wr:+.2f}pp")
    print()
    print(f"💰 R:R ANALYSIS (Binary Options @ 0.495):")
    print(f"   Entry:         $0.495")
    print(f"   Win payout:    $1.000 (+$0.505)")
    print(f"   Loss:          $0.000 (-$0.495)")
    print(f"   Unit R:R:      1:{rr_unit:.3f} (binary)")
    print()
    print(f"💵 P&L:")
    print(f"   Avg Win:       ${avg_win:+.4f}")
    print(f"   Avg Loss:      ${avg_loss:+.4f}")
    print(f"   Total P&L:     ${total_pnl:+.2f}")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Expectancy:    ${expectancy:+.4f}/trade")
    print()
    print(f"📅 By Day:")
    by_day = defaultdict(list)
    for t in trades:
        day = t['time'][:10]
        by_day[day].append(t)
    for day in sorted(by_day):
        day_trades = by_day[day]
        day_wins = sum(1 for t in day_trades if t['won'])
        day_wr = day_wins / len(day_trades) * 100
        day_pnl = sum(t['pnl'] for t in day_trades)
        print(f"   {day}: {len(day_trades):3d} trades, {day_wr:5.1f}% WR, ${day_pnl:+.2f}")

    # Verdict
    print()
    print("=" * 60)
    print("🎯 VERDICT")
    print("=" * 60)
    if win_rate > be_wr:
        print(f"✅ Strategy is EDGE-POSITIVE: WR {win_rate:.1f}% > BE {be_wr:.1f}%")
        print(f"   Expected profit: ${expectancy:+.4f}/trade")
        print(f"   Over 100 trades: ${expectancy*100:+.2f}")
    else:
        print(f"❌ Strategy is EDGE-NEGATIVE: WR {win_rate:.1f}% < BE {be_wr:.1f}%")
        print(f"   Expected loss: ${expectancy:+.4f}/trade")
        print(f"   Over 100 trades: ${expectancy*100:+.2f}")

    if profit_factor > 1.5:
        print(f"   💪 Strong profit factor: {profit_factor:.2f}")
    elif profit_factor > 1.0:
        print(f"   📊 Marginal profit factor: {profit_factor:.2f}")
    else:
        print(f"   ⚠️  Weak profit factor: {profit_factor:.2f}")

    # Save
    with open('/tmp/btc_5m_wr_rr.json', 'w') as f:
        json.dump({
            'trades': len(trades),
            'win_rate': win_rate,
            'break_even_wr': be_wr,
            'edge_pp': win_rate - be_wr,
            'rr_unit': rr_unit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_pnl': total_pnl,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'by_day': {d: {'trades': len(t), 'wr': sum(1 for x in t if x['won'])/len(t)*100, 'pnl': sum(x['pnl'] for x in t)} for d, t in by_day.items()}
        }, f, indent=2)
    print(f"\n💾 Results saved to /tmp/btc_5m_wr_rr.json")


if __name__ == "__main__":
    main()
