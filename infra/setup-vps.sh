#!/usr/bin/env bash
# Provision a fresh Ubuntu 24.04 Hetzner CX22 for ColdOutreaches.
# Run as root:  bash setup-vps.sh [optional-git-url-of-your-private-repo]
set -euo pipefail

APP_DIR=/opt/coldoutreaches
REPO="${1:-}"

echo "==> system update"
apt-get update && apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw python3 python3-pip

echo "==> swap (4GB box — headroom for Claude/Chromium bursts)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Docker"
curl -fsSL https://get.docker.com | sh

echo "==> Node + Claude Code CLI"
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs
npm install -g @anthropic-ai/claude-code

echo "==> Python deps"
pip3 install --break-system-packages requests beautifulsoup4 lxml

echo "==> firewall (SSH only; n8n stays on localhost, reached via SSH tunnel)"
ufw allow OpenSSH && ufw --force enable

echo "==> app dir"
mkdir -p "$APP_DIR" && cd "$APP_DIR"
if [ -n "$REPO" ]; then git clone "$REPO" . ; else echo "  (copy your project files into $APP_DIR)"; fi
mkdir -p data

echo "==> install bundled Claude skills (frontend-design) for claude -p"
mkdir -p /root/.claude/skills
cp -r skills/* /root/.claude/skills/ 2>/dev/null || true

cat <<'NEXT'

==> Done. Next steps:
  1. cp infra/.env.example infra/.env   &&  edit infra/.env with your secrets
  2. docker compose -f infra/docker-compose.yml up -d        # start n8n
  3. claude   # log in once  (or export CLAUDE_CODE_OAUTH_TOKEN in /etc/environment)
  4. Add the nightly cron (see INFRA_SETUP.md)
  5. SSH tunnel to n8n:  ssh -L 5678:localhost:5678 root@<ip>  -> http://localhost:5678
NEXT
