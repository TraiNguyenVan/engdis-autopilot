#!/usr/bin/env bash
set -u
cd /opt/data/projects/engdis-autopilot

LOG_FILE="/opt/data/projects/engdis-autopilot/unattended.log"

export ED_CRED_FILE=${ED_CRED_FILE:-/home/yes/.hermes/.config/engdis/cred}
export ED_DRY_RUN=0
export ED_PASSES=2

echo "==================================================" >> "$LOG_FILE"
echo "Grind Pipeline Started: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"

COURSE="${1:-${ED_COURSE:-}}"
UNITS="${2:-${ED_UNITS:-all}}"

# Loop continuously until STOP file is present
while [ ! -f "STOP" ]; do
  echo "[$(date)] Running batch (Course: ${COURSE:-<default>}, Units: ${UNITS})..." >> "$LOG_FILE"
  if [ -n "$COURSE" ]; then
    ED_COURSE="$COURSE" ED_UNITS="$UNITS" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true
  else
    ED_UNITS="$UNITS" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true
  fi

  if [ -f "STOP" ]; then break; fi

  echo "[$(date)] Pass cycle completed. Resting 15s before next check..." >> "$LOG_FILE"
  sleep 15
done

echo "==================================================" >> "$LOG_FILE"
echo "Grind Pipeline Stopped: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
