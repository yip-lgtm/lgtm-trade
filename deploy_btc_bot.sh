#!/bin/bash
# ============================================
# BTC 5m Bot v3 - Deploy to Seoul VPS
# ============================================
# Usage: Run this script from your local machine
# Requirements: sshpass installed
# ============================================

set -e

VPS_HOST="43.128.147.184"
VPS_USER="ubuntu"
VPS_PASS='6Lf2&>$?O-}=SSEuQgS)'

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/home/ubuntu"

echo "=========================================="
echo "  BTC 5m Bot v3 - Deploy"
echo "=========================================="

# 1. Upload files
echo "[1/4] Uploading files..."
sshpass -p "$VPS_PASS" scp -o StrictHostKeyChecking=no \
  "$SRC_DIR/btc_5m_bot.py" \
  "$SRC_DIR/btc_5m_bot.env" \
  "$SRC_DIR/btc_5m_bot.service" \
  "$SRC_DIR/requirements.txt" \
  "$VPS_USER@$VPS_HOST:$REMOTE_DIR/"

# 2. Install deps
echo "[2/4] Installing Python dependencies..."
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" << 'ENDSSH'
sudo apt update && sudo apt install -y python3-pip
pip3 install -r /home/ubuntu/requirements.txt
ENDSSH

# 3. Install service
echo "[3/4] Setting up systemd service..."
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" << 'ENDSSH'
sudo cp /home/ubuntu/btc_5m_bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable btc_5m_bot
sudo systemctl start btc_5m_bot
ENDSSH

# 4. Verify
echo "[4/4] Checking status..."
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" \
  "sudo systemctl status btc_5m_bot --no-pager -l | head -20"

echo ""
echo "=========================================="
echo "  ✅ Deploy complete!"
echo ""
echo "  View logs: sudo journalctl -u btc_5m_bot -f"
echo "  Stop bot:  sudo systemctl stop btc_5m_bot"
echo "  Start bot: sudo systemctl start btc_5m_bot"
echo "=========================================="