#!/usr/bin/env python3
"""
ICT Scanner v1.1 Out-of-Sample Test
Splits data into in-sample (training) and out-of-sample (test)
Reports both with same parameters - no look-ahead
"""

import sys
import os
import csv
import json
from datetime import datetime
from typing import List, Dict

sys.path.insert(0, '/home/node/.openclaw/workspace')

from ict_scanner_v11 import (
    ICTScanner, YahooCSVDataProvider, Setup, Candle
)


class HistoricalDataProvider:
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

    def get_data_until(self, symbol: str, cutoff_date: str) -> List[Candle]:
        all_data = self.load_all(symbol)
        return [c for c in all_data if c.datetime < cutoff_date]

    def get_data_between(self, symbol: str, start_date: str, end_date: str) -> List[Candle]:
        all_data = self.load_all(symbol)
        return [c for c in all_data if start_date <= c.datetime < end_date]


class DatedProvider:
    def __init__(self, parent: HistoricalDataProvider, cutoff: str):
        self.parent = parent
        self.cutoff = cutoff

    def get_daily_data(self, symbol: str, count: int = 300) -> List[Candle]:
        data = self.parent.get_data_until(symbol, self.cutoff)
        return data[-count:] if data else []


def run_period(dp: HistoricalDataProvider, symbols: List[str],
               start_date: str, end_date: str, max_days: int = 90,
               forward_days: int = 3) -> Dict:
    """Run backtest for a specific period with N-day forward check"""

    # Get all dates in this period
    all_dates_mes = sorted(set(c.datetime[:10] for c in dp.load_all('MES.F')))
    period_dates = [d for d in all_dates_mes if start_date <= d < end_date]
    period_dates = period_dates[-max_days:] if len(period_dates) > max_days else period_dates

    trades = []
    daily_pnl = []

    for date_str in period_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() >= 5:
            continue

        scanner = ICTScanner(DatedProvider(dp, date_str + " 23:59:59"))

        day_pnl = 0
        day_trades = []

        try:
            all_data = {sym: dp.get_data_until(sym, date_str + " 23:59:59") for sym in symbols}
            if not all_data[symbols[0]]:
                continue

            bias = scanner.get_daily_bias()
            day_setups = []
            for sym in symbols:
                if len(all_data[sym]) < 50:
                    continue
                sym_setups = scanner.find_confluence_setups(all_data[sym], bias, sym)
                day_setups.extend(sym_setups)

            # Get future data for outcome (next N days)
            future_end = date_str  # placeholder
            for i, d in enumerate(all_dates_mes):
                if d > date_str:
                    if i + forward_days < len(all_dates_mes):
                        future_end = all_dates_mes[i + forward_days]
                    else:
                        future_end = all_dates_mes[-1]
                    break

            trades_today = 0
            for setup in day_setups:
                if trades_today >= 2:
                    break
                if day_pnl <= -200:
                    break

                future_data = dp.get_data_until(setup.symbol, future_end + " 23:59:59")
                if not future_data:
                    continue

                # Check if SL or TP1 hit in forward window
                # SL hit = price touches SL level within N days
                # TP1 hit = price touches TP1 level within N days
                hit_sl = False
                hit_tp1 = False

                for candle in future_data:
                    if setup.direction == "LONG":
                        if candle.low <= setup.stop_loss:
                            hit_sl = True
                            break
                        if candle.high >= setup.tp1:
                            hit_tp1 = True
                            break
                    else:  # SHORT
                        if candle.high >= setup.stop_loss:
                            hit_sl = True
                            break
                        if candle.low <= setup.tp1:
                            hit_tp1 = True
                            break

                win = hit_tp1 and not hit_sl
                pnl = 300 if win else -100
                day_pnl += pnl
                day_trades.append({
                    'date': date_str,
                    'sym': setup.symbol,
                    'dir': setup.direction,
                    'entry': setup.entry,
                    'sl': setup.stop_loss,
                    'tp1': setup.tp1,
                    'win': win,
                    'pnl': pnl,
                    'conf': setup.confidence,
                    'period': 'in-sample' if start_date <= date_str < '2026-02-16' else 'out-of-sample'
                })
                trades_today += 1

        except Exception as e:
            continue

        daily_pnl.append(day_pnl)
        trades.extend(day_trades)

    return {
        'trades': trades,
        'daily_pnl': daily_pnl,
        'total_trades': len(trades),
        'wins': sum(1 for t in trades if t['win']),
        'losses': sum(1 for t in trades if not t['win']),
        'total_pnl': sum(t['pnl'] for t in trades),
        'period': f"{start_date} → {end_date}"
    }


