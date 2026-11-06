#!/usr/bin/env bash
# Run cover.py across one or more units.
# Supports:
#   ./cover_all.sh 8 9 2      (from to passes)
#   ./cover_all.sh 8-9 2      (unit_spec passes)
#   ./cover_all.sh all 1      (spec passes)
# Stops early if ./STOP exists.
cd "$(dirname "$0")" || exit 1

ARG1="${1:-0-9}"
ARG2="${2:-}"
ARG3="${3:-}"

if [ -n "$ARG2" ] && [[ "$ARG1" =~ ^[0-9]+$ ]] && [[ "$ARG2" =~ ^[0-9]+$ ]] && [ -n "$ARG3" -o "$ARG1" != "$ARG2" ]; then
  # Legacy syntax: FROM TO PASSES
  UNIT_SPEC="${ARG1}-${ARG2}"
  PASSES="${ARG3:-1}"
else
  UNIT_SPEC="${ARG1}"
  PASSES="${ARG2:-1}"
fi

echo "=== Running cover.py for units: ${UNIT_SPEC} (passes: ${PASSES}) ==="
exec python3 cover.py "${UNIT_SPEC}" "${PASSES}"
