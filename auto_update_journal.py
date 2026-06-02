#!/usr/bin/env python3
"""
Auto Update Journal - Updated for LSTM 1HR System
Runs after each KZ to update journal with current P&L
"""
import json
import subprocess
import pandas as pd
from datetime import datetime
import os

POINT_VALUE = {
    'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MYM.F': 0.5,
    'M6E.F': 12500, 'M6A.F': 10000, 'MCL.F': 100,
    'MBT.F': 0.1, 'MET.F': 0.1, 'MGC.F': 10, 'SIL.F': 5,
}
TICK_SIZE = {
    'MES.F': 0.25, 'MNQ.F': 0.25, 'M2K.F': 0.5, 'MYM.F': 1.0,
    'M6E.F': 0.00005, 'M6A.F': 0.0001, 'MCL.F': 0.01,
    'MBT.F': 1.0, 'MET.F': 0.5, 'MGC.F': 0.1, 'SIL.F': 0.005,
}
CONTRACTS = {
    'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
    'M6E.F': 2, 'M6A.F': 2, 'MCL.F': 1,
    'MBT.F': 1, 'MET.F': 1, 'MGC.F': 2, 'SIL.F': 1,
}

def fetch_prices():
    """Fetch current prices using node"""
    try:
        result = subprocess.run(['/usr/local/bin/node', '/home/node/.openclaw/workspace/fetch_prices.js'],
                              capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error fetching prices: {e}")
        return {}

def load_signals(signal_file='/tmp/lstm_signals.json'):
    """Load signals from LSTM JSON"""
    if os.path.exists(signal_file):
        with open(signal_file) as f:
            return json.load(f)
    return None

def calc_pnl(sym, direction, entry, sl, tp1, close_price, contracts):
    """Calculate P&L for a trade"""
    pv = POINT_VALUE.get(sym, 5)
    tick = TICK_SIZE.get(sym, 0.01)
    contracts = contracts or CONTRACTS.get(sym, 2)
    
    # SL in price units
    sl_price = (200 / (pv * contracts)) * tick
    tp1_price = sl_price * 3
    tp2_price = sl_price * 6
    
    pnl = 0
    exit_price = close_price
    
    if direction == 'short':
        if close_price >= entry + sl_price:
            pnl = -200 * contracts
            exit_price = entry + sl_price  # SL hit
        elif close_price <= entry - tp1_price:
            pnl = 600 * contracts  # TP1 hit
            exit_price = entry - tp1_price
        elif close_price <= entry - tp2_price:
            pnl = 1200 * contracts  # TP2 hit
            exit_price = entry - tp2_price
        else:
            pnl = 0  # Still open
    else:  # long
        if close_price <= entry - sl_price:
            pnl = -200 * contracts
            exit_price = entry - sl_price  # SL hit
        elif close_price >= entry + tp1_price:
            pnl = 600 * contracts  # TP1 hit
            exit_price = entry + tp1_price
        elif close_price >= entry + tp2_price:
            pnl = 1200 * contracts  # TP2 hit
            exit_price = entry + tp2_price
        else:
            pnl = 0  # Still open
    
    return pnl, exit_price

def main():
    kz = 'London' if datetime.utcnow().hour < 12 else 'NY'
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    print(f"[{datetime.utcnow().isoformat()}] Journal Update START - {kz}")
    
    # Load signals
    signals_data = load_signals()
    if not signals_data or not signals_data.get('signals'):
        print("No signals found")
        return
    
    # Fetch current prices
    prices = fetch_prices()
    print(f"Current prices: {len(prices)} symbols")
    
    # Journal file
    journal_file = '/home/node/.openclaw/workspace/live_trading_journal.csv'
    
    # Load or create journal
    if os.path.exists(journal_file):
        df = pd.read_csv(journal_file)
    else:
        df = pd.DataFrame(columns=['date','killzone','symbol','direction','entry_price','sl','tp1','contracts','close_price','signal_est_pnl'])
    
    # Check for duplicates - remove existing entries for same KZ today
    existing_mask = ~((df['date'] == today) & (df['killzone'] == kz))
    df = df[existing_mask].copy()
    print(f"Removed {len(df) - len(df[existing_mask])} duplicate entries for {today} {kz}")
    
    # Process each signal
    new_entries = []
    for sym, sig in signals_data['signals'].items():
        ticker = sym.replace('.F', '=F')
        close = prices.get(ticker)
        
        entry = sig['entry']
        sl = sig['sl']
        tp1 = sig['tp1']
        direction = sig['direction']
        contracts = sig.get('contracts', CONTRACTS.get(sym, 2))
        
        # Calculate P&L
        if close is not None:
            pnl, exit_price = calc_pnl(sym, direction, entry, sl, tp1, close, contracts)
        else:
            pnl, exit_price = 0, None
        
        new_entries.append({
            'date': today,
            'killzone': kz,
            'symbol': sym,
            'direction': direction,
            'entry_price': entry,
            'sl': sl,
            'tp1': tp1,
            'contracts': contracts,
            'close_price': exit_price,
            'signal_est_pnl': pnl
        })
        
        status = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "OPEN")
        print(f"  {sym}: {direction} @{entry} | Close={close} | P&L=${pnl} [{status}]")
    
    # Add to journal
    new_df = pd.DataFrame(new_entries)
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(journal_file, index=False)
    
    # Summary
    today_df = df[df['date'] == today]
    today_total = today_df['signal_est_pnl'].sum()
    today_trades = len(today_df)
    wins = len(today_df[today_df['signal_est_pnl'] > 0])
    losses = len(today_df[today_df['signal_est_pnl'] < 0])
    open_trades = len(today_df[today_df['signal_est_pnl'] == 0])
    win_rate = wins / today_trades * 100 if today_trades > 0 else 0
    
    print(f"\n=== {today} {kz} KZ SUMMARY ===")
    print(f"Trades: {today_trades} | Wins: {wins} | Losses: {losses} | Open: {open_trades}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total P&L: ${int(today_total)}")
    
    # Generate daily summary
    generate_daily_summary()

