#!/usr/bin/env python3
"""
BTC 5m Trader - Telegram Command Handler
Listens for /btc commands and responds with bot status, config changes, etc.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Config paths
PROJECT_ROOT = "/home/node/.openclaw/workspace"
STATE_FILE = os.environ.get("STATE_FILE", f"{PROJECT_ROOT}/btc_5m_state.json")
CONFIG_FILE = os.environ.get("CONFIG_FILE", f"{PROJECT_ROOT}/btc_5m_config.json")
ENV_FILE = os.environ.get("ENV_FILE", f"{PROJECT_ROOT}/config/.env")

COMMANDS = """
<b>BTC 5m Trader - Commands</b>

<code>/btc start</code> - Start trading loop
<code>/btc stop</code> - Stop trading loop
<code>/btc status</code> - Show bot status
<code>/btc info</code> - Show current config
<code>/btc dryrun [on|off]</code> - Toggle dry run mode
<code>/btc prob [0.87]</code> - Set MIN_PROB
<code>/btc edge [0.03]</code> - Set MIN_EDGE
<code>/btc cycles</code> - Show cycle count + history stats
<code>/btc help</code> - Show this help
"""

def load_config():
    """Load current config from state + env"""
    config = {
        "DRY_RUN": "true",
        "MIN_PROB": "0.87",
        "MIN_EDGE": "0.03",
        "CHECK_INTERVAL": "81",
    }
    
    # Load from env file if exists
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    config[key.strip()] = val.strip()
    
    # Override with runtime state if exists
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            for k, v in data.items():
                config[k] = str(v)
    
    return config

def load_state():
    """Load state from state file"""
    if not os.path.exists(STATE_FILE):
        return {"cycle_count": 0, "history": []}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"cycle_count": 0, "history": []}

def cmd_status():
    """Return current bot status"""
    state = load_state()
    config = load_config()
    
    history = state .get("history", [])
    last = history[-1] if history else None
    
    msg = f"""📊 <b>BTC 5m Trader Status</b>

🔹 Mode: <b>{'DRY_RUN' if config.get('DRY_RUN') == 'true' else 'LIVE'}</b>
🔹 MIN_PROB: {config.get('MIN_PROB', '0.87')}
🔹 MIN_EDGE: {config.get('MIN_EDGE', '0.03')}
🔹 Cycles: {state.get('cycle_count', 0)}
🔹 Last signal: {last.get('direction', 'none') if last else 'none'} (p̂={last.get('prob_continue', 0):.3f})"""
    return msg

def cmd_info():
    """Return current config"""
    config = load_config()
    return f"""⚙️ <b>Current Config</b>

DRY_RUN: {config.get('DRY_RUN', 'true')}
MIN_PROB: {config.get('MIN_PROB', '0.87')}
MIN_EDGE: {config.get('MIN_EDGE', '0.03')}
CHECK_INTERVAL: {config.get('CHECK_INTERVAL', '81')}s
STATE_WINDOW: {config.get('STATE_WINDOW', '4')}
ATR_MULT: {config.get('ATR_MULT', '0.8')}
VOL_MULT: {config.get('VOL_MULT', '0.6')}
MAX_DAILY_LOSS: {config.get('MAX_DAILY_LOSS', '30')}$
MAX_POSITION: {config.get('MAX_POSITION', '5')}$"""

def cmd_cycles():
    """Show cycle history stats"""
    state = load_state()
    history = state.get("history", [])
    total = len(history)
    signals = [e for e in history if e.get("signal")]
    wins = [e for e in signals if e.get("result") == "win"]
    losses = [e for e in signals if e.get("result") == "loss"]
    
    probs = [e.get("prob_continue", 0) for e in signals]
    max_prob = max(probs) if probs else 0
    avg_prob = sum(probs) / len(probs) if probs else 0
    
    win_rate = f"{len(wins)/len(signals)*100:.1f}%" if signals else "N/A"
    
    return f"""📈 <b>Cycle Stats</b>

Total cycles: {state.get('cycle_count', 0)}
Signals triggered: {len(signals)}
Wins: {len(wins)}
Losses: {len(losses)}
Win rate: {win_rate}
Max p̂: {max_prob:.3f}
Avg p̂: {avg_prob:.3f}"""

def cmd_help():
    return COMMANDS

def handle_command(text):
    """Parse and handle /btc command"""
    text = text.strip()
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    
    if cmd in ["/btc", "help"]:
        return cmd_help()
    elif cmd == "status":
        return cmd_status()
    elif cmd == "info":
        return cmd_info()
    elif cmd == "cycles":
        return cmd_cycles()
    elif cmd == "start":
        # Write a control flag
        with open(f"{PROJECT_ROOT}/btc_5m_control.json", "w") as f:
            json.dump({"running": True, "updated_at": datetime.now(timezone.utc).isoformat()}, f)
        return "✅ Trading loop STARTED"
    elif cmd == "stop":
        with open(f"{PROJECT_ROOT}/btc_5m_control.json", "w") as f:
            json.dump({"running": False, "updated_at": datetime.now(timezone.utc).isoformat()}, f)
        return "🛑 Trading loop STOPPED"
    elif cmd == "dryrun":
        mode = parts[1].lower() if len(parts) > 1 else None
        if mode == "on":
            return update_config("DRY_RUN", "true")
        elif mode == "off":
            return update_config("DRY_RUN", "false")
        else:
            cfg = load_config()
            current = cfg.get("DRY_RUN", "true")
            return f"DRY_RUN is <b>{current}</b>. Use /btc dryrun on|off"
    elif cmd == "prob":
        if len(parts) > 1:
            try:
                val = float(parts[1])
                return update_config("MIN_PROB", str(val))
            except ValueError:
                return "❌ Invalid probability. Use: /btc prob 0.87"
        else:
            cfg = load_config()
            return f"MIN_PROB is <b>{cfg.get('MIN_PROB', '0.87')}</b>"
    elif cmd == "edge":
        if len(parts) > 1:
            try:
                val = float(parts[1])
                return update_config("MIN_EDGE", str(val))
            except ValueError:
                return "❌ Invalid edge. Use: /btc edge 0.03"
        else:
            cfg = load_config()
            return f"MIN_EDGE is <b>{cfg.get('MIN_EDGE', '0.03')}</b>"
    else:
        return f"❓ Unknown command: {cmd}\n\n{cmd_help()}"

def update_config(key, value):
    """Update a config value in .env file"""
    env_path = ENV_FILE
    lines = []
    updated = False
    
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
    
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            updated = True
        else:
            new_lines.append(line)
    
    if not updated:
        new_lines.append(f"{key}={value}\n")
    
    with open(env_path, "w") as f:
        f.writelines(new_lines)
    
    return f"✅ <b>{key}</b> updated to <b>{value}</b>"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(handle_command(" ".join(sys.argv[1:])))
    else:
        print("Usage: python3 btc_5m_commands.py <command>")