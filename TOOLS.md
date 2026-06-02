# TOOLS.md - Local Notes

## Trading Accounts

### Apex Futures (Apex50k)
- Account Balance: $50,000 USD
- Profit Target: $3,000 (5 trading days)
- Max Drawdown: $2,000 (Intraday Trail) - liquidation at $48,000
- Min Days To Pass: 5 days (daily net profit ≥ $250 = 1 qualifying day)
- Max Contracts: 2 micro contracts per trade (MCL: 1)
- Daily SL: $200 kill-switch (stop if -$200 in one day)
- R:R 1:3 (TP1 = 3×SL, TP2 = 6×SL)
- Scaling: Built-in Price Action

### Contract Specs
```js
POINT_VALUE = {
  'MES.F':5, 'MNQ.F':2, 'M2K.F':5, 'MYM.F':0.5,
  'M6E.F':12500, 'M6A.F':10000, 'MCL.F':100
}
PRECISION = {
  'MES.F':2, 'MNQ.F':2, 'M2K.F':2, 'MYM.F':2,
  'M6E.F':4, 'M6A.F':4, 'MCL.F':2
}
```
- SL_TICKS: 10 ticks, TP1_TICKS: 10 ticks, TP2_TICKS: 20 ticks

## Kill Zone Schedule (Summer, HKT)
- London: 14:00-17:00 HKT
- NY: 20:30-23:00 HKT

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
