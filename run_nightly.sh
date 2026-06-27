#!/usr/bin/env bash
# Nightly pipeline — runs on the VPS (host cron, not inside the n8n container,
# because this needs Python + the Claude Code CLI). See infra/INFRA_SETUP.md.
# Every step logs start/end + exit code to data/logs/ via obs (step helper),
# on top of the per-claude-call logging inside the scripts.
set -uo pipefail
cd "$(dirname "$0")"

export LEADS_DB="${LEADS_DB:-data/leads.db}"
export PYTHONUNBUFFERED=1
AREA="${SCAN_AREA:-svendborg}"
PREP_LIMIT="${PREP_LIMIT:-12}"          # cap claude -p work to protect the weekly cap

ts(){ date -Is; }
step(){
  local n="$1"; shift
  echo "[nightly $(ts)] $n"
  python3 -c "import obs;obs.event('step_start',name='$n')" 2>/dev/null || true
  local rc=0; "$@" || rc=$?
  python3 -c "import obs;obs.event('step_end',name='$n',rc=$rc,ok=$([ $rc -eq 0 ] && echo True || echo False))" 2>/dev/null || true
  return 0
}

python3 -c "import obs;obs.event('loop_start',name='run_nightly')" 2>/dev/null || true

step pull_guidance   python3 pull_guidance.py
step learn_style     python3 learn_style.py
step inbox_poll      python3 inbox_poll.py

# Re-query Overpass only once a week (Sunday); other nights reuse the cached lead
# pool, so we don't hit the public Overpass servers nightly (no more 429s).
if [ "$(date +%u)" = "7" ]; then DISC=""; else DISC="--skip-discover"; fi
step run_scan        python3 run_scan.py --area "$AREA" $DISC
step prep            python3 prep.py --limit "$PREP_LIMIT"
step followups       python3 followups.py
step harvest_emails  python3 harvest_emails.py --limit "${HARVEST_LIMIT:-40}"
step check_demos     python3 check_demos.py
step render_usage    python3 render_usage.py
step badges          python3 badges.py --no-push
step notion_sync     python3 notion_sync.py

# auto-pick the top ugly/borderline leads and build their demos (opt-in: DEMO_LIMIT>0)
if [ "${DEMO_LIMIT:-0}" -gt 0 ]; then
  step select_demos  python3 select_demos.py --limit "$DEMO_LIMIT"
  step prep_draft    python3 prep.py --stage draft
  step notion_sync2  python3 notion_sync.py
fi

step fix_agent       python3 fix_agent.py --limit "${FIX_LIMIT:-2}"
step iterate_demo    python3 iterate_demo.py --limit "${ITERATE_LIMIT:-2}"
step tickets_sync    python3 tickets_sync.py
step send_outbox     python3 send_outbox.py

# local backup of the DB only — do NOT push from the VPS (it diverges from your
# code pushes). The live DB persists on the VPS disk regardless.
cp -f "$LEADS_DB" "${LEADS_DB}.bak" 2>/dev/null || true
python3 -c "import obs;obs.event('loop_end',name='run_nightly')" 2>/dev/null || true
echo "[nightly $(ts)] done"
