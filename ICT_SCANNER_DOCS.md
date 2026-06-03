# ICT Scanner v5 - Complete Logic Documentation

## Overview
The ICT (Inner Circle Trader) Scanner is a technical analysis scanner for futures trading that combines multiple ICT concepts with traditional TA indicators. It runs on each KZ session (London 14:00-15:00 HKT, NY 20:30-21:30 HKT) and only sends alerts when ICT conditions align during a Kill Zone.

## Core Philosophy
ICT trading focuses on:
1. **Liquidity sweeps** at swing highs/lows
2. **Market structure** (HH, HL, LH, LL)
3. **Fair Value Gaps (FVG)** - imbalances to be filled
4. **Optimal Trade Entry (OTE)** zones (62%-79% Fibonacci)
5. **Kill Zone timing** - high-probability time windows

## Strategy Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. DATA LOAD                                                 │
│    - Read CSV (255 daily candles per symbol)                │
│    - Parse OHLCV into arrays                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. INDICATOR CALCULATION                                     │
│    - RSI(14)                                                 │
│    - EMA(12), EMA(26)                                        │
│    - ATR(14)                                                 │
│    - MACD(12, 26, 9)                                         │
│    - Bollinger Bands(20, 2σ)                                 │
│    - Volume SMA(20)                                          │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. ICT STRUCTURE DETECTION                                   │
│    - Swing High/Low (20-period)                              │
│    - Fibonacci Range                                         │
│    - FVG Bull/Bear                                           │
│    - OTE Zone (0.62-0.79)                                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. SIGNAL EVALUATION                                         │
│    - Check Long conditions                                   │
│    - Check Short conditions                                  │
│    - Compute confidence (0-5)                                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. KILL ZONE FILTER                                          │
│    - Check if current time is in London or NY KZ             │
│    - If not in KZ → skip                                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. RISK MANAGEMENT                                           │
│    - SL = $200 per trade                                     │
│    - TP1 = $600 (3× SL)                                      │
│    - TP2 = $1,200 (6× SL)                                    │
│    - Calculate entry, SL, TP1, TP2 prices                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. ALERT                                                     │
│    - Print to console                                        │
│    - Push to kzAlerts                                        │
│    - Send Telegram if signal during KZ                       │
└─────────────────────────────────────────────────────────────┘
```

## Detailed Pseudo Code

### Step 1: Data Load
```
FOR each symbol IN [MES.F, MNQ.F, M2K.F, MYM.F, M6E.F, M6A.F, MCL.F, MBT.F, MET.F]:
    data = read_csv(symbol + ".csv")
    IF data.length < 50:
        SKIP (insufficient data)
    
    closes = [candle.close for candle in data]
    highs  = [candle.high for candle in data]
    lows   = [candle.low for candle in data]
    volumes = [candle.volume for candle in data]
    i = last_index (current candle)
```

### Step 2: Indicator Calculation
```
# RSI(14)
rsi[i] = 100 - 100 / (1 + avg_gain(14) / avg_loss(14))

# EMA(12, 26)
k_12 = 2 / (12 + 1) = 0.1538
k_26 = 2 / (26 + 1) = 0.0741
ema12[i] = close[i] * k_12 + ema12[i-1] * (1 - k_12)
ema26[i] = close[i] * k_26 + ema26[i-1] * (1 - k_26)

# ATR(14)
tr[i] = max(high-low, |high-prev_close|, |low-prev_close|)
atr[i] = (atr[i-1] * 13 + tr[i]) / 14

# MACD(12, 26, 9)
macd_line = ema12 - ema26
signal_line = ema(macd_line, 9)
histogram = macd_line - signal_line

# Bollinger Bands(20, 2σ)
bb_middle = sma(close, 20)
bb_std = std(close, 20)
bb_upper = bb_middle + 2 * bb_std
bb_lower = bb_middle - 2 * bb_std

# Volume SMA(20)
vol_sma = average(volume, last 20)
```

### Step 3: ICT Structure Detection
```
# Swing High/Low (20-period lookback)
FOR each index j >= 20:
    swingH[j] = max(highs[j-20..j])
    swingL[j] = min(lows[j-20..j])
    fibR[j] = swingH[j] - swingL[j]

# FVG (Fair Value Gap) - 2-candle imbalance
fvgBull[j] = 1 IF lows[j-1] > highs[j-2]  # Gap up
fvgBear[j] = 1 IF highs[j-1] < lows[j-2]  # Gap down

# OTE Zone (Optimal Trade Entry 62-79%)
ote_79_bull = swingL + fibR * 0.79
ote_79_bear = swingH - fibR * 0.79
ote_62_bull = swingL + fibR * 0.62
ote_62_bear = swingH - fibR * 0.62

inOteBull[j] = 1 IF close[j] IN [ote_62_bull, ote_79_bull]
inOteBear[j] = 1 IF close[j] IN [ote_62_bear, ote_79_bear]
```

### Step 4: Signal Evaluation

#### Long Signal (Bullish)
```
bullRSI    = 30 < RSI < 60          # Not overbought
bullEMA    = EMA12 > EMA26           # Uptrend
bullFVG    = fvgBull[i] == 1 OR inOteBull[i] == 1
bullBreak  = close > swingH * 0.998 # Near swing high (breakout)
bullMACD   = macd_line > signal_line
bullBB     = close > bb_lower AND close < (bb_upper + bb_lower)/2

