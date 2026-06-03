#!/usr/bin/env python3
"""
ICT Scanner v1.1 Backtest
Runs scanner on historical data day-by-day
Tracks signals, P&L, win rate
"""

import sys
import os
import csv
import json
from datetime import datetime, timedelta
from typing import List, Dict

sys.path.insert(0, '/home/node/.openclaw/workspace')

from ict_scanner_v11 import (
    ICTScanner, YahooCSVDataProvider, Setup, Candle
)


class HistoricalDataProvider:
    """Provides historical data up to a specific date for backtesting"""

    def __init__(self, base_dir: str = "/home/node/.openclaw/workspace"):
        self.base_dir = base_dir
        self.cache: Dict[str, List[Candle]] = {}

    def load_all(self, symbol: str) -> List[Candle]:
        if symbol in self.cache:
            return self.cache[symbol]
        path = os.path.join(self.base_dir, f"{symbol}.csv")
        if not os.path.exists(path):
            return []
        candles = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    candles.append(Candle(
                        datetime=row['datetime'],
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=float(row.get('volume', 0))
                    ))
                except (KeyError, ValueError):
                    continue
        self.cache[symbol] = candles
        return candles

    def get_daily_data(self, symbol: str, count: int = 300) -> List[Candle]:
        """Return last `count` candles"""
        all_data = self.load_all(symbol)
        return all_data[-count:]

    def get_data_until(self, symbol: str, cutoff_date: str) -> List[Candle]:
        """Return all candles before cutoff_date"""
        all_data = self.load_all(symbol)
        return [c for c in all_data if c.datetime < cutoff_date]


