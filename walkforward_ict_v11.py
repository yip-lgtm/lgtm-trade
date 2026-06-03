#!/usr/bin/env python3
"""
ICT Scanner v1.1 - Walk-Forward Optimization Framework
Tests strategy robustness across rolling time windows
Detects regime changes

Parameters optimized (simple grid):
- SWING_LOOKBACK: 10, 20, 30
- OTE_LOW: 0.55, 0.62, 0.70
- OTE_HIGH: 0.75, 0.80, 0.85
- MIN_FVG_TICKS: 5, 15, 25

= 81 combinations per window
"""

import sys
import os
import csv
import json
import itertools
from datetime import datetime
from typing import List, Dict, Tuple
from copy import deepcopy

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
        return [c for c in self.load_all(symbol) if c.datetime < cutoff_date]


class DatedProvider:
    def __init__(self, parent: HistoricalDataProvider, cutoff: str):
        self.parent = parent
        self.cutoff = cutoff

    def get_daily_data(self, symbol: str, count: int = 300) -> List[Candle]:
        data = self.parent.get_data_until(symbol, self.cutoff)
        return data[-count:] if data else []


# Core symbols (drop MCL.F - 0% OOS WR)
SYMBOLS = ['MES.F', 'MNQ.F', 'M2K.F', 'MBT.F', 'MET.F', 'MGC.F']

# Parameter grid (3^4 = 81 combos - manageable)
PARAM_GRID = {
    'SWING_LOOKBACK': [10, 20, 30],
    'OTE_LOW': [0.55, 0.62, 0.70],
    'OTE_HIGH': [0.75, 0.80, 0.85],
    'MIN_FVG_TICKS': [5, 15, 25]
}


def backtest_window(dp: HistoricalDataProvider, symbols: List[str],
                    start_date: str, end_date: str,
                    params: Dict, forward_days: int = 3) -> Dict:
    """Run backtest for date range with given params"""
    # Apply params to a fresh scanner config
    all_dates_mes = sorted(set(c.datetime[:10] for c in dp.load_all('MES.F')))
    period_dates = [d for d in all_dates_mes if start_date <= d < end_date]

    trades = []
    daily_pnl = []

    for date_str in period_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() >= 5:
            continue

        scanner = ICTScanner(DatedProvider(dp, date_str + " 23:59:59"))
        # Apply params
        scanner.SWING_LOOKBACK = params['SWING_LOOKBACK']
        scanner.OTE_LOW = params['OTE_LOW']
        scanner.OTE_HIGH = params['OTE_HIGH']
        scanner.MIN_FVG_TICKS = params['MIN_FVG_TICKS']

        day_pnl = 0
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

            # Find forward window
            future_end = date_str
            for i, d in enumerate(all_dates_mes):
                if d > date_str:
                    if i + forward_days < len(all_dates_mes):
                        future_end = all_dates_mes[i + forward_days]
                    else:
                        future_end = all_dates_mes[-1]
                    break

            trades_today = 0
            for setup in day_setups:
                if trades_today >= scanner.MAX_TRADES_PER_DAY:
                    break
                if day_pnl <= -200:
                    break

                future_data = dp.get_data_until(setup.symbol, future_end + " 23:59:59")
                if not future_data:
                    continue

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
                    else:
                        if candle.high >= setup.stop_loss:
                            hit_sl = True
                            break
                        if candle.low <= setup.tp1:
                            hit_tp1 = True
                            break

                win = hit_tp1 and not hit_sl
                pnl = 300 if win else -100
                day_pnl += pnl
                trades.append({
                    'date': date_str,
                    'sym': setup.symbol,
                    'dir': setup.direction,
                    'win': win,
                    'pnl': pnl,
                    'conf': setup.confidence
                })
                trades_today += 1
        except Exception:
            continue

        daily_pnl.append(day_pnl)

    # Calculate metrics
    if not trades:
        return {'trades': 0, 'pnl': 0, 'wr': 0, 'qualified_days': 0, 'max_dd': 0}

    wins = sum(1 for t in trades if t['win'])
    wr = wins / len(trades) * 100
    pnl = sum(t['pnl'] for t in trades)
    qualified = sum(1 for p in daily_pnl if p >= 250)

    # Max drawdown
    cum = 0
    peak = 0
    max_dd = 0
    for p in daily_pnl:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    return {
        'trades': len(trades),
        'wins': wins,
        'losses': len(trades) - wins,
        'wr': wr,
        'pnl': pnl,
        'qualified_days': qualified,
        'max_dd': max_dd,
        'avg_pnl': pnl / len(trades)
    }


