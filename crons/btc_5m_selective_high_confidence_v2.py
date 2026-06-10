#!/usr/bin/env python3
"""
crons/btc_5m_selective_high_confidence_v2.py

Selective High-Confidence Momentum 策略 v2
- Layer 1: OKX 5m momentum + Polymarket skew filter (FREE, no LLM cost)
- Layer 2: MiniMax LLM confirms direction + confidence (only if Layer 1 passes)
- Layer 3: Confidence-gated bet sizing + Telegram alert

Differences vs btc_5m_momentum_confirmation.py:
- Optional LLM confirm (LLM_CONFIRM env var) with structured JSON output
- Bet sizing by confidence (Kelly-lite)
- All 3 options: B (bet size) + C (Telegram) + D (real LLM call)
"""
import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone

# Add workspace root to path so we can import skills
sys.path.insert(0, '/home/node/.openclaw/workspace')

from skills.token_tracker import TokenTracker

tracker = TokenTracker('btc_5m_selective_v2')

# ==================== Tunable parameters ====================
SECONDS_BEFORE_EXPIRY = 30          # only check in last 30s
MOMENTUM_THRESHOLD = 0.05           # OKX 5m |delta| trigger (0.05%)
SKEW_THRESHOLD = 0.55               # Poly YES/NO >= this to count as skewed
LLM_CONFIDENCE_THRESHOLD = 0.68     # min LLM confidence to bet
LLM_CONFIRM = os.environ.get('LLM_CONFIRM', 'false').lower() == 'true'
LLM_MODEL = os.environ.get('LLM_MODEL', 'minimax/MiniMax-M3')  # M3 default
LLM_BASE_URL = 'https://api.minimax.io/anthropic'

# Bet sizing (Option B): Kelly-lite, capped
MIN_BET_USD = 0.50
MAX_BET_USD = 5.00
BANKROLL = 30.0  # $30 daily budget (matches aggressive v2)

# Telegram (Option C)
TELEGRAM_TOKEN = "8606567428:AAFvcsiNf00mAIES6-CTIwKeQTKaos0trNY"
TELEGRAM_CHAT_ID = "8475453959"

LAST_ALERT_FILE = "/tmp/btc_5m_selective_v2_last_alert.json"
TRADES_LOG = "/tmp/btc_5m_trades.jsonl"


# ==================== Data layer ====================
def fetch_okx_btc_5m_change() -> tuple:
    """
    Return (delta_pct, current_price) for BTC over the last 5m window.
    OKX primary (works in California), Binance fallback.
    """
    # OKX first
    try:
        url = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m&limit=2"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get('data') and len(data['data']) >= 2:
            cur = float(data['data'][0][4])
            prev = float(data['data'][1][4])
            delta_pct = ((cur - prev) / prev) * 100.0
            return delta_pct, cur, 'okx'
    except Exception as e:
        print(f"[OKX_ERR] {e}")
    # Binance fallback
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=2"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data and len(data) >= 2:
            cur = float(data[-1][4])
            prev = float(data[-2][4])
            delta_pct = ((cur - prev) / prev) * 100.0
            return delta_pct, cur, 'binance'
    except Exception as e:
        print(f"[BIN_ERR] {e}")
    return 0.0, 0.0, 'error'


def fetch_polymarket_odds() -> dict:
    """Polymarket 5m BTC up/down odds for next window"""
    try:
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


