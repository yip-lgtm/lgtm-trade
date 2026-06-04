#!/usr/bin/env python3
"""
ICT Scanner v1.2 - Daily Report + Auto-Iteration
- Rolling 7-day metrics
- Symbol filtering (auto-suspend poor performers)
- Win rate trending
- Pass notification
- Auto-suggestions based on performance
"""
import sys
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

SETTLED_FILE = '/tmp/ict_settled_trades.jsonl'
DAILY_STATS_FILE = '/tmp/ict_daily_stats.json'
ROLLING_METRICS_FILE = '/tmp/ict_rolling_metrics.json'
SUSPENDED_SYMBOLS_FILE = '/tmp/ict_suspended_symbols.json'
SUGGESTIONS_FILE = '/tmp/ict_suggestions.json'
ALERT_LOG_FILE = '/tmp/ict_alerts.json'

# Pass criteria
PROFIT_TARGET = 3000
QUALIFIED_DAYS_TARGET = 5
SUSPEND_LOSS_THRESHOLD = 5  # 5 consecutive losses
LOW_WR_THRESHOLD = 45.0  # 7-day WR below this triggers suggestion
LOOKBACK_DAYS = 7


def load_all_trades():
    """Load all settled trades"""
    if not os.path.exists(SETTLED_FILE):
        return []
    trades = []
    with open(SETTLED_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except:
                    continue
    return trades


def compute_rolling_metrics(days=LOOKBACK_DAYS):
    """Compute rolling N-day metrics: WR, P&L, profit factor, best/worst symbol"""
    trades = load_all_trades()
    if not trades:
        return None

    # Filter to last N days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    recent = [t for t in trades if t.get('date', '') >= cutoff and t.get('outcome') in ('WIN_TP1', 'WIN_TP2', 'LOSS')]

    if not recent:
        return None

    wins = [t for t in recent if t['outcome'].startswith('WIN')]
    losses = [t for t in recent if t['outcome'] == 'LOSS']

    total_pnl = sum(t.get('pnl', 0) for t in recent)
    win_pnl = sum(t.get('pnl', 0) for t in wins)
    loss_pnl = sum(t.get('pnl', 0) for t in losses)
    profit_factor = abs(win_pnl / loss_pnl) if loss_pnl else float('inf')
    wr = len(wins) / len(recent) * 100

    # Per-symbol breakdown
    by_symbol = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0, 'trades': []})
    for t in recent:
        sym = t['symbol']
        by_symbol[sym]['trades'].append(t)
        if t['outcome'].startswith('WIN'):
            by_symbol[sym]['wins'] += 1
        else:
            by_symbol[sym]['losses'] += 1
        by_symbol[sym]['pnl'] += t.get('pnl', 0)

    # Best/worst symbols
    sym_rankings = [(sym, data['pnl'], data['wins'] / (data['wins'] + data['losses']) * 100 if (data['wins'] + data['losses']) else 0, data['losses'])
                    for sym, data in by_symbol.items()]
    sym_rankings.sort(key=lambda x: x[1], reverse=True)

    best_symbol = sym_rankings[0] if sym_rankings else None
    worst_symbol = sym_rankings[-1] if sym_rankings else None

    return {
        'period_days': days,
        'cutoff_date': cutoff,
        'total_trades': len(recent),
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'total_pnl': total_pnl,
        'win_pnl': win_pnl,
        'loss_pnl': loss_pnl,
        'profit_factor': profit_factor,
        'best_symbol': {
            'name': best_symbol[0],
            'pnl': best_symbol[1],
            'wr': best_symbol[2],
            'losses': best_symbol[3]
        } if best_symbol else None,
        'worst_symbol': {
            'name': worst_symbol[0],
            'pnl': worst_symbol[1],
            'wr': worst_symbol[2],
            'losses': worst_symbol[3]
        } if worst_symbol else None,
        'all_symbols': {sym: {'pnl': data['pnl'], 'wr': (data['wins']/(data['wins']+data['losses'])*100) if (data['wins']+data['losses']) else 0, 'trades': data['wins']+data['losses']} for sym, data in by_symbol.items()},
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


def check_symbol_filtering():
    """Auto-suspend symbols with >= 5 consecutive losses in recent trades"""
    trades = load_all_trades()
    if not trades:
        return []

    # Sort by date+time
    sorted_trades = sorted(trades, key=lambda t: t.get('signal_time', ''))

    # Track consecutive losses per symbol
    consec_losses = defaultdict(int)
    max_consec = defaultdict(int)
    suspended = []

    for t in sorted_trades:
        if t.get('outcome') not in ('WIN_TP1', 'WIN_TP2', 'LOSS'):
            continue
        sym = t['symbol']
        if t['outcome'] == 'LOSS':
            consec_losses[sym] += 1
            max_consec[sym] = max(max_consec[sym], consec_losses[sym])
        else:
            consec_losses[sym] = 0

    # Suspend if max consecutive losses >= threshold
    for sym, count in max_consec.items():
        if count >= SUSPEND_LOSS_THRESHOLD:
            suspended.append({'symbol': sym, 'reason': f'{count} consecutive losses', 'suspended_at': datetime.now(timezone.utc).isoformat()})

    # Save suspended list
    with open(SUSPENDED_SYMBOLS_FILE, 'w') as f:
        json.dump(suspended, f, indent=2)

    return suspended


def generate_suggestions(rolling):
    """Generate auto-suggestions based on rolling metrics"""
    if not rolling:
        return []

    suggestions = []

    # 1. Low WR - suggest tightening
    if rolling['wr'] < LOW_WR_THRESHOLD:
        suggestions.append({
            'type': 'low_wr',
            'severity': 'high',
            'message': f"7-day WR is {rolling['wr']:.1f}% (below {LOW_WR_THRESHOLD}%). Consider tightening OTE range or strengthening FVG filter.",
        })

    # 2. Low profit factor
    if rolling['profit_factor'] < 1.2:
        suggestions.append({
            'type': 'low_pf',
            'severity': 'high',
            'message': f"7-day profit factor is {rolling['profit_factor']:.2f} (below 1.2). Strategy may need adjustment.",
        })

    # 3. Symbol suspension recommendation
    if rolling['worst_symbol'] and rolling['worst_symbol']['pnl'] < -200:
        suggestions.append({
            'type': 'symbol_suspend',
            'severity': 'high',
            'message': f"Suspend {rolling['worst_symbol']['name']} (P&L ${rolling['worst_symbol']['pnl']:.0f}, {rolling['worst_symbol']['losses']} losses)",
        })

    # 4. Strong performer
    if rolling['best_symbol'] and rolling['best_symbol']['pnl'] > 200:
        suggestions.append({
            'type': 'symbol_focus',
            'severity': 'info',
            'message': f"Focus on {rolling['best_symbol']['name']} (P&L +${rolling['best_symbol']['pnl']:.0f}, {rolling['best_symbol']['wr']:.0f}% WR)",
        })

    with open(SUGGESTIONS_FILE, 'w') as f:
        json.dump(suggestions, f, indent=2)

    return suggestions


def check_pass_notification(daily_stats):
    """Check if pass criteria is met"""
    if not daily_stats:
        return None

    qualified_days = sum(1 for d in daily_stats.values() if d.get('qualified_day'))
    total_profit = sum(d.get('pnl', 0) for d in daily_stats.values())

    if qualified_days >= QUALIFIED_DAYS_TARGET and total_profit >= PROFIT_TARGET:
        return {
            'type': 'pass',
            'qualified_days': qualified_days,
            'total_profit': total_profit,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
        }
    return None


def generate_full_daily_report(today_str=None):
    """Generate complete daily report per spec v1.2"""
    today_str = today_str or datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Load all components
    rolling = compute_rolling_metrics(7)
    daily_stats = {}
    if os.path.exists(DAILY_STATS_FILE):
        with open(DAILY_STATS_FILE) as f:
            daily_stats = json.load(f)

    today_stats = daily_stats.get(today_str, {})
    suspended = check_symbol_filtering()
    suggestions = generate_suggestions(rolling) if rolling else []
    pass_alert = check_pass_notification(daily_stats)

    # Build report
    report = {
        'date': today_str,
        'today': {
            'qualified_day': today_stats.get('qualified_day', False),
            'daily_pnl': today_stats.get('pnl', 0),
            'trades': today_stats.get('total_trades', 0),
            'wins': today_stats.get('wins', 0),
            'losses': today_stats.get('losses', 0),
            'wr': today_stats.get('wr', 0),
            'kill_switch': today_stats.get('kill_switch', False),
            'long_pnl': today_stats.get('long_pnl', 0),
            'short_pnl': today_stats.get('short_pnl', 0),
        },
        'cumulative': {
            'total_qualified_days': sum(1 for d in daily_stats.values() if d.get('qualified_day')),
            'current_profit': sum(d.get('pnl', 0) for d in daily_stats.values()),
            'trading_days': len(daily_stats),
            'target': PROFIT_TARGET,
            'progress_pct': min(100, sum(d.get('pnl', 0) for d in daily_stats.values()) / PROFIT_TARGET * 100),
        },
        'rolling_7d': rolling,
        'suspended_symbols': suspended,
        'suggestions': suggestions,
        'pass_alert': pass_alert,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }

    # Save report
    report_file = f'/tmp/ict_report_{today_str}.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)

    # Save alert
    if pass_alert or any(s['severity'] == 'high' for s in suggestions):
        alerts = []
        if os.path.exists(ALERT_LOG_FILE):
            with open(ALERT_LOG_FILE) as f:
                try:
                    alerts = json.load(f)
                except:
                    alerts = []
        if pass_alert:
            alerts.append(pass_alert)
        for s in suggestions:
            if s['severity'] == 'high':
                alerts.append(s)
        with open(ALERT_LOG_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)

    return report


def format_telegram_report(report):
    """Format report for Telegram"""
    lines = []
    lines.append(f"📊 <b>ICT Daily Report - {report['date']}</b>")
    lines.append("")

    today = report['today']
    cum = report['cumulative']
    roll = report['rolling_7d']

    # Today
    qual = "🎯" if today['qualified_day'] else "  "
    kill = "🛑" if today['kill_switch'] else "  "
    lines.append(f"<b>TODAY</b>")
    lines.append(f"{qual}{kill} P&L: <b>${today['daily_pnl']:+.0f}</b> | WR: {today['wr']:.0f}% | {today['wins']}W/{today['losses']}L")
    lines.append(f"   L: ${today['long_pnl']:+.0f}  S: ${today['short_pnl']:+.0f}  Trades: {today['trades']}")
    lines.append("")

    # Cumulative
    lines.append(f"<b>CUMULATIVE</b>")
    lines.append(f"Qualified days: {cum['total_qualified_days']}/{QUALIFIED_DAYS_TARGET}")
    lines.append(f"Profit: ${cum['current_profit']:+.0f} / ${PROFIT_TARGET} ({cum['progress_pct']:.0f}%)")
    bar = "▓" * int(cum['progress_pct']/10) + "░" * (10 - int(cum['progress_pct']/10))
    lines.append(f"  [{bar}]")
    lines.append("")

    # Rolling 7d
    if roll:
        lines.append(f"<b>ROLLING 7-DAY</b>")
        lines.append(f"WR: {roll['wr']:.1f}% | P&L: ${roll['total_pnl']:+.0f} | PF: {roll['profit_factor']:.2f}")
        if roll['best_symbol']:
            bs = roll['best_symbol']
            lines.append(f"Best: {bs['name']} ${bs['pnl']:+.0f} ({bs['wr']:.0f}% WR)")
        if roll['worst_symbol']:
            ws = roll['worst_symbol']
            lines.append(f"Worst: {ws['name']} ${ws['pnl']:+.0f} ({ws['wr']:.0f}% WR)")
        lines.append("")

    # Suspended
    if report['suspended_symbols']:
        lines.append(f"<b>⏸️ SUSPENDED SYMBOLS</b>")
        for s in report['suspended_symbols']:
            lines.append(f"   • {s['symbol']}: {s['reason']}")
        lines.append("")

    # Suggestions
    if report['suggestions']:
        lines.append(f"<b>💡 SUGGESTIONS</b>")
        for s in report['suggestions']:
            icon = "🔴" if s['severity'] == 'high' else "🟡" if s['severity'] == 'medium' else "🟢"
            lines.append(f"{icon} {s['message']}")
        lines.append("")

    # Pass alert
    if report['pass_alert']:
        pa = report['pass_alert']
        lines.append(f"🎉 <b>PASS NOTIFICATION!</b>")
        lines.append(f"   Qualified days: {pa['qualified_days']}")
        lines.append(f"   Total profit: ${pa['total_profit']:+.0f}")
        lines.append(f"   Profit target: ${PROFIT_TARGET} ACHIEVED!")

    return "\n".join(lines)


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'

    if cmd == 'metrics':
        m = compute_rolling_metrics()
        print(json.dumps(m, indent=2))
    elif cmd == 'suspend':
        s = check_symbol_filtering()
        print(json.dumps(s, indent=2))
    elif cmd == 'suggestions':
        rolling = compute_rolling_metrics()
        s = generate_suggestions(rolling)
        print(json.dumps(s, indent=2))
    elif cmd == 'report':
        r = generate_full_daily_report()
        print(format_telegram_report(r))
    elif cmd == 'json':
        r = generate_full_daily_report()
        print(json.dumps(r, indent=2))
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: ict_auto_iteration.py [metrics|suspend|suggestions|report|json]")