def score_params(metrics: Dict) -> float:
    """
    Composite score (from user's spec):
    Score = (Total_PnL * 0.4) + (Qualified_Days * 50) - (Max_DD * 0.8)
    """
    if metrics['trades'] == 0:
        return -9999
    return (metrics['pnl'] * 0.4) + (metrics['qualified_days'] * 50) - (metrics['max_dd'] * 0.8)


def optimize_window(dp: HistoricalDataProvider, symbols: List[str],
                    train_start: str, train_end: str) -> Tuple[Dict, Dict]:
    """Find best params for training window using grid search"""
    best_params = None
    best_score = -99999
    best_metrics = None

    param_combos = list(itertools.product(
        PARAM_GRID['SWING_LOOKBACK'],
        PARAM_GRID['OTE_LOW'],
        PARAM_GRID['OTE_HIGH'],
        PARAM_GRID['MIN_FVG_TICKS']
    ))

    for sl, ol, oh, mf in param_combos:
        # Validate: OTE_LOW < OTE_HIGH
        if ol >= oh:
            continue

        params = {
            'SWING_LOOKBACK': sl,
            'OTE_LOW': ol,
            'OTE_HIGH': oh,
            'MIN_FVG_TICKS': mf
        }

        metrics = backtest_window(dp, symbols, train_start, train_end, params)
        score = score_params(metrics)

        if score > best_score:
            best_score = score
            best_params = params
            best_metrics = metrics

    return best_params, best_metrics


