#!/usr/bin/env python3
"""
crons/btc_5m_momentum_confirmation.py
Near-expiry momentum confirmation strategy:
- Only check in last 30s before expiry
- Binance real-time price delta (5m window)
- Polymarket odds skew confirmation
- Both must agree → high-confidence signal

Integrates with main btc_5m_bot.py via shared state file.
"""
import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

# Add workspace root to path so we can import skills
sys.path.insert(0, '/home/node/.openclaw/workspace')

from skills.token_tracker import TokenTracker

tracker = TokenTracker('btc_5m_momentum')

# ==================== Tunable parameters ====================
SECONDS_BEFORE_EXPIRY = 30          # only check in last 30s
BINANCE_DELTA_THRESHOLD = 0.05      # 0.05% move in 5m window
POLYMARKET_SKEW_THRESHOLD = 0.60    # YES or NO >= 0.60
LLM_CONFIRM = False                 # optional LLM final confirm
TELEGRAM_TOKEN = "8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY"
TELEGRAM_CHAT_ID = "8475453959"

# Shared state
TRADES_LOG = "/tmp/btc_5m_trades.jsonl"
RELAX_FILE = "/tmp/btc_5m_relax.json"

# Last confirmed signal (avoid double-alert per cycle)
LAST_ALERT_FILE = "/tmp/btc_5m_momentum_last_alert.json"


def get_seconds_until_next_5m_expiry() -> int:
    """Polymarket 5m markets align to xx:00, xx:05, xx:10 ..."""
    now = datetime.now(timezone.utc)
    seconds_in_cycle = (now.minute % 5) * 60 + now.second
    return 300 - seconds_in_cycle


def fetch_binance_btc_5m_change() -> tuple:
    """
    Return (delta_pct, current_price) for BTC over the last 5m window.
    Tries Binance first, falls back to OKX (Binance is geo-blocked in US/CA).
    """
    # Try OKX first (works in California)
    try:
        url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=2"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get('data') and len(data['data']) >= 2:
            # OKX: [ts, open, high, low, close, volume, ...]
            cur = float(data['data'][0][4])   # most recent (in-progress) candle
            prev = float(data['data'][1][4])  # previous closed candle
            delta_pct = ((cur - prev) / prev) * 100.0
            return delta_pct, cur
    except Exception as e:
        print(f"[OKX_ERR] {e}")
    # Fallback: Binance (blocked in some regions)
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=2"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data or len(data) < 2:
            return 0.0, 0.0
        cur = float(data[-1][4])
        prev = float(data[-2][4])
        delta_pct = ((cur - prev) / prev) * 100.0
        return delta_pct, cur
    except Exception as e:
        print(f"[BINANCE_ERR] {e}")
        return 0.0, 0.0


def fetch_polymarket_current_odds() -> dict:
    """
    Get YES/NO prices for the current/next 5m market.
    Uses the same logic as main bot - look up market by slug.
    """
    try:
        # Next window
        next_window = (int(time.time()) // 300) * 300 + 300
        slug = f"btc-updown-5m-{next_window}"
        url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data:
            return {"yes": 0.5, "no": 0.5, "slug": slug}
        m = data[0]
        prices_str = m.get('outcomePrices', '[]')
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            yes = float(prices[0]) if len(prices) > 0 else 0.5
            no = float(prices[1]) if len(prices) > 1 else 0.5
        except Exception:
            yes, no = 0.5, 0.5
        return {"yes": yes, "no": no, "slug": slug, "question": m.get('question', '')}
    except Exception as e:
        print(f"[POLY_ERR] {e}")
        return {"yes": 0.5, "no": 0.5, "slug": "?"}


def should_bet(seconds_left: int, binance_delta: float, poly_odds: dict) -> bool:
    """Core filter: time window + Binance momentum + Poly skew"""
    if seconds_left > SECONDS_BEFORE_EXPIRY:
        return False
    strong_momentum = abs(binance_delta) >= BINANCE_DELTA_THRESHOLD
    skewed = (
        poly_odds["yes"] >= POLYMARKET_SKEW_THRESHOLD
        or poly_odds["no"] >= POLYMARKET_SKEW_THRESHOLD
    )
    return strong_momentum and skewed


def generate_signal(binance_delta: float, poly_odds: dict):
    """Build the final signal object"""
    direction = "UP" if binance_delta > 0 else "DOWN"
    confidence = min(0.55 + abs(binance_delta) * 2, 0.85)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "confidence": round(confidence, 3),
        "binance_delta": round(binance_delta, 4),
        "polymarket_yes": round(poly_odds["yes"], 3),
        "polymarket_no": round(poly_odds["no"], 3),
        "action": "BET" if confidence > 0.65 else "SKIP"
    }