def backtest(days: int = 30, symbols: List[str] = None):
    """Run backtest over last N days"""
    if symbols is None:
        symbols = ['MES.F', 'MNQ.F', 'M2K.F', 'MCL.F', 'MBT.F', 'MET.F', 'MGC.F']

    # Create scanner with mock notifier
    def mock_notifier(msg):
        pass

    dp = HistoricalDataProvider()

    # Load all data once
    for sym in symbols:
        dp.load_all(sym)

    if not symbols or not dp.load_all(symbols[0]):
        print("❌ No data available")
        return

    # Get all dates from MES.F (assume it has the most data)
    all_dates = sorted(set(c.datetime[:10] for c in dp.load_all(symbols[0])))

    # Backtest last N days
    test_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    print(f"🔬 ICT Scanner v1.1 Backtest")
    print(f"   Days: {len(test_dates)} ({test_dates[0]} → {test_dates[-1]})")
    print(f"   Symbols: {len(symbols)}")
    print("=" * 60)

    # Track results
    all_trades = []
    daily_pnl = []
    account_state = {
        'balance': 50000,
        'total_pnl': 0,
        'consecutive_losses': 0
    }

    POINT_VALUE = ICTScanner.POINT_VALUE

    for date_str in test_dates:
        # Skip weekends
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() >= 5:
            continue

        # Set up scanner with custom data provider that limits to this date
        class DatedProvider:
            def __init__(self, parent, cutoff):
                self.parent = parent
                self.cutoff = cutoff
            def get_daily_data(self, symbol, count=300):
                data = self.parent.get_data_until(symbol, self.cutoff)
                return data[-count:] if data else []

        scanner = ICTScanner(DatedProvider(dp, date_str + " 23:59:59"))

        # For each kill zone (simulate)
        day_pnl = 0
        day_trades = []

        for kz in ["LondonOpen", "NYOpen"]:
            # Run scanner
            try:
                all_data = {sym: dp.get_data_until(sym, date_str + " 23:59:59") for sym in symbols}
                if not all_data[symbols[0]]:
                    continue

                # Get bias
                bias = scanner.get_daily_bias()

                setups = []
                for sym in symbols:
                    if len(all_data[sym]) < 50:
                        continue
                    setups.extend(scanner.find_confluence_setups(all_data[sym], bias, sym))

                # Simulate trade
                for setup in setups[:2]:  # Max 2 per KZ
                    # Find next day's data
                    next_dates = [d for d in all_dates if d > date_str]
                    if not next_dates:
                        continue
                    next_date = next_dates[0]

                    next_data = dp.get_data_until(sym, next_date + " 23:59:59")
                    if not next_data:
                        continue

                    next_close = next_data[-1].close

                    # Determine outcome
                    if setup.direction == "LONG":
                        # Win if next close > entry (target 1:3 R:R)
                        win = next_close >= setup.tp1
                    else:
                        win = next_close <= setup.tp1

                    pnl = 600 if win else -100
                    day_pnl += pnl
                    account_state['total_pnl'] += pnl
                    day_trades.append({
                        'date': date_str,
                        'kz': kz,
                        'sym': setup.symbol,
                        'dir': setup.direction,
                        'entry': setup.entry,
                        'sl': setup.stop_loss,
                        'tp1': setup.tp1,
                        'win': win,
                        'pnl': pnl,
                        'conf': setup.confidence
                    })

                    if not win:
                        account_state['consecutive_losses'] += 1
                    else:
                        account_state['consecutive_losses'] = 0

                    # Daily kill switch
                    if day_pnl <= -200:
                        break

            except Exception as e:
                continue

        daily_pnl.append(day_pnl)
        all_trades.extend(day_trades)

    # ==================== Results ====================
    print(f"\n📊 Backtest Results")
    print("=" * 60)
    print(f"Days tested:   {len(daily_pnl)}")
    print(f"Total trades:  {len(all_trades)}")
    if all_trades:
        wins = sum(1 for t in all_trades if t['win'])
        losses = len(all_trades) - wins
        print(f"Wins:          {wins}")
        print(f"Losses:        {losses}")
        print(f"Win Rate:      {wins/len(all_trades)*100:.1f}%")
        print(f"Total P&L:     ${sum(t['pnl'] for t in all_trades):+,.0f}")
        print(f"Avg P&L/trade: ${sum(t['pnl'] for t in all_trades)/len(all_trades):+,.2f}")

    # Daily stats
    if daily_pnl:
        print(f"\nDaily P&L:")
        print(f"  Avg:    ${sum(daily_pnl)/len(daily_pnl):+,.2f}")
        print(f"  Max:    ${max(daily_pnl):+,.0f}")
        print(f"  Min:    ${min(daily_pnl):+,.0f}")
        print(f"  Days >0: {sum(1 for p in daily_pnl if p > 0)}")
        print(f"  Days <0: {sum(1 for p in daily_pnl if p < 0)}")
        print(f"  Days =0: {sum(1 for p in daily_pnl if p == 0)}")

    # Per symbol
    if all_trades:
        print(f"\nPer Symbol:")
        by_sym = {}
        for t in all_trades:
            if t['sym'] not in by_sym:
                by_sym[t['sym']] = []
            by_sym[t['sym']].append(t)
        for sym, trades in sorted(by_sym.items()):
            wins = sum(1 for t in trades if t['win'])
            pnl = sum(t['pnl'] for t in trades)
            print(f"  {sym:8s}: {len(trades):3d} trades, {wins/len(trades)*100:5.1f}% WR, ${pnl:+5.0f}")

    # Save to file
    out_path = '/tmp/ict_scanner_v11_backtest.json'
    with open(out_path, 'w') as f:
        json.dump({
            'total_trades': len(all_trades),
            'wins': sum(1 for t in all_trades if t['win']),
            'losses': sum(1 for t in all_trades if not t['win']),
            'win_rate': sum(1 for t in all_trades if t['win']) / len(all_trades) if all_trades else 0,
            'total_pnl': sum(t['pnl'] for t in all_trades),
            'trades': all_trades[:50]  # Save first 50
        }, f, indent=2, default=str)
    print(f"\n💾 Results saved to {out_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--symbols', nargs='+', default=None)
    args = parser.parse_args()
    backtest(args.days, args.symbols)