# ==================== LLM layer (Option D) ====================
def call_minimax(prompt: str) -> tuple:
    """
    Call MiniMax via OpenClaw's `infer model run` subprocess.
    Uses OpenClaw's own auth (no API key needed in env).
    Returns (content_str, input_tokens, output_tokens).
    Returns (None, 0, 0) on failure.
    """
    import subprocess
    try:
        result = subprocess.run(
            ['openclaw', 'infer', 'model', 'run',
             '--prompt', prompt,
             '--model', LLM_MODEL,
             '--json'],
            capture_output=True, text=True, timeout=45
        )
        if result.returncode != 0:
            print(f"[LLM_ERR] exit={result.returncode} stderr={result.stderr[:200]}")
            return None, 0, 0
        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except Exception:
            # Sometimes output isn't JSON, treat stdout as text
            return result.stdout.strip() or None, 0, 0
        # Extract content and usage
        # Format varies: might be {"content": "...", "usage": {"input_tokens": N, ...}}
        # or {"output": "...", "input_tokens": N, "output_tokens": N}
        content = (
            data.get('content')
            or data.get('output')
            or data.get('text')
            or data.get('message', {}).get('content', '')
        )
        # Usage may be nested
        usage = data.get('usage', {})
        in_tok = (
            usage.get('input_tokens')
            or data.get('input_tokens', 0)
        )
        out_tok = (
            usage.get('output_tokens')
            or data.get('output_tokens', 0)
        )
        return str(content).strip(), int(in_tok), int(out_tok)
    except subprocess.TimeoutExpired:
        print(f"[LLM_ERR] timeout after 45s")
        return None, 0, 0
    except Exception as e:
        print(f"[LLM_ERR] {e}")
        return None, 0, 0


def llm_should_bet(binance_delta: float, poly_odds: dict) -> tuple:
    """
    Layer 2: ask LLM for confirmation.
    Returns (direction, confidence, reason, in_tok, out_tok).
    Returns (None, 0, '', 0, 0) on failure.
    """
    prompt = f"""Polymarket BTC 5m Up/Down market analysis:

- OKX/Binance 5m price change: {binance_delta:+.3f}%
- Polymarket YES: {poly_odds['yes']:.2f}
- Polymarket NO:  {poly_odds['no']:.2f}
- Slug: {poly_odds.get('slug', '?')}

Decide: bet UP or DOWN, with confidence 0.00-1.00.
Return only JSON: {{"direction":"UP|DOWN","confidence":0.00,"reason":"<20char reason>"}}"""
    content, in_tok, out_tok = call_minimax(prompt)
    if not content:
        return None, 0, '', in_tok, out_tok
    # Strip markdown fences if present
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].split('```')[0].strip()
    try:
        j = json.loads(content)
        return (
            j.get('direction', '').upper(),
            float(j.get('confidence', 0)),
            str(j.get('reason', '')),
            in_tok,
            out_tok,
        )
    except Exception as e:
        print(f"[LLM_PARSE_ERR] {e} | content={content[:200]}")
        return None, 0, '', in_tok, out_tok


# ==================== Bet sizing (Option B) ====================
def calc_bet_size(confidence: float) -> float:
    """
    Kelly-lite sizing:
    - binary R:R 1:1, so Kelly = 2*conf - 1
    - Half-Kelly to be conservative
    - Capped at MAX_BET_USD
    """
    if confidence <= 0.5:
        return 0.0
    kelly = max(0.0, (2 * confidence - 1))
    half_kelly = kelly / 2.0
    bet = half_kelly * BANKROLL
    bet = max(MIN_BET_USD, min(MAX_BET_USD, bet))
    return round(bet, 2)


# ==================== Telegram (Option C) ====================
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0',
        })
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[TG_ERR] {e}")


# ==================== Alert dedup ====================
def load_last_alert():
    try:
        if os.path.exists(LAST_ALERT_FILE):
            with open(LAST_ALERT_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"window": 0}


def save_last_alert(window: int, signal: dict):
    try:
        with open(LAST_ALERT_FILE, 'w') as f:
            json.dump({"window": window, "ts": datetime.now(timezone.utc).isoformat(),
                       "signal": signal}, f)
    except Exception:
        pass


def log_trade(signal: dict):
    try:
        with open(TRADES_LOG, 'a') as f:
            f.write(json.dumps(signal) + '\n')
    except Exception:
        pass


