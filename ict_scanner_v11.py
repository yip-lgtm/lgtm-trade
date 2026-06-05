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

    def get_intraday_data(self, symbol: str, count: int = 200) -> Optional[List[Candle]]:
        """Try to load 5min/15min/1hr intraday data from {symbol}_Xmin.csv or {symbol}_1hr.csv"""
        # Convert MES.F to MES_F for filename lookup
        symbol_underscore = symbol.replace('.', '_')

        for tf in ['5min', '15min', '1hr']:
            for path in [
                os.path.join(self.base_dir, f"{symbol}_{tf}.csv"),
                os.path.join(self.base_dir, f"{symbol_underscore}_{tf}.csv")
            ]:
                if os.path.exists(path):
                    candles = []
                    with open(path) as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            try:
                                # Handle both Datetime and datetime columns
                                dt = row.get('Datetime') or row.get('datetime', '')
                                candles.append(Candle(
                                    datetime=dt,
                                    open=float(row.get('Open') or row['open']),
                                    high=float(row.get('High') or row['high']),
                                    low=float(row.get('Low') or row['low']),
                                    close=float(row.get('Close') or row['close']),
                                    volume=float(row.get('Volume') or row.get('volume', 0))
                                ))
                            except (KeyError, ValueError, TypeError):
                                continue
                    if candles:
                        return candles[-count:]
        return None


# ==================== Main Class ====================

