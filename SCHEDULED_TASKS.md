# OpenClaw Scheduled Tasks

## Cron Jobs (Active)
```
30 12 * * 1-5  →  NY KZ 12:30 UTC (Mon-Fri)
                   cd /home/node/.openclaw/workspace && /usr/bin/python3 xgb_live.py >> /tmp/xgb_live.log 2>&1

0 6 * * 1-5     →  London KZ 06:00 UTC (Mon-Fri)
                   cd /home/node/.openclaw/workspace && /usr/bin/python3 xgb_live.py >> /tmp/xgb_live.log 2>&1
```

## Scripts
- `xgb_live.py` - XGBoost + Kronos fusion live trading
- `gemma_signals.py` - Pure Gemma LLM signals (needs OPENAI_API_KEY env var)
- `gemma_validator.py` - Gemma LLM validator for signals

## Log Files
- `/tmp/xgb_live.log` - XGBoost live trading log

## Git Push Status
Last push: 2026-05-19 15:01 UTC