def send_telegram(msg: str):
    """Send Telegram message via direct API"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        })
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[TG_ERR] {e}")


def load_last_alert():
    try:
        if os.path.exists(LAST_ALERT_FILE):
            with open(LAST_ALERT_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"window": 0}


def save_last_alert(window: int):
    try:
        with open(LAST_ALERT_FILE, 'w') as f:
            json.dump({"window": window, "ts": datetime.now(timezone.utc).isoformat()}, f)
    except Exception:
        pass


def main():
    now = datetime.now(timezone.utc)
    next_window = (int(time.time()) // 300) * 300 + 300
    seconds_left = get_seconds_until_next_5m_expiry()

    print(f"\n[{now.strftime('%H:%M:%S')}] Window: {next_window} | "
          f"Seconds left: {seconds_left}")

    # Skip if too early
    if seconds_left > SECONDS_BEFORE_EXPIRY + 5:
        # Allow a small grace window in case we're checking slightly late
        if seconds_left < 300 - 5:  # not at the very start of a new window
            print("Not in confirmation window")
            return
        # Edge case: at top of new 5m, just switched. Wait.
        if seconds_left > 290:
            print("Top of new window, waiting...")
            return

    # Avoid duplicate alerts for the same 5m window
    last_alert = load_last_alert()
    if last_alert.get("window") == next_window:
        print(f"Already alerted for window {next_window}")
        return

    # Fetch real-time Binance momentum
    binance_delta, btc_price = fetch_binance_btc_5m_change()
    print(f"[BINANCE] BTC=${btc_price:.2f} | Δ (5m)={binance_delta:+.4f}%")

    # Fetch current Polymarket odds
    poly_odds = fetch_polymarket_current_odds()
    print(f"[POLY] {poly_odds['slug']} | YES={poly_odds['yes']:.3f} / "
          f"NO={poly_odds['no']:.3f}")

    # Check conditions
    if should_bet(seconds_left, binance_delta, poly_odds):
        signal = generate_signal(binance_delta, poly_odds)

        # === Optional LLM confirmation ===
        if LLM_CONFIRM:
            # Placeholder for LLM call
            # tracker.log(model="minimax/M2.7", input_tokens=xxx, output_tokens=xxx, task="5m_momentum_confirm")
            pass

        # Log trade
        try:
            with open(TRADES_LOG, 'a') as f:
                f.write(json.dumps({
                    "ts": signal["timestamp"],
                    "type": "momentum_confirm",
                    "slug": poly_odds.get("slug"),
                    "window": next_window,
                    "direction": signal["direction"],
                    "confidence": signal["confidence"],
                    "binance_delta": signal["binance_delta"],
                    "polymarket_yes": signal["polymarket_yes"],
                    "polymarket_no": signal["polymarket_no"],
                    "btc_price": btc_price,
                    "status": "pending",
                    "result": None
                }) + "\n")
        except Exception as e:
            print(f"[LOG_ERR] {e}")

        # Telegram alert
        msg = (
            f"🚨🚨🚨 <b>MOMENTUM CONFIRM</b> 🚨🚨🚨\n\n"
            f"⏰ <b>Window:</b> <code>{poly_odds.get('slug')}</code>\n"
            f"⏳ <b>Seconds left:</b> {seconds_left}\n\n"
            f"📊 <b>Binance momentum:</b>\n"
            f"  BTC: <code>${btc_price:,.2f}</code>\n"
            f"  Δ (5m): <code>{binance_delta:+.4f}%</code>\n\n"
            f"📈 <b>Polymarket odds:</b>\n"
            f"  YES: <code>{poly_odds['yes']:.3f}</code>\n"
            f"  NO: <code>{poly_odds['no']:.3f}</code>\n\n"
            f"🎯 <b>SIGNAL:</b> <code>{signal['direction']}</code>\n"
            f"  Confidence: <b>{signal['confidence']:.2f}</b>\n"
            f"  Action: <b>{signal['action']}</b>"
        )
        send_telegram(msg)
        save_last_alert(next_window)
        print(f"✅ SIGNAL: {signal['direction']} | conf={signal['confidence']}")
    else:
        strong = abs(binance_delta) >= BINANCE_DELTA_THRESHOLD
        skewed = (
            poly_odds["yes"] >= POLYMARKET_SKEW_THRESHOLD
            or poly_odds["no"] >= POLYMARKET_SKEW_THRESHOLD
        )
        reasons = []
        if not strong:
            reasons.append(f"Δ {binance_delta:+.4f}% < {BINANCE_DELTA_THRESHOLD}%")
        if not skewed:
            reasons.append(f"Poly not skewed (Y={poly_odds['yes']:.2f}, N={poly_odds['no']:.2f})")
        print(f"❌ Skip: {', '.join(reasons)}")

    # Token summary
    summary = tracker.get_summary()
    print(f"Session tokens: in={summary['in']} out={summary['out']} "
          f"calls={summary['calls']}")


if __name__ == "__main__":
    main()
