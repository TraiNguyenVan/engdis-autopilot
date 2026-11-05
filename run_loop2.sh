#!/bin/bash
cd /opt/data/cache/scratch/ed22u1 || exit 1

CHROME=/opt/hermes/tools/chromium-1208/chrome-linux64/chrome
PROFILE=/opt/data/cache/scratch/chrome-ed22c/profile

ensure_chrome() {
  if curl -s --max-time 3 http://127.0.0.1:9225/json/version >/dev/null 2>&1; then
    return 0
  fi
  echo "=== chrome down, restarting $(date -u +%H:%M:%S)" >> auto_l4.log
  python3 killchrome.py >> auto_l4.log 2>&1
  rm -f "$PROFILE"/Singleton* "$PROFILE"/DevToolsActivePort
  nohup "$CHROME" --headless=new --remote-debugging-port=9225 \
    --user-data-dir="$PROFILE" --no-sandbox --disable-gpu \
    --disable-dev-shm-usage --renderer-process-limit=2 --window-size=1400,1000 \
    --autoplay-policy=no-user-gesture-required \
    --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
    about:blank >> chrome.log 2>&1 &
  for i in $(seq 1 20); do
    sleep 2
    if curl -s --max-time 3 http://127.0.0.1:9225/json/version >/dev/null 2>&1; then
      python3 - <<'PY' >> auto_l4.log 2>&1
import edlib
t = edlib.tab()
t.goto('https://ed22.engdis.com/Runtime/learningArea.html?v=5', wait=15)
print('=== chrome resumed:', t.js("(document.querySelectorAll('ed-la-dropdownlist')[1]?.innerText||'').split(String.fromCharCode(10))[0]"))
PY
      return 0
    fi
  done
  echo "=== chrome restart FAILED" >> auto_l4.log
  return 1
}

for i in $(seq 1 15); do
  while pgrep -f "python3 auto.py" >/dev/null 2>&1; do sleep 5; done
  [ -f STOP ] && { echo "=== STOP file, exit" >> auto_l4.log; break; }
  ensure_chrome
  echo "=== supervisor run $i $(date -u +%H:%M:%S)" >> auto_l4.log
  python3 auto.py 90 >> auto_l4.log 2>&1
  rc=$?
  echo "=== run $i exit $rc $(date -u +%H:%M:%S)" >> auto_l4.log
  if [ "$rc" = "3" ]; then
    echo "=== SPEAK-BLOCKED: stopping supervisor, needs manual speaking step" >> auto_l4.log
    break
  fi
  sleep 8
done
echo "=== supervisor done" >> auto_l4.log
