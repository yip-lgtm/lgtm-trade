#!/bin/bash
cd /home/node/.openclaw/workspace
echo "=== metrics ==="
python3 ict_auto_iteration.py metrics 2>&1 | head -15
echo "=== suspend ==="
python3 ict_auto_iteration.py suspend 2>&1
echo "=== suggestions ==="
python3 ict_auto_iteration.py suggestions 2>&1
echo "=== report ==="
python3 ict_auto_iteration.py report 2>&1
