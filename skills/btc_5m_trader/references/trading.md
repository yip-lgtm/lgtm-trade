# BTC 5m Trading Logic

## Overview

The bot trades Polymarket "BTC-updown-5m-{timestamp}" markets every 5 minutes using a **Markov Chain streak model** combined with **ATR** and **Volume** filters.

## Market Structure

Each 5-minute window creates a new market on Polymarket:
- `btc-updown-5m-{window_ts}` where `window_ts = (timestamp // 300) * 300`
- YES token pays out if BTC closes UP relative to window open
- NO token pays out if BTC closes DOWN

## Step 1: Fetch BTC Candles

Source: OKX API (`https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=5m`)

- Fetch last 1440 candles (5 days of 5m data)
- Compute direction: UP if close > open, DOWN otherwise
- Compute streak length at each candle

## Step 2: Streak-Based State

State at candle `i` = sequence of streak lengths for last `STATE_WINDOW` candles:
```
state = streaks[i-STATE_WINDOW:i]  # e.g. [1,2,3,1]
```

## Step 3: Transition Matrix (ATR+Vol Filtered)

For each state, count next-direction transitions **only where filters pass**:
- ATR filter: `ATR[i] > avg_ATR × ATR_MULT` (default 0.8)
- Vol filter: `Vol[i] > avg_Vol × VOL_MULT` (default 0.6)

Build probability table:
```
P(state → UP) = count_UP / (count_UP + count_DOWN)
P(state → DOWN) = count_DOWN / (count_UP + count_DOWN)
```

## Step 4: Prediction

Given current state, lookup conditional probability:
```
p̂ = P(next_direction | current_state)
```

## Step 5: Signal Generation

Compare against market price `q` (from Polymarket):
```
edge = p̂ - q
signal = (p̂ >= MIN_PROB) AND (edge >= MIN_EDGE) AND (ATR_filter) AND (Vol_filter)
direction = argmax(UP_prob, DOWN_prob)
```

If signal → execute trade (or log in DRY_RUN)

## Step 6: Execution (Live Mode)

Using `py_clob_client_v2`:
```python
from py_clob_client_v2 import ClobClient, SignatureTypeV2
from py_clob_client_v2 import OrderArgs, PartialCreateOrderOptions
from py_clob_client_v2.order_builder.constants import BUY, SELL

# Derive L2 API key from private key
temp_client = ClobClient(host='https://clob.polymarket.com', key=private_key, chain_id=137)
api_creds = temp_client.create_or_derive_api_key()

client = ClobClient(
    host='https://clob.polymarket.com',
    key=private_key,
    chain_id=137,
    creds=api_creds,
    signature_type=SignatureTypeV2.POLY_1271,  # deposit wallet
    funder=funder_address
)

# Get market token_id from slug
token_id = market['clobTokenIds'][0 if direction=='UP' else 1]

# Place order
response = client.create_and_post_order(
    OrderArgs(token_id=token_id, price=entry_price, size=size, side=BUY/SELL),
    options=PartialCreateOrderOptions(tick_size='0.01', neg_risk=False),
)
```

## ATR Computation

True Range = max(H-L, |H-prev_close|, |L-prev_close|)
ATR(14) = simple moving average of last 14 True Range values

```python
def compute_atr(klines, index, period=14):
    trs = []
    for j in range(1, period + 1):
        high = float(klines[index - j + 1][2])
        low = float(klines[index - j + 1][3])
        prev_close = float(klines[index - j][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs)
```

## Position Sizing

```
position_size = min(MAX_POSITION, 0.02 * account_balance_usd)
size = position_size / entry_price
```

Default: $5 per trade (= 2% of ~$250 account, or whatever MAX_POSITION is set to)
