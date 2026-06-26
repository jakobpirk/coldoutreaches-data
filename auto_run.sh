#!/usr/bin/env bash
# Usage-window-gated launcher for the design/nightly pipeline.
#
# Run from cron every 10 minutes. It starts ONE full pipeline run at the
# beginning of each Claude usage window (so the Max budget gets spent building
# designs), and will NOT start another until the next window opens.
#
# Determining when the next window opens:
#   * If the run exhausts the budget, Claude Code prints 'limit reached|<epoch>'
#     on the way out — we parse that exact reset time.
#   * Otherwise we fall back to start + 5h (the Max rolling-window length).
#
# Install (crontab -e):
#   */10 * * * * /opt/coldoutreaches/auto_run.sh >> /opt/coldoutreaches/data/auto_run.log 2>&1
# and REMOVE the old fixed "30 2 * * * ... run_nightly.sh" line.

cd "$(dirname "$0")" || exit 1
set -a; source infra/.env 2>/dev/null; set +a

STATE="data/usage_state"
LOG="data/nightly.log"
WINDOW_SECONDS="${USAGE_WINDOW_SECONDS:-18000}"   # 5h Max rolling window
ts(){ date -Is; }

# Single-run lock: if a pipeline run is already going, skip this tick.
exec 9>/tmp/coldoutreaches_run.lock
if ! flock -n 9; then
  echo "[$(ts)] run already in progress — skip"
  exit 0
fi

now=$(date +%s)
next_eligible=$(cat "$STATE" 2>/dev/null || echo 0)
[ -z "$next_eligible" ] && next_eligible=0

if [ "$now" -lt "$next_eligible" ]; then
  echo "[$(ts)] window not reset yet (eligible in $(( (next_eligible-now)/60 )) min) — skip"
  exit 0
fi

echo "[$(ts)] usage window open — starting pipeline run"
start=$now
RUNLOG=$(mktemp)
bash run_nightly.sh >"$RUNLOG" 2>&1
cat "$RUNLOG" >> "$LOG"

# Precise reset epoch if Claude reported a limit; else fall back to +5h.
reset=$(grep -oiE 'limit reached\|[0-9]{10}' "$RUNLOG" | grep -oE '[0-9]{10}' | tail -1)
rm -f "$RUNLOG"
if [ -n "$reset" ] && [ "$reset" -gt "$now" ]; then
  echo "$reset" > "$STATE"
  echo "[$(ts)] run done. Next window (from Claude's reported reset) at $(date -d @"$reset" -Is)"
else
  fallback=$(( start + WINDOW_SECONDS ))
  echo "$fallback" > "$STATE"
  echo "[$(ts)] run done. Next window (fallback +$(( WINDOW_SECONDS/3600 ))h) at $(date -d @"$fallback" -Is)"
fi
