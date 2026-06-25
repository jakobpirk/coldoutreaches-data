#!/usr/bin/env bash
# Nightly pipeline — runs on the VPS (host cron, not inside the n8n container,
# because this needs Python + the Claude Code CLI). See infra/INFRA_SETUP.md.
set -euo pipefail
cd "$(dirname "$0")"

export LEADS_DB="${LEADS_DB:-data/leads.db}"
export PYTHONUNBUFFERED=1
AREA="${SCAN_AREA:-svendborg}"
PREP_LIMIT="${PREP_LIMIT:-12}"          # cap claude -p work to protect the weekly cap

log(){ echo "[nightly $(date -Is)] $*"; }

log "pull agent guidance from Notion"
python3 pull_guidance.py || true

log "check inbox (replies, tickets, follow-ups) — only new mail"
python3 inbox_poll.py || true

log "scan area=$AREA"
python3 run_scan.py --area "$AREA"

log "prep (claude -p classify/draft), limit=$PREP_LIMIT"
python3 prep.py --limit "$PREP_LIMIT" || true

log "maintain follow-ups (10-day nudges + outbox drafts + 3-month expiry)"
python3 followups.py || true

log "sync qualified leads to Notion"
python3 notion_sync.py || true

# auto-pick the top ugly/borderline leads and build their demos (opt-in: set DEMO_LIMIT>0 in .env)
if [ "${DEMO_LIMIT:-0}" -gt 0 ]; then
  log "auto-building up to ${DEMO_LIMIT} demos (deploy + design)"
  python3 select_demos.py --limit "$DEMO_LIMIT" || true
  python3 prep.py --stage draft || true      # draft outreach for the freshly built demos
  python3 notion_sync.py
fi

log "auto-fix small support tickets (branch -> PR; never production)"
python3 fix_agent.py --limit "${FIX_LIMIT:-2}" || true

log "sync tickets to Notion"
python3 tickets_sync.py || true

log "send approved outbox emails (the 'Send now' ticks)"
python3 send_outbox.py || true

# local backup of the DB only — do NOT push from the VPS (it diverges from your
# code pushes). The live DB persists on the VPS disk regardless.
cp -f "$LEADS_DB" "${LEADS_DB}.bak" 2>/dev/null || true
log "done"
