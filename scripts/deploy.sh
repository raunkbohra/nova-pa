#!/bin/bash
# =============================================================================
# NOVA Deploy Script — Run from LOCAL machine to deploy to VPS
# =============================================================================
# Usage: bash scripts/deploy.sh [ssh-host]
# Example: bash scripts/deploy.sh ubuntu@65.21.xxx.xxx
# Example: bash scripts/deploy.sh nova-vps   (if in ~/.ssh/config)
# =============================================================================
set -e

SSH_HOST="${1:-nova-vps}"
NOVA_DIR="nova-pa"

echo "Deploying NOVA to $SSH_HOST..."

# Push latest code
echo "[1/3] Pushing to GitHub..."
git push origin main

# Pull on server and restart
echo "[2/3] Pulling on server..."
ssh "$SSH_HOST" "cd $NOVA_DIR && git pull origin main"

# Reinstall deps if requirements changed
echo "[3/3] Restarting NOVA..."
ssh "$SSH_HOST" "cd $NOVA_DIR && source venv/bin/activate && pip install -q -r requirements.txt && pm2 restart nova"

echo ""
echo "Deploy complete! Checking status..."
ssh "$SSH_HOST" "pm2 list && curl -s http://localhost:8000/health"
