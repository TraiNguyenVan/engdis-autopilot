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

# Loop continuously until STOP file is present
while [ ! -f "STOP" ]; do
  echo "[$(date)] Running Advanced 2 (Units 8-9)..." >> "$LOG_FILE"
  ED_COURSE="Advanced 2" ED_UNITS="8-9" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true

  if [ -f "STOP" ]; then break; fi

  echo "[$(date)] Running Advanced 3 (Units 0-9)..." >> "$LOG_FILE"
  ED_COURSE="Advanced 3" ED_UNITS="all" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true

  echo "[$(date)] Pass cycle completed. Resting 15s before next check..." >> "$LOG_FILE"
  sleep 15
done

echo "==================================================" >> "$LOG_FILE"
echo "Grind Pipeline Stopped: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
