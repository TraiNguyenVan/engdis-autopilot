#!/bin/sh
# Walk every unit from $1 to $2 (0-based), one cover.py run each.
# Stops early if ./STOP exists. Logs: cover_u<idx>.log
cd "$(dirname "$0")" || exit 1
FROM=${1:-0}
TO=${2:-9}
PASSES=${3:-1}
for i in $(seq "$FROM" "$TO"); do
  [ -f STOP ] && { echo "STOP file present, halting at unit $i"; break; }
  echo "=== unit $i $(date +%H:%M:%S)"
  python3 cover.py "$i" "$PASSES" >> "cover_u$i.log" 2>&1
  echo "=== unit $i rc=$? $(date +%H:%M:%S)"
  tail -8 "cover_u$i.log"
done
