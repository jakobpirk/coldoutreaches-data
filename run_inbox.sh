#!/usr/bin/env bash
# Inbox reply loop — runs every ~30 min from cron, separate from the heavy
# design pipeline (auto_run.sh). It drafts replies to new inbox mail (never
# sends), then mails the ones you approved by ticking "Send svar" in Notion.
#
# Install (crontab -e):
#   */30 * * * * /opt/coldoutreaches/run_inbox.sh >> /opt/coldoutreaches/data/inbox.log 2>&1
set -uo pipefail
cd "$(dirname "$0")" || exit 1
set -a; source infra/.env 2>/dev/null; set +a
export LEADS_DB="${LEADS_DB:-data/leads.db}"
export PYTHONUNBUFFERED=1
ts(){ date -Is; }

# don't overlap with a previous tick still running
exec 8>/tmp/coldoutreaches_inbox.lock
if ! flock -n 8; then echo "[$(ts)] inbox loop already running — skip"; exit 0; fi

echo "[$(ts)] pull reply templates from Notion"
python3 pull_guidance.py >/dev/null 2>&1 || true

echo "[$(ts)] draft replies for new inbox mail"
python3 reply_agent.py || true

echo "[$(ts)] send approved replies (the 'Send svar' ticks)"
python3 send_replies.py || true

echo "[$(ts)] done"
