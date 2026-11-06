#!/usr/bin/env bash
set -euo pipefail

ED_UNIT="${ED_UNIT:-0}"
ED_PASSES="${ED_PASSES:-1}"
ED_DRY_RUN="${ED_DRY_RUN:-1}"
ED_CDP_PORT="${ED_CDP_PORT:-9225}"

echo "=== Engdis Autopilot Container Starting ==="
echo "Unit: ${ED_UNIT} | Passes: ${ED_PASSES} | Dry Run: ${ED_DRY_RUN}"

mkdir -p /data/profile /data/cache /data/reports
export ED_SCRATCH=/data/cache
export ED_REPORT_DIR=/data/reports
export ED_CDP_PORT="${ED_CDP_PORT}"

# Launch Chromium in background via bootstrap
python3 /app/bootstrap_browser.py --port "${ED_CDP_PORT}" --profile /data/profile &
CHROME_BOOTSTRAP_PID=$!

cleanup() {
  echo "=== Shutting down Chromium (PID: ${CHROME_BOOTSTRAP_PID}) ==="
  kill -TERM "${CHROME_BOOTSTRAP_PID}" 2>/dev/null || true
  wait "${CHROME_BOOTSTRAP_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for CDP endpoint
READY=0
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:${ED_CDP_PORT}/json/version" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "${READY}" -ne 1 ]; then
  echo "Error: Chromium CDP failed to become ready on port ${ED_CDP_PORT}" >&2
  exit 1
fi

echo "=== Running cover.py ==="
EXTRA_ARGS=""
if [ "${ED_DRY_RUN}" = "1" ] || [ "${ED_DRY_RUN}" = "true" ]; then
  EXTRA_ARGS="--dry"
fi

python3 /app/cover.py "${ED_UNIT}" "${ED_PASSES}" ${EXTRA_ARGS}
RC=$?

echo "=== cover.py finished with exit code ${RC} ==="
exit "${RC}"
