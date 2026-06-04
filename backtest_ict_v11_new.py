#!/usr/bin/env python3
"""
ICT Scanner v1.1 Backtest - Walk-forward validation
Tests Daily Bias (BOS) + Order Block + Displacement + Pre-KZ Sweep logic
"""
import sys
import csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/home/node/.openclaw/workspace')
from ict_scanner_v11 import YahooCSVDataProvider, ICTScanner, Candle

# Symbols to backtest
SYMBOLS = ['MES.F', 'MNQ.F', 'M2K.F', 'MGC.F', 'MBT.F', 'MET.F']

# Point value
POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MGC.F': 5,
    'MBT.F': 10, 'MET.F': 1
}

# Backtest period
START_DATE = datetime(2026, 5, 27, tzinfo=timezone.utc)  # ~7 days
END_DATE = datetime(2026, 6, 4, tzinfo=timezone.utc)

# KZ windows (London + NY)
KZ_WINDOWS = [
    ('LondonOpen', 6, 0, 7, 0),     # 06:00-07:00 UTC
    ('NYOpen', 12, 30, 13, 30),     # 12:30-13:30 UTC
]

# Risk
SINGLE_TRADE_RISK = 100  # $100
TP1_PROFIT = 250  # $250 = qualified day
TP2_PROFIT = 500  # $500 = extended target
SL_LOSS = 100  # $100 = max risk

def get_intraday_data(symbol, count=500):
    """Load 15min data for symbol"""
    base = '/home/node/.openclaw/workspace'
    candidates = [
        f"{base}/{symbol.replace('.', '_')}_15min.csv",
        f"{base}/{symbol}_15min.csv",
        f"{base}/{symbol.replace('.', '_')}_1hr.csv",
    ]
    for path in candidates:
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
    """Parse datetime string"""
    dt_str = dt_str.replace('-04:00', '').replace('-05:00', '').strip()
    try:
        return datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except:
        return None

def in_kz_window(dt, kz_name):
    """Check if datetime is in KZ window"""
    for name, h1, m1, h2, m2 in KZ_WINDOWS:
        if name == kz_name:
            cur_min = dt.hour * 60 + dt.minute
            start_min = h1 * 60 + m1
            end_min = h2 * 60 + m2
            if start_min <= cur_min < end_min:
                return True
    return False

def calculate_trade_outcome(setup, data_after_entry, symbol):
    """
    Walk forward through 15min candles to determine trade outcome.
    Returns: ('WIN_TP1'/'WIN_TP2'/'LOSS', pnl, exit_price, exit_time)
    """
    pv = POINT_VALUE.get(symbol, 5)
    entry = setup.entry
    sl = setup.stop_loss
    tp1 = setup.tp1
    tp2 = setup.tp2
    direction = setup.direction  # LONG or SHORT

    for candle in data_after_entry:
        if direction == 'LONG':
            # Check SL hit
            if candle.low <= sl:
                return ('LOSS', -SL_LOSS, sl, parse_dt(candle.datetime))
            # Check TP1
            if candle.high >= tp1:
                # Check if also TP2 in same candle
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

    # No exit found in available data
    return ('OPEN', 0, data_after_entry[-1].close if data_after_entry else entry, None)

