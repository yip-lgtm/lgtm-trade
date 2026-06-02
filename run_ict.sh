#!/bin/bash
# Load API key from .env file (git-ignored)
if [ -f /home/node/.openclaw/workspace/.env ]; then
    export $(grep -v '^#' /home/node/.openclaw/workspace/.env | xargs)
fi
cd /home/node/.openclaw/workspace
/usr/bin/python3 ict_signals.py >> /tmp/ict_live.log 2>&1