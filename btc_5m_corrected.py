#!/usr/bin/env python3
"""
BTC 5m Backtest - CORRECTED Win Rate & R:R
Binary options R:R = Risk:GrossReward = 0.495:1.00 = 1:2.02
Break-even WR = 33.3% (NOT 49.5%)
"""

import json
import csv
import os
from datetime import datetime
from collections import defaultdict


MIN_PROB = 0.50
STATE_WINDOW = 4
ENTRY_PRICE = 0.495  # Binary option entry
PAYOUT = 1.00        # Binary option gross payout on win


def load_cached_btc():
    paths = ['/home/node/.openclaw/workspace/BTC-USD-5m.csv', '/tmp/btc_5m_data.csv']
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


def fetch_yahoo_btc():
    import urllib.request
    from datetime import datetime, timedelta
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?period1=' + str(int((datetime.now() - timedelta(days=7)).timestamp())) + '&period2=' + str(int(datetime.now().timestamp())) + '&interval=5m'
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


def main():
    print("=" * 70)
    print("🎲 BTC 5m - CORRECTED R:R Analysis")
    print(f"   Binary Options @ {ENTRY_PRICE} entry, ${PAYOUT} payout")
    print(f"   R:R = 1:{PAYOUT/ENTRY_PRICE:.2f} (Risk:GrossReward)")
    print(f"   Break-even WR = 1/(1+{PAYOUT/ENTRY_PRICE:.2f}) = {1/(1+PAYOUT/ENTRY_PRICE)*100:.1f}%")
    print("=" * 70)

    klines = load_cached_btc()
    if not klines:
        klines = fetch_yahoo_btc()
    if not klines:
        print("❌ No data available")
        return

    print(f"📊 Loaded {len(klines)} 5m candles")
    first = datetime.fromtimestamp(klines[0]['t']).strftime('%Y-%m-%d %H:%M')
    last = datetime.fromtimestamp(klines[-1]['t']).strftime('%Y-%m-%d %H:%M')
    print(f"   Range: {first} → {last}")
    print()

    vol_avg = sum(k['v'] for k in klines[-100:]) / 100 if len(klines) >= 100 else 1
    transitions = build_transitions(klines)
    print(f"🧠 {len(transitions)} Markov states")
    print()

    # Backtest
    trades = []
    for i in range(STATE_WINDOW, len(klines) - 1):
        state_parts = []
        for j in range(i - STATE_WINDOW, i):
            state_parts.append('1' if klines[j]['c'] > klines[j-1]['c'] else '0')
        state = ''.join(state_parts)
        m = transitions.get(state, {'UP': 0, 'DOWN': 0, 'total': 0})
        prob = m['UP'] / m['total'] if m['total'] else 0.5
        prob = max(0.3, min(0.9, prob))

        last_dir = 'UP' if klines[i]['c'] > klines[i-1]['c'] else 'DOWN'
        current_vol = klines[i]['v']

        if current_vol > vol_avg * 0.6 and prob >= MIN_PROB:
            actual_dir = 'UP' if klines[i+1]['c'] > klines[i]['c'] else 'DOWN'
            won = (actual_dir == last_dir)
            trades.append({
                'time': datetime.fromtimestamp(klines[i]['t']).strftime('%Y-%m-%d %H:%M'),
                'state': state,
                'p_hat': prob,
                'direction': last_dir,
                'actual': actual_dir,
                'won': won
            })

    if not trades:
        print("❌ No trades")
        return

    # Metrics
    wins = sum(1 for t in trades if t['won'])
    losses = len(trades) - wins
    win_rate = wins / len(trades) * 100

    # R:R Analysis (CORRECTED)
    risk = ENTRY_PRICE       # 0.495
    reward = PAYOUT          # 1.00
    net_profit = reward - risk   # 0.505
    rr_ratio = reward / risk     # 2.02
    be_wr = risk / (risk + reward) * 100  # 33.11%

    # P&L per $1 position
    win_pnl = net_profit    # +0.505
    loss_pnl = -risk         # -0.495
    total_pnl = wins * win_pnl + losses * loss_pnl

    # Per-trade expectancy
    expectancy = (win_rate / 100) * win_pnl + ((100 - win_rate) / 100) * loss_pnl

    # Profit factor
    gross_profit = wins * win_pnl
    gross_loss = losses * abs(loss_pnl)
    profit_factor = gross_profit / gross_loss if gross_loss else 0

    # Kelly Criterion
    kelly = (win_rate / 100 * rr_ratio - (1 - win_rate / 100)) / rr_ratio

    # Edge in percentage points
    edge_pp = win_rate - be_wr

    print("📊 RESULTS")
    print("=" * 70)
    print(f"Trades:           {len(trades)}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print()
    print(f"🎯 WIN RATE:      {win_rate:.2f}%")
    print(f"⚖️  Break-even:    {be_wr:.2f}%")
    print(f"📈 Edge:          {edge_pp:+.2f}pp")
    print()
    print(f"💰 R:R ANALYSIS:")
    print(f"   Risk:          ${risk:.3f} (entry)")
    print(f"   Gross Reward:  ${reward:.3f} (payout)")
    print(f"   Net Profit:    ${net_profit:.3f} (reward - risk)")
    print(f"   R:R:           1:{rr_ratio:.2f}")
    print()
    print(f"💵 P&L (per $1 position):")
    print(f"   Win:           ${win_pnl:+.4f}")
    print(f"   Loss:          ${loss_pnl:+.4f}")
    print(f"   Total:         ${total_pnl:+.4f}")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Expectancy:    ${expectancy:+.4f}/trade")
    print(f"   Kelly %:       {kelly*100:.2f}% (optimal bet size)")
    print()
    print(f"📅 By Day:")
    by_day = defaultdict(list)
    for t in trades:
        by_day[t['time'][:10]].append(t)
    for day in sorted(by_day):
        day_trades = by_day[day]
        day_wins = sum(1 for t in day_trades if t['won'])
        day_wr = day_wins / len(day_trades) * 100
        day_pnl = day_wins * win_pnl + (len(day_trades) - day_wins) * loss_pnl
        print(f"   {day}: {len(day_trades):3d} trades, {day_wr:5.1f}% WR, ${day_pnl:+.4f}")

    # Per Day Projection
    total_days = len(by_day)
    avg_daily_pnl = total_pnl / total_days if total_days else 0
    avg_daily_trades = len(trades) / total_days if total_days else 0

    print()
    print("=" * 70)
    print("📈 PROJECTIONS (at current $1/trade)")
    print("=" * 70)
    print(f"   Trades/day:    {avg_daily_trades:.1f}")
    print(f"   Daily P&L:     ${avg_daily_pnl:+.4f}")
    print(f"   Weekly:        ${avg_daily_pnl*7:+.4f}")
    print(f"   Monthly:       ${avg_daily_pnl*30:+.4f}")
    print()
    print("   With Kelly bet sizing:")
    print(f"   Kelly %:       {kelly*100:.2f}% of bankroll per trade")
    print(f"   With $1000:    bet ${kelly*1000:.2f}/trade")
    kelly_trade_pnl = (kelly*1000) * expectancy
    print(f"   Per-trade P&L: ${kelly_trade_pnl:+.2f}")
    print(f"   Daily P&L:     ${kelly_trade_pnl*avg_daily_trades:+.2f} (at Kelly size)")
    print(f"   Monthly:       ${kelly_trade_pnl*avg_daily_trades*30:+.2f}")

    # Verdict
    print()
    print("=" * 70)
    print("🎯 VERDICT")
    print("=" * 70)
    if edge_pp > 10:
        verdict = "✅ STRONG EDGE - Strategy has 10+pp edge over break-even"
    elif edge_pp > 5:
        verdict = "✅ DECENT EDGE - 5-10pp edge, viable"
    elif edge_pp > 0:
        verdict = "⚠️  MARGINAL EDGE - small positive edge, fragile"
    else:
        verdict = "❌ NO EDGE - negative expectation"
    print(verdict)
    print(f"   Edge:         {edge_pp:+.2f}pp over break-even ({be_wr:.1f}%)")
    print(f"   WR achieved:  {win_rate:.2f}%")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Kelly %:      {kelly*100:.2f}% (use this for bet sizing)")

    # Save
    with open('/tmp/btc_5m_corrected.json', 'w') as f:
        json.dump({
            'trades': len(trades),
            'win_rate': win_rate,
            'break_even': be_wr,
            'edge_pp': edge_pp,
            'rr_ratio': rr_ratio,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'kelly_pct': kelly * 100,
            'total_pnl': total_pnl,
            'avg_daily_pnl': avg_daily_pnl
        }, f, indent=2)


if __name__ == "__main__":
    main()
