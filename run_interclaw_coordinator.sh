#!/bin/bash
# InterClaw Coordinator startup script
# Run this on boot to keep the coordinator alive

cd /home/node/.openclaw/workspace/skills
exec node interclaw_coordinator_standalone.js