def main():
    dp = HistoricalDataProvider()
    for sym in SYMBOLS:
        dp.load_all(sym)

    all_dates = sorted(set(c.datetime[:10] for c in dp.load_all('MES.F')))
    data_start = all_dates[0]
    data_end = all_dates[-1]

    # WF config
    TRAIN_DAYS = 180
    TEST_DAYS = 30
    STEP_DAYS = 30

    print("=" * 70)
    print("🔬 Walk-Forward Optimization")
    print(f"   Symbols: {SYMBOLS} (MCL.F dropped - 0% OOS WR)")
    print(f"   Train: {TRAIN_DAYS}d | Test: {TEST_DAYS}d | Step: {STEP_DAYS}d")
    print("=" * 70)

    # Generate windows
    windows = []
    cursor = 0
    while cursor + TRAIN_DAYS + TEST_DAYS <= len(all_dates):
        train_start_idx = cursor
        train_end_idx = cursor + TRAIN_DAYS
        test_start_idx = train_end_idx
        test_end_idx = test_end_idx = min(test_start_idx + TEST_DAYS, len(all_dates))

        windows.append({
            'train_start': all_dates[train_start_idx],
            'train_end': all_dates[train_end_idx - 1],
            'test_start': all_dates[test_start_idx],
            'test_end': all_dates[min(test_end_idx - 1, len(all_dates) - 1)]
        })
        cursor += STEP_DAYS

    print(f"\n📅 Generated {len(windows)} walk-forward windows:")
    for i, w in enumerate(windows):
        print(f"   {i+1}. Train: {w['train_start']} → {w['train_end']} | Test: {w['test_start']} → {w['test_end']}")

    # Run WF
    wf_results = []
    for i, w in enumerate(windows):
        print(f"\n{'='*70}")
        print(f"🟦 Window {i+1}/{len(windows)}: Test {w['test_start']} → {w['test_end']}")
        print(f"{'='*70}")

        # Optimize on training window
        print(f"   Optimizing on train window ({w['train_start']} → {w['train_end']})...")
        best_params, train_metrics = optimize_window(dp, SYMBOLS, w['train_start'], w['train_end'])

        print(f"   Best params: {best_params}")
        print(f"   Train score: {score_params(train_metrics):.1f}")
        print(f"   Train: {train_metrics['trades']} trades, {train_metrics['wr']:.1f}% WR, ${train_metrics['pnl']:+,.0f}, Q={train_metrics['qualified_days']}")

        # Test on OOS window
        print(f"   Testing OOS window ({w['test_start']} → {w['test_end']})...")
        oos_metrics = backtest_window(dp, SYMBOLS, w['test_start'], w['test_end'], best_params)

        print(f"   OOS:  {oos_metrics['trades']} trades, {oos_metrics['wr']:.1f}% WR, ${oos_metrics['pnl']:+,.0f}, Q={oos_metrics['qualified_days']}, MaxDD=${oos_metrics['max_dd']:,.0f}")

        wf_results.append({
            'window': i + 1,
            'train_start': w['train_start'],
            'train_end': w['train_end'],
            'test_start': w['test_start'],
            'test_end': w['test_end'],
            'best_params': best_params,
            'train_metrics': train_metrics,
            'oos_metrics': oos_metrics
        })

    # ==================== Aggregate Results ====================
    print(f"\n{'='*70}")
    print("📊 WALK-FORWARD AGGREGATE RESULTS")
    print(f"{'='*70}")

    total_oos_trades = sum(r['oos_metrics']['trades'] for r in wf_results)
    total_oos_wins = sum(r['oos_metrics']['wins'] for r in wf_results)
    total_oos_pnl = sum(r['oos_metrics']['pnl'] for r in wf_results)
    total_oos_qualified = sum(r['oos_metrics']['qualified_days'] for r in wf_results)
    max_oos_dd = max((r['oos_metrics']['max_dd'] for r in wf_results), default=0)

    if total_oos_trades > 0:
        agg_wr = total_oos_wins / total_oos_trades * 100
        agg_avg = total_oos_pnl / total_oos_trades
    else:
        agg_wr = 0
        agg_avg = 0

    print(f"\n🟦 Total OOS Performance (across all windows):")
    print(f"   Total Trades:       {total_oos_trades}")
    print(f"   Wins/Losses:        {total_oos_wins}/{total_oos_trades - total_oos_wins}")
    print(f"   Win Rate:           {agg_wr:.1f}%")
    print(f"   Total P&L:          ${total_oos_pnl:+,.0f}")
    print(f"   Avg P&L/Trade:      ${agg_avg:+,.2f}")
    print(f"   Qualified Days:     {total_oos_qualified}")
    print(f"   Max Window DD:      ${max_oos_dd:,.0f}")

    # Per-window OOS performance
    print(f"\n📅 Per-Window OOS Performance:")
    print(f"   {'Window':<7} {'Test Period':<28} {'Trades':<7} {'WR':<7} {'P&L':<10} {'Q':<3} {'DD':<7} {'Params'}")
    print("-" * 120)
    for r in wf_results:
        m = r['oos_metrics']
        p = r['best_params']
        params_str = f"SL={p['SWING_LOOKBACK']} O={p['OTE_LOW']:.2f}-{p['OTE_HIGH']:.2f} F={p['MIN_FVG_TICKS']}"
        print(f"   {r['window']:<7} {r['test_start']} → {r['test_end']}  {m['trades']:<7} {m['wr']:<7.1f} ${m['pnl']:<+9,.0f} {m['qualified_days']:<3} ${m['max_dd']:<6,.0f} {params_str}")

    # Regime change detection
    print(f"\n🔍 Regime Change Analysis:")
    if len(wf_results) >= 2:
        # Calculate rolling OOS performance
        pnl_history = [r['oos_metrics']['pnl'] for r in wf_results]
        wr_history = [r['oos_metrics']['wr'] for r in wf_results]

        # Detect drops
        declining_windows = []
        for i in range(1, len(pnl_history)):
            if pnl_history[i] < pnl_history[i-1] - 500:  # $500 drop
                declining_windows.append(i)

        if declining_windows:
            print(f"   ⚠️  Significant OOS P&L drops detected in windows: {[w+1 for w in declining_windows]}")
        else:
            print(f"   ✅ No significant regime changes detected")

        # Most stable params (appear most often)
        from collections import Counter
        param_counter = Counter()
        for r in wf_results:
            p = r['best_params']
            key = (p['SWING_LOOKBACK'], p['OTE_LOW'], p['OTE_HIGH'], p['MIN_FVG_TICKS'])
            param_counter[key] += 1

        if param_counter:
            most_common = param_counter.most_common(3)
            print(f"   🏆 Most robust params (across windows):")
            for params, count in most_common:
                sl, ol, oh, mf = params
                print(f"      SL={sl} OTE={ol:.2f}-{oh:.2f} FVG={mf} → used in {count}/{len(wf_results)} windows")

    # Save results
    output = {
        'config': {
            'symbols': SYMBOLS,
            'train_days': TRAIN_DAYS,
            'test_days': TEST_DAYS,
            'step_days': STEP_DAYS,
            'param_grid': PARAM_GRID
        },
        'aggregate': {
            'total_trades': total_oos_trades,
            'win_rate': agg_wr,
            'total_pnl': total_oos_pnl,
            'avg_pnl': agg_avg,
            'qualified_days': total_oos_qualified,
            'max_dd': max_oos_dd
        },
        'windows': wf_results
    }
    with open('/tmp/ict_wf_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n💾 Results saved to /tmp/ict_wf_results.json")


if __name__ == "__main__":
    main()
