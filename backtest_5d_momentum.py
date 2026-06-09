#!/usr/bin/env python3
"""
backtest_5d_momentum.py
Near-expiry momentum confirmation - 5d backtest
Uses OKX (Binance geo-blocked in California)

Strategy:
- At 30s before each 5m window expires, check the in-progress candle's delta
- If |delta| >= 0.05% → strong momentum → predict same direction for NEXT 5m
- Polymarket skew was used in cron script; here we just check momentum edge
"""
import json
import urllib.request
import pandas as pd
from datetime import datetime, timezone, timedelta

# =============== Params (match cron) ===============
SECONDS_BEFORE_EXPIRY = 30
BINANCE_DELTA_THRESHOLD = 0.05  # 0.05%
LOOKBACK_DAYS = 5
INST_ID = "BTC-USDT"
# ==================================================

def fetch_okx_5m(days=5):
    """Fetch OKX 5m klines, paginated. Returns DataFrame with OHLCV."""
    # OKX returns up to 300 candles per request; paginate with 'after' param
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_candles = []
    after = end_ts
    while True:
        url = f"https://www.okx.com/api/v5/market/candles?instId={INST_ID}&bar=5m&limit=300&after={after}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        candles = data.get('data', [])
        if not candles:
            break
        all_candles.extend(candles)
        # OKX returns DESC order; oldest at end
        oldest_ts = int(candles[-1][0])
        if oldest_ts <= start_ts:
            break
        # next page: 'after' = oldest_ts - 1
        after = oldest_ts - 1
    if not all_candles:
        return pd.DataFrame()
    # Convert: [ts, open, high, low, close, volume, ...]
    df = pd.DataFrame(all_candles)
    # OKX returns 9 columns: [ts, open, high, low, close, volume, volCcy, volCcyQuote, confirm]
    df.columns = ['ts', 'open', 'high', 'low', 'close', 'vol', 'volCcy', 'volCcyQuote', 'confirm']
    df = df[['ts', 'open', 'high', 'low', 'close', 'vol']].copy()
    df['ts'] = pd.to_datetime(df['ts'].astype(int), unit='ms', utc=True)
    df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
    # Sort ascending and dedup
    df = df.sort_values('ts').drop_duplicates('ts').reset_index(drop=True)
    return df


def simulate_strategy(df: pd.DataFrame, mode='next'):
    """
    mode='next': predict NEXT 5m candle direction based on current momentum
    mode='cont': predict current in-progress candle closes in same direction as delta
    """
    results = []
    for i in range(len(df) - 1):
        cur = df.iloc[i]
        delta_pct = (cur['close'] - cur['open']) / cur['open'] * 100.0
        if abs(delta_pct) < BINANCE_DELTA_THRESHOLD:
            continue
        predicted = "UP" if delta_pct > 0 else "DOWN"
        if mode == 'next':
            nxt = df.iloc[i + 1]
            actual = "UP" if nxt['close'] > nxt['open'] else "DOWN"
            check_field = 'next candle'
        else:  # 'cont' - continuation within same candle
            actual = "UP" if cur['close'] > cur['open'] else "DOWN"
            check_field = 'same candle'
        win = predicted == actual
        results.append({
            "time": cur['ts'],
            "delta_pct": round(delta_pct, 4),
            "predicted": predicted,
            "actual": actual,
            "win": win
        })
    return pd.DataFrame(results)


def main():
    print(f"=== Backtest: {LOOKBACK_DAYS} days momentum confirmation ===")
    print(f"Instrument: {INST_ID}")
    print(f"Threshold: |delta| >= {BINANCE_DELTA_THRESHOLD}%")
    print(f"Loading data from OKX...")
    df = fetch_okx_5m(LOOKBACK_DAYS)
    if df.empty:
        print("❌ No data from OKX")
        return
    print(f"Got {len(df)} candles from {df['ts'].iloc[0]} to {df['ts'].iloc[-1]}\n")

    res = simulate_strategy(df, mode='next')
    if res.empty:
        print("❌ No signals triggered (market too flat)")
        return

    total = len(res)
    wins = res['win'].sum()
    losses = total - wins
    wr = wins / total * 100.0

    print(f"Mode: PREDICT NEXT 5m CANDLE based on current momentum")
    print(f"=== Overall ===")
    print(f"Total signals:    {total}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print(f"Win rate:         {wr:.2f}%")
    print(f"Avg |delta|:      {res['delta_pct'].abs().mean():.4f}%")
    print(f"Max |delta|:      {res['delta_pct'].abs().max():.4f}%")
    print()

    # By direction
    print("=== By direction ===")
    by_dir = res.groupby('predicted').agg(
        trades=('win', 'count'),
        wins=('win', 'sum'),
        wr_pct=('win', lambda x: round(x.sum() / len(x) * 100, 2))
    )
    print(by_dir)
    print()

    # By delta magnitude
    print("=== By delta magnitude ===")
    res['abs_delta'] = res['delta_pct'].abs()
    bins = [0.05, 0.08, 0.12, 0.20, 0.50, 999.0]
    labels = ['0.05-0.08%', '0.08-0.12%', '0.12-0.20%', '0.20-0.50%', '>0.50%']
    res['delta_group'] = pd.cut(res['abs_delta'], bins=bins, labels=labels)
    by_mag = res.groupby('delta_group', observed=True).agg(
        trades=('win', 'count'),
        wins=('win', 'sum'),
        wr_pct=('win', lambda x: round(x.sum() / len(x) * 100, 2))
    )
    print(by_mag)
    print()

    # Profit calculation (Polymarket binary: $1 to win, $0 to lose; win pays $1)
    print("=== R:R 1:1 (Polymarket) ===")
    pos = 1.0
    pnl_total = wins * pos - losses * pos
    print(f"P&L: ${pnl_total:+.2f} (from {total} trades @ ${pos:.0f}/trade)")
    print(f"EV/trade: ${pnl_total/total:+.3f}")
    print(f"Daily EV (×288 trades/day max): ${pnl_total/total*288:+.2f}")
    print()

    # Compare thresholds
    print("=== Threshold sensitivity ===")
    for t in [0.03, 0.04, 0.05, 0.07, 0.10, 0.15, 0.20]:
        sub = res[res['abs_delta'] >= t]
        if len(sub) == 0:
            print(f"  >= {t:.2f}%: 0 trades")
            continue
        wr_t = sub['win'].sum() / len(sub) * 100.0
        pnl_t = (sub['win'].sum() - (len(sub) - sub['win'].sum())) * pos
        print(f"  >= {t:.2f}%: {len(sub):3d} trades, WR={wr_t:.1f}%, P&L=${pnl_t:+.2f}")

    # Also test continuation mode
    print("\n\n=== ALT MODE: Predict current candle direction (continuation) ===")
    res2 = simulate_strategy(df, mode='cont')
    if not res2.empty:
        total2 = len(res2)
        wins2 = res2['win'].sum()
        wr2 = wins2 / total2 * 100.0
        print(f"Total: {total2}, Wins: {wins2}, WR: {wr2:.2f}%")
        pnl2 = (wins2 - (total2 - wins2)) * 1.0
        print(f"P&L: ${pnl2:+.2f}")


if __name__ == "__main__":
    main()