def run_backtest():
    print("="*70)
    print("ICT Scanner v1.1 Backtest")
    print("="*70)
    print(f"Period: {START_DATE.date()} → {END_DATE.date()}")
    print(f"Symbols: {', '.join(SYMBOLS)}")
    print(f"KZ Windows: London 06-07 UTC, NY 12:30-13:30 UTC")
    print(f"Risk: ${SINGLE_TRADE_RISK}/trade, TP1: ${TP1_PROFIT}, TP2: ${TP2_PROFIT}")
    print()

    dp = YahooCSVDataProvider()
    scanner = ICTScanner(dp, notifier=None)

    # Load all data first
    all_data = {}
    for sym in SYMBOLS:
        data = get_intraday_data(sym, count=500)
        if not data:
            print(f"⚠️  No data for {sym}")
            continue
        all_data[sym] = data
        print(f"✅ {sym}: {len(data)} 15-min candles ({parse_dt(data[0].datetime).date()} → {parse_dt(data[-1].datetime).date()})")

    print()

    # Track daily bias over time
    daily_biases = {}
    for sym in SYMBOLS:
        if sym not in all_data:
            continue
        # Use MES.F as bias reference (per scanner)
        bias_data = all_data.get('MES.F', all_data[sym])
        for candle in bias_data:
            dt = parse_dt(candle.datetime)
            if dt is None:
                continue
            date_key = dt.date()
            if date_key not in daily_biases:
                # Get daily data so far
                daily_so_far = [c for c in bias_data if parse_dt(c.datetime) and parse_dt(c.datetime).date() <= date_key]
                if len(daily_so_far) >= 10:
                    struct = scanner.get_market_structure(daily_so_far, lookback=min(20, len(daily_so_far)))
                    daily_biases[date_key] = struct['bias']

    print(f"📊 Daily biases computed for {len(daily_biases)} days")
    print()

    # Run backtest
    all_trades = []
    daily_pnl = defaultdict(float)
    qualified_days = set()
    killswitch_days = set()

    for sym in SYMBOLS:
        if sym not in all_data:
            continue

        data = all_data[sym]
        print(f"\n{'='*70}\nScanning {sym}...\n{'='*70}")

        sym_trades = []

        # For each 15-min candle, check if in KZ and run scanner
        for i in range(50, len(data) - 50):  # Need lookback and forward
            candle = data[i]
            dt = parse_dt(candle.datetime)
            if dt is None:
                continue

            # Only check during KZ windows
            in_kz = False
            kz_name = None
            for name, h1, m1, h2, m2 in KZ_WINDOWS:
                cur_min = dt.hour * 60 + dt.minute
                if h1*60+m1 <= cur_min < h2*60+m2:
                    in_kz = True
                    kz_name = name
                    break

            if not in_kz:
                continue

            # Get bias for this day
            bias = daily_biases.get(dt.date(), 'NONE')

            # Get data up to this point + 50 future candles for outcome
            data_so_far = data[:i+1]
            data_future = data[i+1:i+100]  # ~25 hours of 15min

            # Run scanner
            try:
                setups = scanner.find_confluence_setups(data_so_far, bias, sym)
            except Exception as e:
                continue

            for setup in setups:
                # Skip if entry is not this candle
                if abs(setup.entry - candle.close) > setup.entry * 0.005:  # 0.5% tolerance
                    continue

                # Skip if already traded today on this symbol
                date_key = dt.date()
                if daily_pnl[date_key] <= -200:
                    killswitch_days.add(date_key)
                    continue
                if any(t['symbol'] == sym and t['date'] == date_key for t in sym_trades):
                    continue  # Skip multiple trades per symbol per day

                # Calculate trade outcome
                outcome, pnl, exit_price, exit_time = calculate_trade_outcome(setup, data_future, sym)

                # Skip if couldn't determine outcome
                if outcome == 'OPEN':
                    continue

                trade = {
                    'symbol': sym,
                    'date': date_key,
                    'time': dt.isoformat(),
                    'kz': kz_name,
                    'direction': setup.direction,
                    'entry': setup.entry,
                    'sl': setup.stop_loss,
                    'tp1': setup.tp1,
                    'tp2': setup.tp2,
                    'confidence': setup.confidence,
                    'reasons': setup.reasons,
                    'outcome': outcome,
                    'pnl': pnl,
                    'exit_price': exit_price,
                    'exit_time': exit_time.isoformat() if exit_time else None,
                    'bias': bias,
                }
                sym_trades.append(trade)
                daily_pnl[date_key] += pnl

                if pnl >= TP1_PROFIT:
                    qualified_days.add(date_key)

                print(f"  {dt.strftime('%m-%d %H:%M')} {kz_name:11} {setup.direction:5} @ {setup.entry:8.2f} | conf={setup.confidence} | {outcome:8} ${pnl:+.0f} | bias={bias}")
                print(f"    Reasons: {', '.join(setup.reasons[:3])}")

        all_trades.extend(sym_trades)

    # Summary
    print()
    print("="*70)
    print("BACKTEST RESULTS")
    print("="*70)

    if not all_trades:
        print("No trades generated")
        return

    total = len(all_trades)
    wins = [t for t in all_trades if t['outcome'].startswith('WIN')]
    losses = [t for t in all_trades if t['outcome'] == 'LOSS']
    opens = [t for t in all_trades if t['outcome'] == 'OPEN']

    total_pnl = sum(t['pnl'] for t in all_trades)
    win_pnl = sum(t['pnl'] for t in wins)
    loss_pnl = sum(t['pnl'] for t in losses)

    print(f"Total trades:  {total}")
    print(f"  WIN:         {len(wins)} ({len(wins)/total*100:.1f}%)")
    print(f"  LOSS:        {len(losses)} ({len(losses)/total*100:.1f}%)")
    print(f"  OPEN:        {len(opens)}")
    print(f"Total P&L:     ${total_pnl:+.0f}")
    print(f"  Win total:   ${win_pnl:+.0f}")
    print(f"  Loss total:  ${loss_pnl:+.0f}")
    print(f"Avg P&L/trade: ${total_pnl/total:+.0f}")
    print()
    print(f"Qualified days: {len(qualified_days)}")
    print(f"Kill-switch days: {len(killswitch_days)}")
    print()

    # By direction
    print("By direction:")
    for d in ['LONG', 'SHORT']:
        d_trades = [t for t in all_trades if t['direction'] == d]
        if d_trades:
            d_wins = sum(1 for t in d_trades if t['outcome'].startswith('WIN'))
            d_pnl = sum(t['pnl'] for t in d_trades)
            print(f"  {d:5}: {len(d_trades):3} trades, {d_wins}W, ${d_pnl:+.0f}")

    print()
    print("By KZ:")
    for kz in ['LondonOpen', 'NYOpen']:
        k_trades = [t for t in all_trades if t['kz'] == kz]
        if k_trades:
            k_wins = sum(1 for t in k_trades if t['outcome'].startswith('WIN'))
            k_pnl = sum(t['pnl'] for t in k_trades)
            print(f"  {kz:11}: {len(k_trades):3} trades, {k_wins}W, ${k_pnl:+.0f}")

    print()
    print("By symbol:")
    for sym in SYMBOLS:
        s_trades = [t for t in all_trades if t['symbol'] == sym]
        if s_trades:
            s_wins = sum(1 for t in s_trades if t['outcome'].startswith('WIN'))
            s_pnl = sum(t['pnl'] for t in s_trades)
            print(f"  {sym:7}: {len(s_trades):3} trades, {s_wins}W, ${s_pnl:+.0f}")

    # === AUTO WR / R:R REPORT ===
    print()
    print("="*70)
    print("AUTO WR / R:R ANALYSIS")
    print("="*70)

    def calc_rr(trades):
        """Calculate actual achieved R:R"""
        if not trades:
            return 0
        avg_win = sum(t['pnl'] for t in trades if t['pnl'] > 0) / max(1, sum(1 for t in trades if t['pnl'] > 0))
        avg_loss = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0)) / max(1, sum(1 for t in trades if t['pnl'] < 0))
        if avg_loss == 0:
            return float('inf') if avg_win > 0 else 0
        return avg_win / avg_loss

    def calc_metrics(trades, label):
        if not trades:
            return
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] < 0]
        n = len(trades)
        nw = len(wins)
        wr = nw / n * 100
        pnl = sum(t['pnl'] for t in trades)
        rr = calc_rr(trades)
        ev = (nw/n * (pnl/nw if nw else 0)) - ((n-nw)/n * (abs(sum(t['pnl'] for t in losses)/(n-nw)) if (n-nw) else 0))
        print(f"  {label:20} | N={n:3} | WR={wr:5.1f}% | P&L=${pnl:+7.0f} | R:R=1:{rr:.2f} | EV=${ev:+.1f}/trade")

    print("Overall:")
    calc_metrics(all_trades, "ALL")

    print("\nBy direction:")
    calc_metrics([t for t in all_trades if t['direction'] == 'LONG'], "LONG")
    calc_metrics([t for t in all_trades if t['direction'] == 'SHORT'], "SHORT")

    print("\nBy KZ:")
    calc_metrics([t for t in all_trades if t['kz'] == 'LondonOpen'], "LondonOpen")
    calc_metrics([t for t in all_trades if t['kz'] == 'NYOpen'], "NYOpen")

    print("\nBy symbol:")
    for sym in SYMBOLS:
        calc_metrics([t for t in all_trades if t['symbol'] == sym], sym)

    print("\nBy day:")
    for date_key in sorted(set(t['date'] for t in all_trades)):
        calc_metrics([t for t in all_trades if t['date'] == date_key], str(date_key))

    print("\nBy direction × KZ:")
    for d in ['LONG', 'SHORT']:
        for k in ['LondonOpen', 'NYOpen']:
            calc_metrics([t for t in all_trades if t['direction'] == d and t['kz'] == k], f"{d}+{k}")

    # Summary stats
    total_wins = sum(t['pnl'] for t in all_trades if t['pnl'] > 0)
    total_losses = sum(t['pnl'] for t in all_trades if t['pnl'] < 0)
    print()
    print(f"💰 Win total:  ${total_wins:+,.0f}")
    print(f"💸 Loss total: ${total_losses:+,.0f}")
    print(f"📊 Net:        ${total_wins + total_losses:+,.0f}")
    print(f"📈 Profit Factor: {abs(total_wins / total_losses) if total_losses else 'inf':.2f}")
    print(f"📈 Expectancy: ${(total_wins + total_losses) / len(all_trades):+.1f}/trade")

if __name__ == '__main__':
    run_backtest()
