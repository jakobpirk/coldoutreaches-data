#!/usr/bin/env bash
# Inbox reply loop — runs every ~30 min from cron, separate from the heavy
# design pipeline (auto_run.sh). Drafts replies to new inbox mail (never sends),
# mails the ones you approved (Send svar), runs the demo-iteration worker, and
# refreshes the process badges. Every step is logged to data/logs/ via obs.
#
# Install (crontab -e):
#   */30 * * * * /opt/coldoutreaches/run_inbox.sh >> /opt/coldoutreaches/data/inbox.log 2>&1
set -uo pipefail
cd "$(dirname "$0")" || exit 1
set -a; source infra/.env 2>/dev/null; set +a
export LEADS_DB="${LEADS_DB:-data/leads.db}"
export PYTHONUNBUFFERED=1
ts(){ date -Is; }

# run one step: log start/end + exit code to obs, never abort the loop
step(){
  local n="$1"; shift
  echo "[$(ts)] $n"
  python3 -c "import obs;obs.event('step_start',name='$n')" 2>/dev/null || true
  local rc=0; "$@" || rc=$?
  python3 -c "import obs;obs.event('step_end',name='$n',rc=$rc,ok=$([ $rc -eq 0 ] && echo True || echo False))" 2>/dev/null || true
  return 0
}

# don't overlap with a previous tick still running
exec 8>/tmp/coldoutreaches_inbox.lock
if ! flock -n 8; then echo "[$(ts)] inbox loop already running — skip"; exit 0; fi

python3 -c "import obs;obs.event('loop_start',name='run_inbox')" 2>/dev/null || true
step pull_guidance  python3 pull_guidance.py
step reply_agent    python3 reply_agent.py
step send_replies   python3 send_replies.py
step iterate_demo   python3 iterate_demo.py --limit "${ITERATE_LIMIT:-1}"
step badges         python3 badges.py
python3 -c "import obs;obs.event('loop_end',name='run_inbox')" 2>/dev/null || true
echo "[$(ts)] done"