# ==================== Main ====================
def main():
    now = datetime.now(timezone.utc)
    next_window = (int(time.time()) // 300) * 300 + 300
    seconds_left = next_window - int(time.time())

    # Time window check
    if seconds_left > SECONDS_BEFORE_EXPIRY:
        return  # too early, silent

    # Dedup: skip if already alerted this window
    last = load_last_alert()
    if last.get('window') == next_window:
        return

    print(f"\n[{now.isoformat()}] Selective v2 check (window={next_window}, t-{seconds_left}s)")

    # Layer 1: free filter
    delta, price, src = fetch_okx_btc_5m_change()
    poly = fetch_polymarket_odds()
    has_momentum = abs(delta) >= MOMENTUM_THRESHOLD
    is_skewed = max(poly['yes'], poly['no']) >= SKEW_THRESHOLD
    print(f"  {src} Δ: {delta:+.3f}% | Poly Y={poly['yes']:.2f} N={poly['no']:.2f} | momentum={has_momentum} skewed={is_skewed}")

    if not (has_momentum and is_skewed):
        print(f"  ❌ Layer 1 fail → HOLD")
        return

    # Layer 2: LLM confirm (optional)
    direction = "UP" if delta > 0 else "DOWN"
    confidence = 0.70
    reason = "Layer1+alignment"
    in_tok = out_tok = 0

    if LLM_CONFIRM:
        llm_dir, llm_conf, llm_reason, in_tok, out_tok = llm_should_bet(delta, poly)
        if in_tok or out_tok:
            tracker.log(LLM_MODEL, in_tok, out_tok, task='selective_v2')
        if not llm_dir:
            print(f"  ❌ LLM failed → HOLD")
            return
        if llm_dir != direction:
            print(f"  ⚠️ LLM disagrees ({llm_dir} vs momentum {direction}) → HOLD")
            return
        direction = llm_dir
        confidence = llm_conf
        reason = llm_reason
        print(f"  ✅ LLM: {direction} @ {confidence:.2f} | {reason}")

    # Layer 3: confidence gate
    if confidence < LLM_CONFIDENCE_THRESHOLD:
        print(f"  ⚠️ Confidence {confidence:.2f} < {LLM_CONFIDENCE_THRESHOLD} → HOLD")
        return

    bet_size = calc_bet_size(confidence)
    if bet_size <= 0:
        print(f"  ⚠️ Bet size 0 → HOLD")
        return

    # Build signal
    signal = {
        "timestamp": now.isoformat(),
        "window": next_window,
        "direction": direction,
        "confidence": round(confidence, 3),
        "delta_pct": round(delta, 4),
        "btc_price": price,
        "poly_yes": round(poly['yes'], 3),
        "poly_no": round(poly['no'], 3),
        "poly_slug": poly.get('slug', ''),
        "bet_size_usd": bet_size,
        "reason": reason,
        "llm_used": LLM_CONFIRM,
        "data_source": src,
    }
    log_trade(signal)
    save_last_alert(next_window, signal)

    # Loud alert 🚨🚨🚨
    msg = (
        f"🚨🚨🚨 <b>BTC 5m SELECTIVE v2 SIGNAL</b> 🚨🚨🚨\n\n"
        f"<b>Direction:</b> {direction}\n"
        f"<b>Confidence:</b> {confidence*100:.1f}%\n"
        f"<b>Bet size:</b> ${bet_size:.2f}\n"
        f"<b>Reason:</b> {reason}\n\n"
        f"<b>Data:</b>\n"
        f"  • OKX Δ: {delta:+.3f}%\n"
        f"  • BTC: ${price:,.2f}\n"
        f"  • Poly YES: {poly['yes']:.2f} | NO: {poly['no']:.2f}\n"
        f"  • Slug: {poly.get('slug', '?')}\n"
        f"  • Window: {next_window} (t-{seconds_left}s)\n\n"
        f"<b>Action:</b> Bet {direction} on Polymarket"
    )
    send_telegram(msg)
    print(f"  🚨 SIGNAL: {direction} @ {confidence:.2f} | ${bet_size}")

    summary = tracker.get_summary()
    print(f"  Session tokens: {summary['total']} | Calls: {summary['calls']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FATAL] {e}")
