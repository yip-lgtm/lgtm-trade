#!/usr/bin/env python3
"""Debug backtest to find MGC/MCL bugs"""
import sys
import os
import csv
from datetime import datetime
sys.path.insert(0, '/home/node/.openclaw/workspace')

from ict_scanner_v11 import (
    ICTScanner, YahooCSVDataProvider, Candle
)


class DatedProvider:
    def __init__(self, dp, cutoff):
        self.dp = dp
        self.cutoff = cutoff
    
    def get_daily_data(self, symbol, count=300):
        all_data = self.dp.get_daily_data(symbol, count=500)
        return [c for c in all_data if c.datetime < self.cutoff][-count:]


def main():
    dp = YahooCSVDataProvider()
    scanner = ICTScanner(dp, notifier=None)
    
    symbols = ['MES.F', 'MGC.F', 'MCL.F', 'MCL.F']
    
    # Get all unique dates
    all_dates = sorted(set(c.datetime[:10] for c in dp.get_daily_data('MES.F', count=500)))
    test_dates = all_dates[-30:]  # Last 30 days
    
    print(f"Debug Backtest - last {len(test_dates)} days")
    print(f"Period: {test_dates[0]} → {test_dates[-1]}")
    print("=" * 70)
    
    for date_str in test_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() >= 5:
            continue
        
        dated_dp = DatedProvider(dp, date_str + " 23:59:59")
        scanner_dp = ICTScanner(dated_dp, notifier=None)
        
        bias = scanner_dp.get_daily_bias()
        print(f"\n{date_str} (bias={bias}):")
        
        for sym in ['MES.F', 'MGC.F', 'MCL.F']:
            data = dated_dp.get_daily_data(sym, count=300)
            if len(data) < 50:
                continue
            
            setups = scanner_dp.find_confluence_setups(data, bias, sym)
            
            if setups:
                for s in setups:
                    # Check next day outcome
                    next_idx = all_dates.index(date_str) + 1 if date_str in all_dates else None
                    if next_idx and next_idx < len(all_dates):
                        next_date = all_dates[next_idx]
                        next_data = [c for c in dp.get_daily_data(sym, count=500) if c.datetime[:10] == next_date]
                        if next_data:
                            next_close = next_data[0].close
                            win_long = next_close >= s.tp1
                            win_short = next_close <= s.tp1
                            win = win_long if s.direction == 'LONG' else win_short
                            print(f"  {sym:8s} {s.direction:5s} @ {s.entry:.2f} TP1={s.tp1:.2f} | next({next_date}) close={next_close:.2f} {'WIN' if win else 'LOSS'}")


if __name__ == "__main__":
    main()
