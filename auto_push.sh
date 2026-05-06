#!/bin/bash
# Auto push script for lstm-trading repo
SSH_KEY_FILE="$HOME/.ssh/id_rsa"
REPO_DIR="/home/node/.openclaw/workspace"

# Start ssh-agent if not running
if [ -z "$SSH_AUTH_SOCK" ]; then
    eval $(ssh-agent -s) > /dev/null 2>&1
fi

# Add key if not already added
ssh-add $SSH_KEY_FILE 2>/dev/null

# Push
cd $REPO_DIR
git push origin master 2>&1
