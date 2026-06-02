#!/usr/bin/env python3
"""
Generate trade chart for a symbol - candlestick with entry/exit markers
"""
import sys
import json
from datetime import datetime

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    import numpy as np
except ImportError:
    print("matplotlib not available, trying alternative...")
    sys.exit(1)

SYM = sys.argv[1] if len(sys.argv) > 1 else 'MCL.F'
CSV_FILE = f'{SYM}.csv'
TRADES_CSV = 'backtest_results.csv'

def main():
    # Load price data
    df = pd.read_csv(CSV_FILE, parse_dates=['Datetime'] if 'Datetime' in pd.read_csv(CSV_FILE, nrows=1).columns else None)
    if 'Datetime' in df.columns:
        df.rename(columns={'Datetime': 'datetime'}, inplace=True)
    df.set_index('datetime', inplace=True)

    # Load trades
    try:
        trades_df = pd.read_csv(TRADES_CSV)
        trades_df = trades_df[trades_df['symbol'] == SYM]
    except:
        print(f"No trades found for {SYM}")
        sys.exit(1)

    if len(trades_df) == 0:
        print(f"No trades for {SYM}")
        sys.exit(1)

    fig, ax = plt.subplots(figsize=(16, 8))

    # Plot candlesticks
    for idx in range(len(df)):
        o = df.iloc[idx]['open']
        h = df.iloc[idx]['high']
        l = df.iloc[idx]['low']
        c = df.iloc[idx]['close']
        dt = mdates.date2num(df.index[idx].to_pydatetime())

        color = '#26a69a' if c >= o else '#ef5350'
        ax.plot([dt, dt], [l, h], color=color, linewidth=0.5)
        ax.plot([dt, dt], [min(o, c), max(o, c)], color=color, linewidth=2.5)

    # Mark entries/exits
    for _, t in trades_df.iterrows():
        dt = mdates.date2num(datetime.strptime(t['date'], '%Y-%m-%d %H:%M:%S'))
        entry = t['entry']
        exit_px = t['exit']
        pnl = t['pnl']

        if t['direction'] == 'Long':
            entry_color = '#2196F3'  # Blue for long
            exit_color = '#4CAF50' if pnl > 0 else '#F44336'
            ax.annotate('▲', (dt, entry), fontsize=8, color=entry_color, ha='center')
            ax.annotate('▼', (dt, exit_px), fontsize=8, color=exit_color, ha='center')
        else:
            entry_color = '#FF9800'  # Orange for short
            exit_color = '#4CAF50' if pnl > 0 else '#F44336'
            ax.annotate('▼', (dt, entry), fontsize=8, color=entry_color, ha='center')
            ax.annotate('▲', (dt, exit_px), fontsize=8, color=exit_color, ha='center')

    # Summary stats
    total_pnl = trades_df['pnl'].sum()
    wins = len(trades_df[trades_df['pnl'] > 0])
    losses = len(trades_df[trades_df['pnl'] < 0])
    wr = wins / len(trades_df) * 100

    ax.set_title(f'{SYM} - 60 Day Trade Map\nTotal PnL: ${total_pnl:,.0f} | Win Rate: {wr:.1f}% | Trades: {len(trades_df)}', fontsize=14, fontweight='bold')
    ax.set_ylabel('Price', fontsize=12)
    ax.set_xlabel('Date', fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.xticks(rotation=45)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_file = f'trade_chart_{SYM.replace(".","")}.png'
    plt.savefig(out_file, dpi=120)
    print(f"✅ Saved: {out_file}")
    return out_file

if __name__ == '__main__':
    main()