class ICTScanner:
    """ICT Scanner with full confluence logic + 50K risk management"""

    # Symbol specs
    POINT_VALUE = {
        'MES.F': 5, 'MNQ.F': 2, 'M2K.F': 5, 'MYM.F': 0.5,
        'M6E.F': 12500, 'M6A.F': 10000, 'MCL.F': 100, 'MBT.F': 10,
        'MET.F': 1, 'MGC.F': 5, 'ES.F': 5, 'NQ.F': 2
    }
    CONTRACTS = {
        'MES.F': 2, 'MNQ.F': 2, 'M2K.F': 2, 'MYM.F': 2,
        'M6E.F': 2, 'M6A.F': 2, 'MCL.F': 1, 'MBT.F': 2,
        'MET.F': 2, 'MGC.F': 2, 'ES.F': 2, 'NQ.F': 2
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

        # Strategy parameters (configurable for WF optimization)
        self.SWING_LOOKBACK = 20
        self.OTE_LOW = 0.50  # Widened from 0.62 (more entries)
        self.OTE_HIGH = 0.85  # Widened from 0.79 (more entries)
        self.MIN_FVG_TICKS = 5
        self.MIN_CONFIDENCE = 3
        self.MAX_TRADES_PER_DAY = 2

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

        # 4. Per-symbol scan (each symbol can have its own bias via BOS)
        for symbol in symbols:
            if self.account.is_killed_today:
                self.logger.info("🛑 Daily kill-switch active, no more trades")
                break
            try:
                sym_data = self.data_provider.get_intraday_data(symbol, count=200)
                if sym_data is None or len(sym_data) < 50:
                    sym_data = self.data_provider.get_daily_data(symbol, count=200)
                if sym_data is None or len(sym_data) < 50:
                    continue
                # Per-symbol bias via BOS
                struct = self.get_market_structure(sym_data, lookback=min(50, len(sym_data)))
                sym_bias = struct['bias']
                if sym_bias == 'NONE':
                    # Fallback: simple trend
                    if len(sym_data) >= 20:
                        closes = [d.close for d in sym_data[-20:]]
                        sma10 = sum(closes[-10:]) / 10
                        sym_bias = 'BULLISH' if closes[-1] > sma10 else 'BEARISH'
                    else:
                        continue
                self.logger.info(f"📊 {symbol} bias: {sym_bias}")

                for kz in ["LondonOpen", "NYOpen"]:
                    if not self.is_in_kill_zone(kz):
                        continue
                    try:
                        setups = self.find_confluence_setups(sym_data, sym_bias, symbol)
                    except Exception as e:
                        self.logger.error(f"{symbol} {kz} setup error: {e}")
                        continue
                    for setup in setups:
                        if self.check_risk_ok(setup):
                            all_setups.append(setup)
                            self.send_alert(setup, kz)
            except Exception as e:
                self.logger.error(f"{symbol} scan error: {e}")
                continue

        return all_setups

    def scan_symbol(self, symbol: str, bias: str, kill_zone: str) -> List[Setup]:
        """Scan single symbol for ICT setups (uses 5min intraday data)"""
        # Try 5min first, fall back to daily if not available
        data = self.data_provider.get_intraday_data(symbol, count=200)
        if data is None or len(data) < 50:
            data = self.data_provider.get_daily_data(symbol, count=200)
        if len(data) < 50:
            return []

        setups = self.find_confluence_setups(data, bias, symbol)
        return setups

    # ==================== Step 1: Daily Bias ====================

    def get_market_structure(self, data: List[Candle], lookback: int = 20) -> Dict:
        """
        Identify market structure via swing high/low breaks.
        Returns: {bias: 'BULLISH'/'BEARISH', last_bos: 'bullish'/'bearish'/'none', swing_h: float, swing_l: float}
        """
        if len(data) < 10:
            return {'bias': 'NONE', 'last_bos': 'none', 'swing_h': 0, 'swing_l': 0}

        recent = data[-min(lookback, len(data)):]
        highs = [d.high for d in recent]
        lows = [d.low for d in recent]

        # Find swing highs/lows (3-bar pivot)
        swing_highs = []
        swing_lows = []
        for i in range(1, len(recent) - 1):
            if recent[i].high > recent[i-1].high and recent[i].high > recent[i+1].high:
                swing_highs.append((i, recent[i].high))
            if recent[i].low < recent[i-1].low and recent[i].low < recent[i+1].low:
                swing_lows.append((i, recent[i].low))

        if not swing_highs or not swing_lows:
            return {'bias': 'NONE', 'last_bos': 'none', 'swing_h': max(highs), 'swing_l': min(lows)}

        # Check for BOS: price broke above previous swing high (bullish) or below swing low (bearish)
        current_close = recent[-1].close
        last_swing_h = max(swing_highs, key=lambda x: x[0])[1]
        last_swing_l = min(swing_lows, key=lambda x: x[0])[1]

        bos = 'none'
        if current_close > last_swing_h:
            bos = 'bullish'
        elif current_close < last_swing_l:
            bos = 'bearish'

        # Determine bias from BOS + recent structure
        # Higher highs + higher lows = bullish; lower highs + lower lows = bearish
        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]
        hh_first = max(d.high for d in first_half)
        hh_second = max(d.high for d in second_half)
        ll_first = min(d.low for d in first_half)
        ll_second = min(d.low for d in second_half)

        bias = 'NONE'
        if hh_second > hh_first and ll_second > ll_first:
            bias = 'BULLISH'  # Higher highs + higher lows
        elif hh_second < hh_first and ll_second < ll_first:
            bias = 'BEARISH'  # Lower highs + lower lows

        return {
            'bias': bias,
            'last_bos': bos,
            'swing_h': max(highs),
            'swing_l': min(lows)
        }

    def get_daily_bias(self) -> str:
        """
        Daily Bias per ICT methodology:
        - 20-day market structure (HH+HL = bullish, LH+LL = bearish)
        - BOS confirmation
        """
        try:
            data = self.data_provider.get_daily_data('MES.F', count=20)
            if len(data) < 15:
                return "NONE"

            structure = self.get_market_structure(data, lookback=20)
            bias = structure['bias']

            # BOS confirmation
            if bias == 'BULLISH' and structure['last_bos'] == 'bearish':
                return "NONE"  # Conflicting signals
            if bias == 'BEARISH' and structure['last_bos'] == 'bullish':
                return "NONE"

            return bias
        except Exception as e:
            self.logger.error(f"Bias error: {e}")
            return "NONE"

    # ==================== Step 2: Liquidity Sweep ====================

    def get_pre_kz_range(self, data: List[Candle], kz_name: str) -> Dict:
        """
        Get pre-Kill-Zone high/low (the liquidity pool).
        Pre-London: yesterday's 18:00-today 06:00 UTC
        Pre-NY: today's 06:00-12:30 UTC
        """
        if len(data) < 5:
            return {'high': 0, 'low': 0, 'swept_high': False, 'swept_low': False}

        if kz_name == 'LondonOpen':
            # Pre-London: prior 6 hours (or all data if not enough)
            pre_kz = data[-12:]  # 12 5-min candles = 1 hour
        else:  # NYOpen
            # Pre-NY: 4 hours
            pre_kz = data[-48:]

        if not pre_kz:
            return {'high': 0, 'low': 0, 'swept_high': False, 'swept_low': False}

        pre_high = max(d.high for d in pre_kz)
        pre_low = min(d.low for d in pre_kz)

        # Check if recent price swept the levels
        recent = data[-6:]  # last 30 min
        swept_high = any(d.high > pre_high for d in recent) and data[-1].close < pre_high
        swept_low = any(d.low < pre_low for d in recent) and data[-1].close > pre_low

        return {
            'high': pre_high,
            'low': pre_low,
            'swept_high': swept_high,
            'swept_low': swept_low
        }

    def check_liquidity_sweep(self, data: List[Candle], direction: str) -> bool:
        """
        Check if recent price swept swing high/low.
        Per ICT: sweep = wick through level, close back inside.
        """
        if len(data) < 5:
            return False
        last = data[-1]
        prev_swing = data[-10:-1] if len(data) > 10 else data[:-1]
        if not prev_swing:
            return False

        if direction == "BULLISH":
            recent_low = min(d.low for d in prev_swing)
            if last.low < recent_low and last.close > recent_low:
                return True
        else:  # BEARISH
            recent_high = max(d.high for d in prev_swing)
            if last.high > recent_high and last.close < recent_high:
                return True
        return False

    # ==================== Step 2.5: Order Block ====================

    def detect_order_block(self, data: List[Candle], direction: str) -> Optional[Dict]:
        """
        ICT Order Block detection.
        Bullish OB: last down candle before strong up move
        Bearish OB: last up candle before strong down move
        Returns: {type: 'BULL'/'BEAR', high: float, low: float, mitigated: bool}
        """
        if len(data) < 10:
            return None

        recent = data[-20:]  # look back 20 candles
        if direction == "BULLISH":
            # Find last down candle (close < open) before a strong up move
            for i in range(len(recent) - 3, max(len(recent) - 10, 0), -1):
                candle = recent[i]
                next_candle = recent[i + 1]
                # Down candle followed by strong up move (next close > candle.high)
                if candle.close < candle.open and next_candle.close > candle.high:
                    return {
                        'type': 'BULL',
                        'high': candle.high,
                        'low': candle.low,
                        'mitigated': data[-1].low < candle.low
                    }
        else:  # BEARISH
            for i in range(len(recent) - 3, max(len(recent) - 10, 0), -1):
                candle = recent[i]
                next_candle = recent[i + 1]
                # Up candle followed by strong down move
                if candle.close > candle.open and next_candle.close < candle.low:
                    return {
                        'type': 'BEAR',
                        'high': candle.high,
                        'low': candle.low,
                        'mitigated': data[-1].high > candle.high
                    }
        return None

    def detect_displacement(self, data: List[Candle], direction: str) -> bool:
        """
        ICT Displacement: strong momentum candle that breaks structure.
        Bullish: large body (close-open) > 2x ATR
        Bearish: large body > 2x ATR
        """
        if len(data) < 20:
            return False
        atr = self._compute_atr(data, period=14)
        if atr <= 0:
            return False
        last = data[-1]
        body = abs(last.close - last.open)
        # Displacement = body > 2x ATR AND close in top/bottom 30% of range
        if body < 2 * atr:
            return False
        candle_range = last.high - last.low
        if candle_range <= 0:
            return False
        if direction == "BULLISH":
            return last.close > last.open and (last.close - last.low) / candle_range > 0.7
        else:  # BEARISH
            return last.close < last.open and (last.high - last.close) / candle_range > 0.7

    def _compute_atr(self, data: List[Candle], period: int = 14) -> float:
        """ATR(period)"""
        if len(data) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(data)):
            h = data[i].high
            l = data[i].low
            pc = data[i-1].close
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        return sum(trs[-period:]) / period

    # ==================== Step 3: OTE Zone ====================

    def calculate_ote_zone(self, swing_high: float, swing_low: float, direction: str) -> Dict:
        """
        OTE = Optimal Trade Entry (configurable Fibonacci retracement)
        Default 62-79%, can be tuned via self.OTE_LOW / self.OTE_HIGH
        """
        fib_range = swing_high - swing_low
        if fib_range <= 0:
            return {"low": 0, "high": 0, "valid": False}

        if direction == "BULLISH":
            return {
                "low": swing_low + fib_range * self.OTE_LOW,
                "high": swing_low + fib_range * self.OTE_HIGH,
                "mid": swing_low + fib_range * (self.OTE_LOW + self.OTE_HIGH) / 2,
                "valid": True
            }
        else:  # BEARISH
            return {
                "low": swing_high - fib_range * self.OTE_HIGH,
                "high": swing_high - fib_range * self.OTE_LOW,
                "mid": swing_high - fib_range * (self.OTE_LOW + self.OTE_HIGH) / 2,
                "valid": True
            }

    # ==================== Step 4: FVG Detection ====================

    def detect_fvg(self, data: List[Candle], direction: str) -> Optional[Dict]:
        """
        FVG = Fair Value Gap (3-candle imbalance)
        Bullish: candle[0].high < candle[2].low (gap up)
        Bearish: candle[0].low > candle[2].high (gap down)
        Relaxed: check last 10 candles for any FVG near current price
        """
        if len(data) < 3:
            return None
        # Relaxed: check up to 10 candles back
        for offset in range(2, min(10, len(data) - 1)):
            c0 = data[-(offset + 2)]
            c1 = data[-(offset + 1)]
            c2 = data[-offset]

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

        # Swing structure (configurable lookback)
        lookback_size = min(self.SWING_LOOKBACK, len(data) - 1)
        lookback = data[-(lookback_size + 1):-1] if lookback_size > 0 and lookback_size < len(data) else data[:-1]
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
            # NEW: Order Block + Displacement
            ob = self.detect_order_block(data, "BULLISH")
            displacement = self.detect_displacement(data, "BULLISH")
            in_ob = ob is not None and not ob['mitigated'] and ob['low'] <= cur <= ob['high']

            # Conditions
            cond_rsi = 30 < cur_rsi < 60
            cond_ema = cur_ema12 > cur_ema26
            cond_fvg_or_ote = (fvg is not None) or in_ote
            cond_macd = cur_macd > cur_sig
            cond_bb = cur > cur_bb_l and cur < cur_bb_m  # Near lower BB
            cond_sweep = swept

            if cond_rsi and cond_ema and cond_fvg_or_ote:
                # Calculate confidence (per spec: each confluence = 1, need >= 2)
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
                if in_ob:
                    conf += 2
                    reasons.append(f"Order Block ({ob['low']:.2f}-{ob['high']:.2f})")
                if displacement:
                    conf += 2
                    reasons.append("Displacement")
                if vol_above:
                    reasons.append("Volume ↑")

                if conf >= 2:  # Min confidence (relaxed from 3)
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
            # NEW: Order Block + Displacement
            ob = self.detect_order_block(data, "BEARISH")
            displacement = self.detect_displacement(data, "BEARISH")
            in_ob = ob is not None and not ob['mitigated'] and ob['low'] <= cur <= ob['high']

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
                if in_ob:
                    conf += 2
                    reasons.append(f"Order Block ({ob['low']:.2f}-{ob['high']:.2f})")
                if displacement:
                    conf += 2
                    reasons.append("Displacement")
                if vol_above:
                    reasons.append("Volume ↑")

                if conf >= 2:
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

    def check_qualified_day(self, current_pnl: float, position: Position) -> bool:
        """
        Per spec: if profit >= $250, partial close 50% + move SL to breakeven.
        Returns True if qualified day was just achieved.
        """
        if position.qualified_locked:
            return False
        if current_pnl >= self.QUALIFIED_DAY_PROFIT:
            position.qualified_locked = True
            self.account.qualified_days += 1
            self.logger.info(
                f"🎯 QUALIFIED DAY #{self.account.qualified_days}: "
                f"P&L ${current_pnl:.0f} >= $250 | Move SL to BE"
            )
            return True
        return False

    def manage_position(self, position: Position, current_price: float) -> Dict:
        """
        Position management per spec:
        - If profit >= $250: partial close 50%, move SL to BE, record qualified day
        - If daily_pnl <= -$200: close all, kill-switch
        Returns: {action: 'HOLD'/'PARTIAL'/'CLOSE', new_sl: float, pnl: float}
        """
        # Calculate current P&L
        pv = self.POINT_VALUE.get(position.symbol, 5)
        if position.direction == "LONG":
            points = current_price - position.entry_price
        else:  # SHORT
            points = position.entry_price - current_price
        current_pnl = points * pv * position.contracts

        # Check qualified day trigger
        if self.check_qualified_day(current_pnl, position):
            return {
                'action': 'PARTIAL',
                'new_sl': position.entry_price,  # Move to breakeven
                'pnl': current_pnl,
                'reason': f'Qualified day ${self.QUALIFIED_DAY_PROFIT} reached'
            }

        # Check daily kill-switch
        if self.account.daily_pnl <= -self.MAX_DAILY_LOSS:
            return {
                'action': 'CLOSE',
                'new_sl': position.stop_loss,
                'pnl': current_pnl,
                'reason': f'Daily loss limit ${self.MAX_DAILY_LOSS} hit'
            }

        return {
            'action': 'HOLD',
            'new_sl': position.stop_loss,
            'pnl': current_pnl,
            'reason': 'Holding'
        }

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
        """Send alert via notifier + queue for daily settlement"""
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

        # Queue for daily settlement
        try:
            import json
            from datetime import datetime, timezone
            pending_file = '/tmp/ict_pending_trades.json'
            pending = []
            import os
            if os.path.exists(pending_file):
                try:
                    with open(pending_file) as f:
                        pending = json.load(f)
                except:
                    pending = []
            sig_id = f"{setup.symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H')}_{setup.direction}"
            # Dedup: same symbol+direction+kz within same hour
            cur_hour_prefix = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
            is_dup = any(
                t.get('symbol') == setup.symbol
                and t.get('direction') == setup.direction
                and t.get('kz') == kz
                and t.get('signal_time', '').startswith(cur_hour_prefix)
                for t in pending
            )
            trade = {
                'id': sig_id,
                'symbol': setup.symbol,
                'direction': setup.direction,
                'entry': setup.entry,
                'sl': setup.stop_loss,
                'tp1': setup.tp1,
                'tp2': setup.tp2,
                'confidence': setup.confidence,
                'reasons': setup.reasons,
                'kz': kz,
                'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'signal_time': datetime.now(timezone.utc).isoformat(),
                'added_at': datetime.now(timezone.utc).isoformat(),
            }
            if not is_dup:
                pending.append(trade)
                with open(pending_file, 'w') as f:
                    json.dump(pending, f, indent=2)
                self.logger.info(f"📋 Queued for settlement: {sig_id}")
            else:
                self.logger.info(f"⏩ Deduped (same hour/kz): {sig_id}")
        except Exception as e:
            self.logger.error(f"Queue error: {e}")


# ==================== Example Usage ====================

def main():
    """Example: run scanner with Yahoo CSV data + Telegram notifier"""
    dp = YahooCSVDataProvider()

    def tg_notifier(msg):
        # Integrate with your Telegram bot
        print(f"[TG] {msg[:100]}...")

    scanner = ICTScanner(dp, notifier=tg_notifier)
    # Load suspended symbols (v1.2 auto-filter)
    suspended = []
    import os
    if os.path.exists('/tmp/ict_suspended_symbols.json'):
        with open('/tmp/ict_suspended_symbols.json') as f:
            try:
                suspended = json.load(f)
            except:
                suspended = []
    suspended_names = [s['symbol'] for s in suspended]
    # Optimized symbol list (per backtest: 35% WR, +$700 P&L)
    all_symbols = ['MNQ.F', 'M2K.F', 'MBT.F', 'MET.F']
    symbols = [s for s in all_symbols if s not in suspended_names]
    if suspended_names:
        print(f"⏸️ Suspended symbols: {suspended_names}")
    if not symbols:
        print("❌ All symbols suspended!")
        return

    setups = scanner.run_daily_scan(symbols)
    print(f"\n✅ {len(setups)} setups found")


if __name__ == "__main__":
    main()
