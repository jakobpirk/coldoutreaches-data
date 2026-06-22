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

log "scan area=$AREA"
python3 run_scan.py --area "$AREA"

log "prep (claude -p classify/research/draft), limit=$PREP_LIMIT"
python3 prep.py --limit "$PREP_LIMIT"

log "sync qualified leads to Notion"
python3 notion_sync.py

# snapshot the DB into the private data repo so state persists across runs
if [ -d .git ]; then
  git add -A "$LEADS_DB" 2>/dev/null || true
  git commit -m "nightly $(date -Is)" >/dev/null 2>&1 || true
  git push >/dev/null 2>&1 || true
fi
log "done"
