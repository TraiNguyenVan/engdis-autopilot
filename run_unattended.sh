#!/usr/bin/env bash
set -u
cd /opt/data/projects/engdis-autopilot

LOG_FILE="/opt/data/projects/engdis-autopilot/unattended.log"

echo "==================================================" >> "$LOG_FILE"
echo "Unattended Pipeline Started: $(date)" >> "$LOG_FILE"
echo "Target: Advanced 2 (Units 8-9) -> Advanced 3 (Units 0-9)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"

export ED_CRED_FILE=${ED_CRED_FILE:-/home/yes/.hermes/.config/engdis/cred}
export ED_DRY_RUN=0
export ED_PASSES=2

# Step 1: Finish Advanced 2 Units 8-9
echo "[$(date)] Phase 1: Advanced 2 (Units 8-9)..." >> "$LOG_FILE"
ED_COURSE="Advanced 2" ED_UNITS="8-9" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true

# Check for STOP file
if [ -f "STOP" ]; then
  echo "[$(date)] STOP file detected after Phase 1. Halting pipeline." >> "$LOG_FILE"
  exit 0
fi

# Step 2: Advanced 3 Units 0-9
echo "[$(date)] Phase 2: Advanced 3 (All Units)..." >> "$LOG_FILE"
ED_COURSE="Advanced 3" ED_UNITS="all" docker compose run --rm --name engdis_runner engdis >> "$LOG_FILE" 2>&1 || true

echo "==================================================" >> "$LOG_FILE"
echo "Unattended Pipeline Finished: $(date)" >> "$LOG_FILE"
echo "==================================================" >> "$LOG_FILE"