IF bullRSI AND bullEMA AND (bullFVG OR bullBreak):
    signal = 1 (Long)
    confidence = (FVG_or_OTE ? 3 : 1) + (MACD_bull ? 1 : 0) + (BB_lower ? 1 : 0)
    reasons = [EMA交叉睇好, FVG/OTE做多 OR 突破SW High, MACD陽, 成交量放大]
```

#### Short Signal (Bearish)
```
bearRSI    = 40 < RSI < 70          # Not oversold
bearEMA    = EMA12 < EMA26           # Downtrend
bearFVG    = fvgBear[i] == 1 OR inOteBear[i] == 1
bearBreak  = close < swingL * 1.002 # Near swing low (breakdown)
bearMACD   = macd_line < signal_line
bearBB     = close < bb_upper AND close > (bb_upper + bb_lower)/2

IF bearRSI AND bearEMA AND (bearFVG OR bearBreak):
    signal = -1 (Short)
    confidence = (FVG_or_OTE ? 3 : 1) + (MACD_bear ? 1 : 0) + (BB_upper ? 1 : 0)
    reasons = [EMA交叉睇淡, FVG/OTE做空 OR 突破SW Low, MACD陰, 成交量放大]
```

### Step 5: Kill Zone Filter
```
now_utc = current UTC time
h = now_utc.hour, m = now_utc.minute

isInKZ:
    London KZ: 06:00-07:00 UTC
    NY KZ: 12:30-13:30 UTC

IF NOT isInKZ:
    SKIP signal (don't send alert)

IF isInKZ AND signal != 0:
    PROCEED to risk management
```

### Step 6: Risk Management
```
SL_AMOUNT = $200
TP1_MULT = 3
TP2_MULT = 6

point_value = lookup(symbol)  # MES.F: 5, MNQ.F: 2, etc.
contracts = lookup(symbol)    # Max 2 micro, MCL 1

sl_points = SL_AMOUNT / (point_value * contracts)
entry = close[i]

IF signal == 1 (Long):
    sl = entry - sl_points
    tp1 = entry + (TP1_MULT * sl_points)  # +$600 worth
    tp2 = entry + (TP2_MULT * sl_points)  # +$1,200 worth

IF signal == -1 (Short):
    sl = entry + sl_points
    tp1 = entry - (TP1_MULT * sl_points)
    tp2 = entry - (TP2_MULT * sl_points)

est_pnl = TP1_MULT * SL_AMOUNT * contracts
```

### Step 7: Alert Output
```
IF signal != 0 AND inKZ:
    print(🔥🔥🔥 {kz} KILL ZONE 有效信號！！！)
    print(Entry: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2})
    print(風險 $200 | 目標 TP1:${600} TP2:${1200} | {contracts}合約)
    kzAlerts.append({symbol, signal, entry, sl, tp1, tp2, contracts, kz})
    
# Telegram (via scheduler)
send_telegram(message)
```

## Risk Parameters by Symbol

| Symbol | Point Value | Contracts | SL Ticks | TP1 Ticks | TP2 Ticks |
|--------|-------------|-----------|----------|-----------|-----------|
| MES.F  | $5          | 2         | 10       | 30        | 60        |
| MNQ.F  | $2          | 2         | 10       | 30        | 60        |
| M2K.F  | $5          | 2         | 10       | 30        | 60        |
| MYM.F  | $0.5        | 2         | 10       | 30        | 60        |
| M6E.F  | $12,500     | 2         | 10       | 30        | 60        |
| M6A.F  | $10,000     | 2         | 10       | 30        | 60        |
| MCL.F  | $100        | 1         | 10       | 30        | 60        |
| MBT.F  | $10         | 2         | 10       | 30        | 60        |
| MET.F  | $1          | 2         | 10       | 30        | 60        |

## Confidence Scoring

| Component | Points |
|-----------|--------|
| FVG or OTE present | 3 |
| MACD aligned | 1 |
| Bollinger position | 1 |
| **Max** | **5** |

Confidence interpretation:
- 1-2: Weak signal (consider skipping)
- 3: Moderate signal
- 4-5: Strong signal

## Known Limitations

1. **Daily data only** - Can't see intraday 5m/15m price action
2. **No real-time** - CSV is end-of-day
3. **No ML/LSTM** - Pure technical
4. **No backtest validation** - Strategy unverified
5. **Static SL/TP** - Doesn't adapt to volatility
6. **No position sizing based on volatility**

## Future Enhancements

- [ ] Order Block detection
- [ ] Breaker blocks
- [ ] Multi-timeframe analysis (15m + 1h + 4h)
- [ ] Volatility-adjusted position sizing
- [ ] Walk-forward optimization
- [ ] Win rate tracking
- [ ] Dynamic SL based on ATR

## Related Files

- `ict_scanner_v5.cjs` - Main scanner (CommonJS)
- `ict_scanner_v5.js` - Same but ESM (broken with type:module)
- `kz_scheduler.js` - Schedules LSTM/KZ sessions
- `dl_node.cjs` - Yahoo Finance data downloader
- `live_trading_journal.csv` - Signal log
- `btc_5m_bot.py` - BTC 5m Markov bot (separate strategy)