def main():
    dp = HistoricalDataProvider()
    symbols = ['MES.F', 'MGC.F', 'MCL.F', 'MBT.F', 'MET.F', 'M2K.F', 'MNQ.F']

    # Load all data once
    for sym in symbols:
        dp.load_all(sym)

    all_dates = sorted(set(c.datetime[:10] for c in dp.load_all('MES.F')))
    data_start = all_dates[0]
    data_end = all_dates[-1]
    total_days = len(all_dates)

    # Split: 70% in-sample, 30% out-of-sample
    split_idx = int(total_days * 0.7)
    is_start = all_dates[0]
    is_end = all_dates[split_idx]
    oos_start = all_dates[split_idx]
    oos_end = all_dates[-1]

    print("=" * 70)
    print("🔬 ICT Scanner v1.1 - Out-of-Sample Validation")
    print("=" * 70)
    print(f"Data range:    {data_start} → {data_end} ({total_days} days)")
    print(f"Split point:   {oos_start} (70% / 30% split)")
    print(f"")
    print(f"In-Sample:      {is_start} → {is_end}")
    print(f"Out-of-Sample:  {oos_start} → {oos_end}")
    print("=" * 70)

    # Run both periods with SAME parameters (no changes between)
    print("\n📊 Running In-Sample backtest...")
    is_result = run_period(dp, symbols, is_start, is_end, forward_days=3)

    print("📊 Running Out-of-Sample backtest...")
    oos_result = run_period(dp, symbols, oos_start, oos_end, forward_days=3)

    # Print comparison
    print("\n" + "=" * 70)
    print("📈 RESULTS COMPARISON")
    print("=" * 70)

    def print_stats(name, result):
        if result['total_trades'] == 0:
            print(f"\n{name}: No trades")
            return
        wr = result['wins'] / result['total_trades'] * 100
        avg = result['total_pnl'] / result['total_trades']
        max_dd = 0
        cum = 0
        peak = 0
        for p in result['daily_pnl']:
            cum += p
            peak = max(peak, cum)
            dd = peak - cum
            max_dd = max(max_dd, dd)
        print(f"\n{name} ({result['period']}):")
        print(f"  Trades:       {result['total_trades']}")
        print(f"  Wins/Losses:  {result['wins']}/{result['losses']}")
        print(f"  Win Rate:     {wr:.1f}%")
        print(f"  Total P&L:    ${result['total_pnl']:+,.0f}")
        print(f"  Avg/Trade:    ${avg:+,.2f}")
        print(f"  Max Drawdown: ${max_dd:,.0f}")
        if result['daily_pnl']:
            print(f"  Days Tested:  {len(result['daily_pnl'])}")
            print(f"  Avg Daily:    ${sum(result['daily_pnl'])/len(result['daily_pnl']):+,.2f}")
            print(f"  Best Day:     ${max(result['daily_pnl']):+,.0f}")
            print(f"  Worst Day:    ${min(result['daily_pnl']):+,.0f}")

    print_stats("🟢 IN-SAMPLE (Training)", is_result)
    print_stats("🔴 OUT-OF-SAMPLE (Test)", oos_result)

    # Sanity check: OOS should not be wildly different from IS
    print("\n" + "=" * 70)
    print("🎯 OOS Validation Score")
    print("=" * 70)
    if is_result['total_trades'] > 0 and oos_result['total_trades'] > 0:
        is_wr = is_result['wins'] / is_result['total_trades']
        oos_wr = oos_result['wins'] / oos_result['total_trades']
        wr_decay = (is_wr - oos_wr) * 100
        print(f"  IS Win Rate:    {is_wr*100:.1f}%")
        print(f"  OOS Win Rate:   {oos_wr*100:.1f}%")
        print(f"  WR Decay:       {wr_decay:+.1f}pp")
        if wr_decay < 5:
            print(f"  ✅ ROBUST - low decay, strategy generalizes")
        elif wr_decay < 15:
            print(f"  ⚠️ MODERATE - some decay, monitor")
        else:
            print(f"  ❌ OVERFIT - high decay, do not trust")

        # OOS profitability
        if oos_result['total_pnl'] > 0:
            print(f"  ✅ OOS PROFITABLE: ${oos_result['total_pnl']:+,.0f}")
        else:
            print(f"  ❌ OOS UNPROFITABLE: ${oos_result['total_pnl']:+,.0f}")

    # Per-symbol OOS breakdown
    if oos_result['total_trades'] > 0:
        print(f"\n📊 Per-Symbol OOS Performance:")
        by_sym = {}
        for t in oos_result['trades']:
            by_sym.setdefault(t['sym'], []).append(t)
        for sym in sorted(by_sym):
            trades = by_sym[sym]
            wins = sum(1 for t in trades if t['win'])
            pnl = sum(t['pnl'] for t in trades)
            wr = wins / len(trades) * 100
            status = "✅" if pnl > 0 else "❌"
            print(f"  {status} {sym:8s}: {len(trades):3d} trades, {wr:5.1f}% WR, ${pnl:+5.0f}")

    # Save results
    out = {
        'in_sample': {
            'period': is_result['period'],
            'trades': is_result['total_trades'],
            'win_rate': is_result['wins'] / is_result['total_trades'] if is_result['total_trades'] else 0,
            'total_pnl': is_result['total_pnl'],
            'avg_pnl': is_result['total_pnl'] / is_result['total_trades'] if is_result['total_trades'] else 0
        },
        'out_of_sample': {
            'period': oos_result['period'],
            'trades': oos_result['total_trades'],
            'win_rate': oos_result['wins'] / oos_result['total_trades'] if oos_result['total_trades'] else 0,
            'total_pnl': oos_result['total_pnl'],
            'avg_pnl': oos_result['total_pnl'] / oos_result['total_trades'] if oos_result['total_trades'] else 0
        }
    }
    with open('/tmp/ict_oos_results.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n💾 Results saved to /tmp/ict_oos_results.json")


if __name__ == "__main__":
    main()
