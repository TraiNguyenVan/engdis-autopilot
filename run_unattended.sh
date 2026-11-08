#!/usr/bin/env bash
set -u
cd /opt/data/projects/engdis-autopilot

LOG_FILE="/opt/data/projects/engdis-autopilot/unattended.log"

echo "==================================================" >> "$LOG_FILE"
echo "Unattended Pipeline Started: $(date)" >> "$LOG_FILE"
# Accepts ED_COURSE and ED_UNITS from environment or CLI arguments:
# ./run_unattended.sh ["Course Name"] ["unit-spec"]
COURSE="${1:-${ED_COURSE:-}}"
UNITS="${2:-${ED_UNITS:-all}}"

echo "Target: Course='${COURSE:-<default>}', Units='${UNITS}'" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"

export ED_CRED_FILE=${ED_CRED_FILE:-/home/yes/.hermes/.config/engdis/cred}
export ED_DRY_RUN=0
export ED_PASSES=2

echo "[$(date)] Running batch (Course: ${COURSE:-<default>}, Units: ${UNITS})..." >> "$LOG_FILE"
if [ -n "$COURSE" ]; then
  ED_COURSE="$COURSE" ED_UNITS="$UNITS" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true
else
  ED_UNITS="$UNITS" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true
fi

echo "==================================================" >> "$LOG_FILE"
echo "Unattended Pipeline Finished: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
