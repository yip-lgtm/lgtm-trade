#!/usr/bin/env python3
"""
ICT Scanner Daily Settlement + Cumulative Tracking
- Auto-detect WIN/LOSS for signals
- Track daily P&L, qualified days
- Send daily summary at 00:00 UTC
"""
import sys
import json
import csv
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/home/node/.openclaw/workspace')
from ict_scanner_v11 import YahooCSVDataProvider, ICTScanner, Candle

# Configuration
SYMBOLS = ['MNQ.F', 'M2K.F', 'MBT.F', 'MET.F']  # Best performers per backtest
POINT_VALUE = {'MNQ.F': 2, 'M2K.F': 5, 'MBT.F': 10, 'MET.F': 1}
SINGLE_TRADE_RISK = 100
TP1_PROFIT = 250
TP2_PROFIT = 500
SL_LOSS = 100

# Files
PENDING_FILE = '/tmp/ict_pending_trades.json'
SETTLED_FILE = '/tmp/ict_settled_trades.jsonl'
DAILY_STATS_FILE = '/tmp/ict_daily_stats.json'
KZ_SCHEDULE = {
    'LondonOpen': (6, 0, 7, 0),
    'NYOpen': (12, 30, 13, 30),
}

def get_intraday_data(symbol, count=500):
    """Load 15min data for symbol"""
    base = '/home/node/.openclaw/workspace'
    for path in [
        f"{base}/{symbol.replace('.', '_')}_15min.csv",
        f"{base}/{symbol}_15min.csv",
    ]:
        try:
            candles = []
            with open(path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        dt = row.get('Datetime') or row.get('datetime', '')
                        candles.append(Candle(
                            datetime=dt,
                            open=float(row.get('Open') or row['open']),
                            high=float(row.get('High') or row['high']),
                            low=float(row.get('Low') or row['low']),
                            close=float(row.get('Close') or row['close']),
                            volume=float(row.get('Volume') or row.get('volume', 0))
                        ))
                    except (KeyError, ValueError, TypeError):
                        continue
            if candles:
                return candles
        except FileNotFoundError:
            continue
    return []

def parse_dt(dt_str):
    dt_str = dt_str.replace('-04:00', '').replace('-05:00', '').strip()
    try:
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except:
        return None

def get_kz_for_time(dt):
    """Return KZ name if dt is in a KZ window, else None"""
    cur_min = dt.hour * 60 + dt.minute
    for name, (h1, m1, h2, m2) in KZ_SCHEDULE.items():
        if h1*60+m1 <= cur_min < h2*60+m2:
            return name
    return None

def calculate_outcome(setup, future_candles, symbol):
    """Determine WIN/LOSS by walking forward through candles"""
    pv = POINT_VALUE.get(symbol, 5)
    entry = setup.entry
    sl = setup.stop_loss
    tp1 = setup.tp1
    tp2 = setup.tp2
    direction = setup.direction

    for candle in future_candles:
        if direction == 'LONG':
            if candle.low <= sl:
                return ('LOSS', -SL_LOSS, sl, parse_dt(candle.datetime))
            if candle.high >= tp1:
                if candle.high >= tp2:
                    return ('WIN_TP2', TP2_PROFIT, tp2, parse_dt(candle.datetime))
                return ('WIN_TP1', TP1_PROFIT, tp1, parse_dt(candle.datetime))
        else:  # SHORT
            if candle.high >= sl:
                return ('LOSS', -SL_LOSS, sl, parse_dt(candle.datetime))
            if candle.low <= tp1:
                if candle.low <= tp2:
                    return ('WIN_TP2', TP2_PROFIT, tp2, parse_dt(candle.datetime))
                return ('WIN_TP1', TP1_PROFIT, tp1, parse_dt(candle.datetime))
    return ('OPEN', 0, future_candles[-1].close if future_candles else entry, None)

def scan_for_pending():
    """Walk through today's KZ windows, find signals not yet settled"""
    dp = YahooCSVDataProvider()
    scanner = ICTScanner(dp, notifier=None)

    # Load pending
    pending = []
    try:
        if os.path.exists(PENDING_FILE) and os.path.getsize(PENDING_FILE) > 0:
            with open(PENDING_FILE) as f:
                content = f.read().strip()
                if content:
                    try:
                        pending = json.loads(content)
                    except json.JSONDecodeError:
                        # Corrupt file - reset it
                        print(f"⚠️ Corrupt pending file, resetting")
                        with open(PENDING_FILE, 'w') as f:
                            f.write('[]')
                        pending = []
    except Exception as e:
        print(f"⚠️ Error loading pending: {e}")
        pending = []

    if not pending:
        print("No pending trades")
        return

    print(f"📋 {len(pending)} pending trades to settle")

    settled_today = []
    for trade in pending:
        symbol = trade['symbol']
        data = get_intraday_data(symbol, count=500)
        if not data:
            print(f"  ⚠️ No data for {symbol}")
            continue

        # Find the entry candle
        entry_dt = parse_dt(trade['signal_time'])
        entry_idx = None
        for i, c in enumerate(data):
            dt = parse_dt(c.datetime)
            if dt and abs((dt - entry_dt).total_seconds()) < 600:  # 10 min tolerance
                entry_idx = i
                break

        if entry_idx is None:
            print(f"  ⚠️ {symbol}: Entry candle not found for {trade['signal_time']}")
            continue

        # Build a fake setup object
        from ict_scanner_v11 import Setup
        setup = Setup(
            symbol=symbol,
            direction=trade['direction'],
            entry=trade['entry'],
            stop_loss=trade['sl'],
            tp1=trade['tp1'],
            tp2=trade['tp2'],
            confidence=trade.get('confidence', 0),
            reasons=trade.get('reasons', []),
            ote_zone={},
            fvg_type=None,
            swing_high=0,
            swing_low=0,
        )

        # Walk forward
        future = data[entry_idx+1:]
        outcome, pnl, exit_price, exit_time = calculate_outcome(setup, future, symbol)

        # Record
        trade['outcome'] = outcome
        trade['pnl'] = pnl
        trade['exit_price'] = exit_price
        trade['exit_time'] = exit_time.isoformat() if exit_time else None
        trade['settled_at'] = datetime.now(timezone.utc).isoformat()

        # Write to settled log
        with open(SETTLED_FILE, 'a') as f:
            f.write(json.dumps(trade) + '\n')

        settled_today.append(trade)
        print(f"  ✅ {symbol} {trade['direction']:5} @ {trade['entry']:.2f} | {outcome:8} ${pnl:+.0f}")

    # Clear pending
    with open(PENDING_FILE, 'w') as f:
        json.dump([], f)

    # Update daily stats
    update_daily_stats(settled_today)

def add_pending(signal_data):
    """Add a signal to pending list"""
    pending = []
    try:
        if os.path.exists(PENDING_FILE) and os.path.getsize(PENDING_FILE) > 0:
            with open(PENDING_FILE) as f:
                content = f.read().strip()
                if content:
                    pending = json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  ⚠️ Reset corrupt pending: {e}")
        pending = []

    # Avoid duplicates
    sig_id = f"{signal_data['symbol']}_{signal_data['signal_time']}"
    if any(t.get('id') == sig_id for t in pending):
        print(f"  Duplicate: {sig_id}")
        return False

    signal_data['id'] = sig_id
    signal_data['added_at'] = datetime.now(timezone.utc).isoformat()
    pending.append(signal_data)

    with open(PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)

    print(f"  Added pending: {sig_id}")
    return True

def update_daily_stats(settled_trades):
    """Update daily cumulative stats"""
    # Load all settled
    all_settled = []
    if os.path.exists(SETTLED_FILE):
        with open(SETTLED_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_settled.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # Skip corrupt lines

    # Load existing daily stats
    daily_stats = {}
    if os.path.exists(DAILY_STATS_FILE):
        with open(DAILY_STATS_FILE) as f:
            daily_stats = json.load(f)

    # Group by date
    by_date = defaultdict(list)
    for t in all_settled:
        date_key = t['date']
        by_date[date_key].append(t)

    # Recompute daily stats
    for date_key, trades in by_date.items():
        completed = [t for t in trades if t.get('outcome') in ('WIN_TP1', 'WIN_TP2', 'LOSS')]
        wins = [t for t in completed if t['outcome'].startswith('WIN')]
        losses = [t for t in completed if t['outcome'] == 'LOSS']
        pnl = sum(t.get('pnl', 0) for t in completed)
        qualified = pnl >= TP1_PROFIT
        kill_switch = pnl <= -200

        long_trades = [t for t in completed if t['direction'] == 'LONG']
        short_trades = [t for t in completed if t['direction'] == 'SHORT']

        daily_stats[date_key] = {
            'date': date_key,
            'total_trades': len(trades),
            'completed': len(completed),
            'wins': len(wins),
            'losses': len(losses),
            'wr': (len(wins) / len(completed) * 100) if completed else 0,
            'pnl': pnl,
            'qualified_day': qualified,
            'kill_switch': kill_switch,
            'long_pnl': sum(t.get('pnl', 0) for t in long_trades),
            'short_pnl': sum(t.get('pnl', 0) for t in short_trades),
        }

    # Sort by date desc
    sorted_stats = {k: daily_stats[k] for k in sorted(daily_stats.keys(), reverse=True)}

    with open(DAILY_STATS_FILE, 'w') as f:
        json.dump(sorted_stats, f, indent=2)

    print(f"📊 Updated daily stats: {len(daily_stats)} days")

def get_cumulative_summary(days=7):
    """Get cumulative summary for last N days"""
    if not os.path.exists(DAILY_STATS_FILE):
        return None

    with open(DAILY_STATS_FILE) as f:
        daily_stats = json.load(f)

    # Last N days
    sorted_dates = sorted(daily_stats.keys(), reverse=True)[:days]
    recent = [daily_stats[d] for d in sorted_dates]

    total_pnl = sum(d['pnl'] for d in recent)
    total_trades = sum(d['total_trades'] for d in recent)
    total_wins = sum(d['wins'] for d in recent)
    total_losses = sum(d['losses'] for d in recent)
    qualified_count = sum(1 for d in recent if d['qualified_day'])
    kill_count = sum(1 for d in recent if d['kill_switch'])

    avg_daily_pnl = total_pnl / len(recent) if recent else 0
    avg_wr = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0

    return {
        'period': f"Last {len(recent)} days",
        'total_pnl': total_pnl,
        'avg_daily_pnl': avg_daily_pnl,
        'total_trades': total_trades,
        'wins': total_wins,
        'losses': total_losses,
        'wr': avg_wr,
        'qualified_days': qualified_count,
        'kill_switch_days': kill_count,
        'days': recent,
    }

def print_summary():
    """Print cumulative summary"""
    s = get_cumulative_summary(days=7)
    if not s:
        print("No data yet")
        return

    print()
    print("="*70)
    print(f"📊 ICT Scanner Cumulative Summary ({s['period']})")
    print("="*70)
    print(f"Total trades:    {s['total_trades']}")
    print(f"WR:              {s['wr']:.1f}% ({s['wins']}W / {s['losses']}L)")
    print(f"Total P&L:       ${s['total_pnl']:+,.0f}")
    print(f"Avg daily P&L:   ${s['avg_daily_pnl']:+,.0f}")
    print(f"Qualified days:  {s['qualified_days']}/{len(s['days'])}")
    print(f"Kill-switch:     {s['kill_switch_days']}/{len(s['days'])}")
    print()
    print("Per day:")
    for d in s['days']:
        qual = "🎯" if d['qualified_day'] else "  "
        kill = "🛑" if d['kill_switch'] else "  "
        print(f"  {qual}{kill} {d['date']}: {d['total_trades']:2} trades, "
              f"WR {d['wr']:5.1f}%, P&L ${d['pnl']:+5.0f} "
              f"(L:${d['long_pnl']:+4.0f} S:${d['short_pnl']:+4.0f})")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == 'settle':
            scan_for_pending()
        elif cmd == 'summary':
            print_summary()
        elif cmd == 'stats':
            s = get_cumulative_summary()
            if s:
                print(json.dumps(s, indent=2))
    else:
        print_summary()
