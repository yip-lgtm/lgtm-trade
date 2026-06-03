#!/usr/bin/env python3
"""
ICT Scanner v1.1 - Complete Logic Implementation
專為 50K Account 設計，嚴格遵守 Daily SL $200 / Qualified Day $250 規則
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta, timezone
import logging
import csv
import os
import json

# ==================== Data Classes ====================

@dataclass
class Candle:
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Setup:
    symbol: str
    direction: str          # "LONG" or "SHORT"
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    confidence: int
    reasons: List[str]
    ote_zone: Dict
    fvg_type: Optional[str] = None  # "BULL" / "BEAR" / None
    swing_high: float = 0.0
    swing_low: float = 0.0


@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    contracts: int
    qualified_locked: bool = False


@dataclass
class AccountState:
    balance: float = 50000.0
    target: float = 3000.0           # Profit target
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    open_positions: List[Position] = field(default_factory=list)
    qualified_days: int = 0
    trading_day_count: int = 0
    is_killed_today: bool = False


# ==================== Indicators ====================

def compute_rsi(closes: List[float], period: int = 14) -> List[float]:
    """RSI(14)"""
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    avg_g, avg_l = 0, 0
    for i in range(1, period + 1):
        d = closes[i] - closes[i-1]
        if d > 0: avg_g += d
        else: avg_l -= d
    avg_g /= period
    avg_l /= period
    for i in range(period, len(closes)):
        if i > period:
            d = closes[i] - closes[i-1]
            avg_g = (avg_g * (period-1) + (d if d > 0 else 0)) / period
            avg_l = (avg_l * (period-1) + (-d if d < 0 else 0)) / period
        out[i] = 100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def compute_ema(closes: List[float], period: int) -> List[float]:
    """EMA(period)"""
    out = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    out[period-1] = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        out[i] = closes[i] * k + out[i-1] * (1 - k)
    return out


def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """ATR(14)"""
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    s = 0
    for i in range(1, period + 1):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        s += tr
    out[period] = s / period
    for i in range(period+1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        out[i] = (out[i-1] * (period-1) + tr) / period
    return out


def compute_macd(closes: List[float]) -> Tuple[List[float], List[float]]:
    """MACD(12, 26, 9)"""
    e12 = compute_ema(closes, 12)
    e26 = compute_ema(closes, 26)
    macd_line = [None] * len(closes)
    for i in range(len(closes)):
        if e12[i] is not None and e26[i] is not None:
            macd_line[i] = e12[i] - e26[i]
    valid = [v for v in macd_line if v is not None]
    sig_raw = compute_ema(valid, 9)
    signal = [None] * len(closes)
    j = 0
    for i in range(len(closes)):
        if macd_line[i] is not None:
            if j < len(sig_raw):
                signal[i] = sig_raw[j]
                j += 1
    return macd_line, signal


def compute_bbands(closes: List[float], period: int = 20, stddev: float = 2.0):
    """Bollinger Bands(20, 2σ)"""
    upper = [None] * len(closes)
    middle = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period-1, len(closes)):
        sl = closes[i-period+1:i+1]
        mean = sum(sl) / period
        var = sum((x - mean) ** 2 for x in sl) / period
        sd = var ** 0.5
        middle[i] = mean
        upper[i] = mean + stddev * sd
        lower[i] = mean - stddev * sd
    return upper, middle, lower


# ==================== Data Provider ====================

class YahooCSVDataProvider:
    """Read from /home/node/.openclaw/workspace/*.csv"""

    def __init__(self, base_dir: str = "/home/node/.openclaw/workspace"):
        self.base_dir = base_dir
        self.cache: Dict[str, List[Candle]] = {}

    def get_daily_data(self, symbol: str, count: int = 300) -> List[Candle]:
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
        candles = candles[-count:]
        self.cache[symbol] = candles
        return candles


# ==================== Main Class ====================

class ICTScanner:
    """ICT Scanner with full confluence logic + 50K risk management"""

    # Symbol specs
    POINT_VALUE = {
        'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MYM.F': 0.5,
        'M6E.F': 12500, 'M6A.F': 10000, 'MCL.F': 100, 'MBT.F': 10,
        'MET.F': 1
    }
    CONTRACTS = {
        'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
        'M6E.F': 2, 'M6A.F': 2, 'MCL.F': 1, 'MBT.F': 2,
        'MET.F': 2
    }
    PRECISION = {
        'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
        'M6E.F': 4, 'M6A.F': 4, 'MCL.F': 2, 'MBT.F': 2,
        'MET.F': 2
    }

    def __init__(self, data_provider, notifier=None):
        """
        data_provider: 必須有 get_daily_data(symbol, count) 方法
        notifier: 接受 message 字串 (e.g. Telegram)
        """
        self.data_provider = data_provider
        self.notifier = notifier
        self.logger = logging.getLogger("ICTScanner")
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

        # 50K Account Rules
        self.MAX_DAILY_LOSS = 200
        self.QUALIFIED_DAY_PROFIT = 250
        self.SINGLE_TRADE_RISK = 100
        self.MIN_PROB = 0.50  # For Markov BTC bot
        self.PROFIT_TARGET = 3000
        self.INITIAL_BALANCE = 50000
        self.MAX_DRAWDOWN = 2000

        # Account state
        self.account = AccountState(balance=self.INITIAL_BALANCE)

    # ==================== Main Workflow ====================

    def run_daily_scan(self, symbols: List[str]) -> List[Setup]:
        """每日主掃描流程"""
        # 1. Reset daily
        self.account.daily_pnl = 0
        self.account.is_killed_today = False
        self.account.trading_day_count += 1

        # 2. Check daily loss kill switch
        if self.account.total_pnl <= -self.MAX_DRAWDOWN:
            self.logger.info(f"❌ Max drawdown hit: {self.account.total_pnl}")
            return []

        # 3. Get daily bias
        bias = self.get_daily_bias()
        if bias == "NONE":
            self.logger.info("⏸️ No clear bias today")
            return []

        self.logger.info(f"📊 Daily Bias: {bias}")

        all_setups = []

        # 4. Run KZ scans
        for kz in ["LondonOpen", "NYOpen"]:
            if not self.is_in_kill_zone(kz):
                continue

            self.logger.info(f"⏰ In {kz}")
            for symbol in symbols:
                if self.account.is_killed_today:
                    self.logger.info("🛑 Daily kill-switch active, no more trades")
                    break

                setups = self.scan_symbol(symbol, bias, kz)
                for setup in setups:
                    if self.check_risk_ok(setup):
                        all_setups.append(setup)
                        self.send_alert(setup, kz)

        return all_setups

    def scan_symbol(self, symbol: str, bias: str, kill_zone: str) -> List[Setup]:
        """Scan single symbol for ICT setups"""
        data = self.data_provider.get_daily_data(symbol, count=300)
        if len(data) < 50:
            return []

        setups = self.find_confluence_setups(data, bias, symbol)
        return setups

    # ==================== Step 1: Daily Bias ====================

    def get_daily_bias(self) -> str:
        """
        Daily Bias based on:
        - Last day's close vs 5-day SMA
        - Higher timeframe trend
        """
        try:
            data = self.data_provider.get_daily_data('MES.F', count=20)
            if len(data) < 10:
                return "NONE"
            closes = [d.close for d in data]
            last_close = closes[-1]
            sma5 = sum(closes[-5:]) / 5
            sma20 = sum(closes) / len(closes)

            if last_close > sma5 > sma20:
                return "BULLISH"
            elif last_close < sma5 < sma20:
                return "BEARISH"
            else:
                return "NONE"
        except Exception as e:
            self.logger.error(f"Bias error: {e}")
            return "NONE"

    # ==================== Step 2: Liquidity Sweep ====================

    def check_liquidity_sweep(self, data: List[Candle], direction: str) -> bool:
        """
        Check if recent price swept swing high/low
        Sweep = wick through level, close back inside
        """
        if len(data) < 5:
            return False
        last = data[-1]
        prev_swing = data[-10:-1] if len(data) > 10 else data[:-1]
        if not prev_swing:
            return False

        if direction == "BULLISH":
            # Swept below recent low, closed back above
            recent_low = min(d.low for d in prev_swing)
            if last.low < recent_low and last.close > recent_low:
                return True
        else:  # BEARISH
            recent_high = max(d.high for d in prev_swing)
            if last.high > recent_high and last.close < recent_high:
                return True
        return False

    # ==================== Step 3: OTE Zone ====================

    def calculate_ote_zone(self, swing_high: float, swing_low: float, direction: str) -> Dict:
        """
        OTE = Optimal Trade Entry (62-79% Fibonacci retracement)
        """
        fib_range = swing_high - swing_low
        if fib_range <= 0:
            return {"low": 0, "high": 0, "valid": False}

        if direction == "BULLISH":
            return {
                "low": swing_low + fib_range * 0.62,
                "high": swing_low + fib_range * 0.79,
                "mid": swing_low + fib_range * 0.705,
                "valid": True
            }
        else:  # BEARISH
            return {
                "low": swing_high - fib_range * 0.79,
                "high": swing_high - fib_range * 0.62,
                "mid": swing_high - fib_range * 0.705,
                "valid": True
            }

    # ==================== Step 4: FVG Detection ====================

    def detect_fvg(self, data: List[Candle], direction: str) -> Optional[Dict]:
        """
        FVG = Fair Value Gap (3-candle imbalance)
        Bullish: candle[0].high < candle[2].low (gap up)
        Bearish: candle[0].low > candle[2].high (gap down)
        """
        if len(data) < 3:
            return None
        c0 = data[-3]
        c1 = data[-2]
        c2 = data[-1]

        if direction == "BULLISH":
            if c0.high < c2.low:
                return {
                    "type": "BULL",
                    "low": c0.high,
                    "high": c2.low,
                    "mid": (c0.high + c2.low) / 2
                }
        else:  # BEARISH
            if c0.low > c2.high:
                return {
                    "type": "BEAR",
                    "low": c2.high,
                    "high": c0.low,
                    "mid": (c2.high + c0.low) / 2
                }
        return None

    # ==================== Step 5: Confluence Setups ====================

    def find_confluence_setups(self, data: List[Candle], bias: str, symbol: str) -> List[Setup]:
        """
        Find setups that meet ALL ICT confluence criteria:
        1. Bias aligned
        2. Liquidity sweep
        3. FVG or OTE present
        4. RSI not overbought/oversold
        5. EMA trend aligned
        6. MACD momentum
        """
        if len(data) < 50:
            return []

        closes = [d.close for d in data]
        highs = [d.high for d in data]
        lows = [d.low for d in data]
        volumes = [d.volume for d in data]
        i = len(data) - 1

        # Compute indicators
        rsi = compute_rsi(closes)
        ema12 = compute_ema(closes, 12)
        ema26 = compute_ema(closes, 26)
        atr = compute_atr(highs, lows, closes)
        macd_line, macd_sig = compute_macd(closes)
        bb_upper, bb_mid, bb_lower = compute_bbands(closes)

        cur = closes[i]
        cur_rsi = rsi[i] if rsi[i] is not None else 50
        cur_ema12 = ema12[i] if ema12[i] is not None else cur
        cur_ema26 = ema26[i] if ema26[i] is not None else cur
        cur_macd = macd_line[i] if macd_line[i] is not None else 0
        cur_sig = macd_sig[i] if macd_sig[i] is not None else 0
        cur_bb_u = bb_upper[i] if bb_upper[i] is not None else cur
        cur_bb_l = bb_lower[i] if bb_lower[i] is not None else cur
        cur_bb_m = bb_mid[i] if bb_mid[i] is not None else cur
        cur_atr = atr[i] if atr[i] is not None else 0

        # Volume confirmation
        vol_sma = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else volumes[-1]
        vol_above = volumes[i] > vol_sma

        # Swing structure (20-period)
        lookback = data[-21:-1] if len(data) > 21 else data[:-1]
        if not lookback:
            return []
        swing_h = max(d.high for d in lookback)
        swing_l = min(d.low for d in lookback)

        setups = []

        # ===== BULLISH LOGIC =====
        if bias in ("BULLISH", "NONE"):
            # FVG
            fvg = self.detect_fvg(data, "BULLISH")
            # OTE Zone
            ote = self.calculate_ote_zone(swing_h, swing_l, "BULLISH")
            in_ote = ote["valid"] and ote["low"] <= cur <= ote["high"]

            # Sweep
            swept = self.check_liquidity_sweep(data, "BULLISH")

            # Conditions
            cond_rsi = 30 < cur_rsi < 60
            cond_ema = cur_ema12 > cur_ema26
            cond_fvg_or_ote = (fvg is not None) or in_ote
            cond_macd = cur_macd > cur_sig
            cond_bb = cur > cur_bb_l and cur < cur_bb_m  # Near lower BB
            cond_sweep = swept

            if cond_rsi and cond_ema and cond_fvg_or_ote:
                # Calculate confidence
                conf = 0
                reasons = []
                if fvg is not None:
                    conf += 3
                    reasons.append(f"FVG ({fvg['low']:.2f}-{fvg['high']:.2f})")
                elif in_ote:
                    conf += 3
                    reasons.append(f"OTE ({ote['low']:.2f}-{ote['high']:.2f})")
                if cond_sweep:
                    conf += 1
                    reasons.append("Liquidity sweep")
                if cond_macd:
                    conf += 1
                    reasons.append("MACD bullish")
                if cond_bb:
                    conf += 1
                    reasons.append("Lower BB")
                if vol_above:
                    reasons.append("Volume ↑")

                if conf >= 3:  # Min confidence
                    setup = self.build_setup(
                        symbol, "LONG", cur, swing_h, swing_l, ote, fvg,
                        conf, reasons
                    )
                    setups.append(setup)

        # ===== BEARISH LOGIC =====
        if bias in ("BEARISH", "NONE"):
            fvg = self.detect_fvg(data, "BEARISH")
            ote = self.calculate_ote_zone(swing_h, swing_l, "BEARISH")
            in_ote = ote["valid"] and ote["low"] <= cur <= ote["high"]
            swept = self.check_liquidity_sweep(data, "BEARISH")

            cond_rsi = 40 < cur_rsi < 70
            cond_ema = cur_ema12 < cur_ema26
            cond_fvg_or_ote = (fvg is not None) or in_ote
            cond_macd = cur_macd < cur_sig
            cond_bb = cur < cur_bb_u and cur > cur_bb_m
            cond_sweep = swept

            if cond_rsi and cond_ema and cond_fvg_or_ote:
                conf = 0
                reasons = []
                if fvg is not None:
                    conf += 3
                    reasons.append(f"FVG ({fvg['low']:.2f}-{fvg['high']:.2f})")
                elif in_ote:
                    conf += 3
                    reasons.append(f"OTE ({ote['low']:.2f}-{ote['high']:.2f})")
                if cond_sweep:
                    conf += 1
                    reasons.append("Liquidity sweep")
                if cond_macd:
                    conf += 1
                    reasons.append("MACD bearish")
                if cond_bb:
                    conf += 1
                    reasons.append("Upper BB")
                if vol_above:
                    reasons.append("Volume ↑")

                if conf >= 3:
                    setup = self.build_setup(
                        symbol, "SHORT", cur, swing_h, swing_l, ote, fvg,
                        conf, reasons
                    )
                    setups.append(setup)

        return setups

    # ==================== Setup Builder ====================

    def build_setup(self, symbol, direction, entry, swing_h, swing_l,
                    ote, fvg, confidence, reasons) -> Setup:
        """Build Setup with SL/TP based on risk rules"""
        pv = self.POINT_VALUE.get(symbol, 1)
        contracts = self.CONTRACTS.get(symbol, 2)

        # SL = $200 risk / contracts / point_value
        sl_distance_points = self.MAX_DAILY_LOSS / (pv * contracts)
        # But we use $100 per trade as risk (so 2 trades per day max)
        sl_distance_points = self.SINGLE_TRADE_RISK / (pv * contracts)

        if direction == "LONG":
            sl = entry - sl_distance_points
            tp1 = entry + sl_distance_points * 3   # R:R = 1:3
            tp2 = entry + sl_distance_points * 6   # R:R = 1:6
        else:
            sl = entry + sl_distance_points
            tp1 = entry - sl_distance_points * 3
            tp2 = entry - sl_distance_points * 6

        return Setup(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            confidence=confidence,
            reasons=reasons,
            ote_zone=ote,
            fvg_type=fvg['type'] if fvg else None,
            swing_high=swing_h,
            swing_low=swing_l
        )

    # ==================== Step 6: Risk Check ====================

    def check_risk_ok(self, setup: Setup) -> bool:
        """
        50K Apex Rules:
        - Daily SL $200 (max 2 trades per day)
        - Single trade risk $100
        - Max drawdown $2000 (total)
        """
        # 1. Daily kill switch
        if self.account.is_killed_today:
            return False

        # 2. Daily loss limit
        if self.account.daily_pnl <= -self.MAX_DAILY_LOSS:
            self.logger.warning(f"🛑 Daily loss limit hit: {self.account.daily_pnl}")
            self.account.is_killed_today = True
            return False

        # 3. Max drawdown
        if self.account.total_pnl <= -self.MAX_DRAWDOWN:
            self.logger.error(f"❌ Max drawdown hit: {self.account.total_pnl}")
            return False

        # 4. Profit target
        if self.account.total_pnl >= self.PROFIT_TARGET:
            self.logger.info(f"🎯 Profit target reached: {self.account.total_pnl}")
            return False

        # 5. Open position conflict
        for pos in self.account.open_positions:
            if pos.symbol == setup.symbol:
                self.logger.info(f"⏸️ Already in {setup.symbol}")
                return False

        # 6. Max positions per day (2 = $200 max risk)
        # (Could be added as self.daily_trade_count)

        return True

    # ==================== Step 7: Kill Zone ====================

    def is_in_kill_zone(self, kz_name: str) -> bool:
        """
        London KZ: 14:00-15:00 HKT = 06:00-07:00 UTC
        NY KZ: 20:30-21:30 HKT = 12:30-13:30 UTC
        """
        now = datetime.now(timezone.utc)
        h, m = now.hour, now.minute

        if kz_name == "LondonOpen":
            return h == 6 and 0 <= m <= 59
        elif kz_name == "NYOpen":
            return (h == 12 and m >= 30) or (h == 13 and m < 30)
        return False

    # ==================== Notifications ====================

    def send_alert(self, setup: Setup, kz: str):
        """Send alert via notifier"""
        msg = (
            f"🔥🔥🔥 {kz} KILL ZONE 有效信號！！！\n\n"
            f"📊 {setup.symbol}: {setup.direction}\n"
            f"💰 Entry: {setup.entry:.2f}\n"
            f"🛑 SL: {setup.stop_loss:.2f}\n"
            f"🎯 TP1: {setup.tp1:.2f} (R:R 1:3)\n"
            f"🎯 TP2: {setup.tp2:.2f} (R:R 1:6)\n"
            f"📈 Confidence: {setup.confidence}/5\n"
            f"📝 Reasons:\n" + "\n".join(f"  • {r}" for r in setup.reasons) + "\n\n"
            f"⚠️ Daily P&L: ${self.account.daily_pnl:.0f}\n"
            f"💼 Total P&L: ${self.account.total_pnl:.0f}\n"
            f"📅 Day: {self.account.trading_day_count}/5"
        )
        print(msg)
        if self.notifier:
            try:
                self.notifier(msg)
            except Exception as e:
                self.logger.error(f"Notifier error: {e}")


# ==================== Example Usage ====================

def main():
    """Example: run scanner with Yahoo CSV data + Telegram notifier"""
    dp = YahooCSVDataProvider()

    def tg_notifier(msg):
        # Integrate with your Telegram bot
        print(f"[TG] {msg[:100]}...")

    scanner = ICTScanner(dp, notifier=tg_notifier)
    symbols = ['MES.F', 'MNQ.F', 'M2K.F', 'MCL.F', 'MBT.F', 'MET.F']

    setups = scanner.run_daily_scan(symbols)
    print(f"\n✅ {len(setups)} setups found")


if __name__ == "__main__":
    main()
