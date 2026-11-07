#!/bin/bash
cd /opt/data/cache/scratch/ed22u1 || exit 1
for i in $(seq 1 20); do
  # wait for any existing auto.py to finish
  while pgrep -f "python3 auto.py" >/dev/null 2>&1; do sleep 5; done
  [ -f STOP ] && { echo "=== STOP file, exit" >> auto_l4.log; break; }
  echo "=== supervisor run $i $(date -u +%H:%M:%S)" >> auto_l4.log
  python3 auto.py 90 >> auto_l4.log 2>&1
  echo "=== run $i exit $? $(date -u +%H:%M:%S)" >> auto_l4.log
  sleep 8
done
echo "=== supervisor done" >> auto_l4.log