def generate_daily_summary():
    """Generate daily summary with cumulative P&L and win rate"""
    journal_file = '/home/node/.openclaw/workspace/live_trading_journal.csv'
    if not os.path.exists(journal_file):
        return
    
    df = pd.read_csv(journal_file)
    
    # Calculate wins/losses per date
    wins = df[df['signal_est_pnl'] > 0].groupby('date').size().reset_index(name='wins')
    losses = df[df['signal_est_pnl'] < 0].groupby('date').size().reset_index(name='losses')
    
    daily = df.groupby('date').agg({
        'signal_est_pnl': 'sum',
        'symbol': 'count'
    }).reset_index()
    daily.columns = ['date', 'pnl', 'trades']
    daily = daily.merge(wins, on='date', how='left')
    daily = daily.merge(losses, on='date', how='left')
    daily['wins'] = daily['wins'].fillna(0).astype(int)
    daily['losses'] = daily['losses'].fillna(0).astype(int)
    daily['win_rate'] = (daily['wins'] / daily['trades'] * 100).round(1)
    daily['cumulative_pnl'] = daily['pnl'].cumsum()
    
    daily.to_csv('/home/node/.openclaw/workspace/journal_daily_summary.csv', index=False)
    
    print("\n📊 DAILY CUMULATIVE SUMMARY:")
    print("=" * 70)
    for _, row in daily.iterrows():
        emoji = "🟢" if row['pnl'] > 0 else ("🔴" if row['pnl'] < 0 else "⚪")
        print(f"{row['date']} | {row['trades']} trades | WR={row['win_rate']:.1f}% | {emoji}${int(row['pnl'])} | Cumulative: ${int(row['cumulative_pnl'])}")

if __name__ == '__main__':
    main()