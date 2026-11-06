"""Best-effort unit coverage.

Walks every lesson of a unit, runs auto.py on each one, records where it
failed, and moves on to the next lesson instead of stopping. Prints a
summary and writes cover_report.json.

Usage:  python3 cover.py [unit_index] [passes] [--dry]
        unit_index is 0-based (Unit 2 == 1)
"""
import json
import os
import subprocess
import threading
import sys
import time

import edlib, login
import config

HOME = "https://ed22.engdis.com/ptithcm#/home"
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = config.REPORT_DIR
PER_LESSON_TIMEOUT = int(os.environ.get("ED_LESSON_TIMEOUT", "1000"))

HOME_JS = """(() => {
  const w = document.querySelectorAll('.home__unitW');
  if (!w.length) return {err:'no units on page'};
  let s = angular.element(w[0]).scope();
  while (s && !s.unitsCtrl) s = s.$parent;
  if (!s) return {err:'no unitsCtrl'};
  const c = s.unitsCtrl;
  return {units: (c.units||[]).map((u,i) => ({
    i: i, name: u.Name, progress: u.Progress,
    lessons: (u.Children||[]).map((l,j) => ({
      j: j, name: l.Name, id: l.NodeId, progress: l.Progress, done: !!l.IsDone
    }))
  }))};
})()"""

GOTO_JS = """(() => {
  const w = document.querySelectorAll('.home__unitW');
  if (!w.length) return 'no units';
  let s = angular.element(w[0]).scope();
  while (s && !s.unitsCtrl) s = s.$parent;
  if (!s) return 'no unitsCtrl';
  const c = s.unitsCtrl;
  const u = c.units[%d];
  if (!u) return 'no unit';
  const l = u.Children[%d];
  if (!l) return 'no lesson';
  try { c.goToLesson(l, false, 'Unit'); return 'ok ' + l.Name; }
  catch (e) { return 'err ' + e; }
})()"""


def home_state(t):
    t.goto(HOME)
    time.sleep(6)
    for _ in range(6):
        d = t.js(HOME_JS)
        if isinstance(d, dict) and d.get("units"):
            return d
        time.sleep(3)
    return {}


def goto_lesson(t, unit_i, lesson_j):
    t.goto(HOME)
    time.sleep(5)
    r = t.js(GOTO_JS % (unit_i, lesson_j))
    time.sleep(10)
    return r


def run_lesson(lesson_name, max_iter=90):
    """Run auto.py once; bounded, never raises."""
    cmd = [sys.executable, "auto.py", str(max_iter)]
    started = time.time()
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in lesson_name).strip()
    lp = os.path.join(HERE, "logs", safe + ".log")
    tail = []
    try:
        with open(lp, "a") as lf:
            lf.write("\n=== %s %s\n" % (time.strftime("%H:%M:%S"), lesson_name))
            lf.flush()
            env = dict(os.environ, ED_LESSON_LOCK="1")
            p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, env=env,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1)
            killer = threading.Timer(PER_LESSON_TIMEOUT, p.kill)
            killer.start()
            for line in p.stdout:
                lf.write(line)
                lf.flush()
                if line.strip():
                    tail.append(line.rstrip())
                    tail = tail[-6:]
            p.wait()
            killer.cancel()
            rc = p.returncode
    except subprocess.TimeoutExpired:
        p.kill()
        rc, tail = "timeout", ["timeout"]
    dur = int(time.time() - started)
    return rc, tail[-4:], dur


def _num(x):
    while isinstance(x, (list, tuple)):
        x = x[0] if x else 0
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def pct(x):
    return f"{round(_num(x) * 100)}%"


def main():
    unit_i = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
    args = [a for a in sys.argv[1:] if not a.isdigit()]
    passes = 2
    dry = "--dry" in args
    skips = [a.split("=", 1)[1] for a in args if a.startswith("--skip=")]
    for a in args:
        if a.startswith("--passes="):
            passes = int(a.split("=")[1])

    t = edlib.tab()
    if not login.ensure_login(t):
        print("LOGIN-FAIL")
        return 4
    h = home_state(t)
    if not h.get("units"):
        print("no home data", h)
        return 2
    unit = h["units"][unit_i]
    print(f"UNIT {unit_i}: {unit['name']} {pct(unit['progress'])} | {len(unit['lessons'])} lessons")

    report = {"unit": unit["name"], "lessons": {}, "passes": passes}
    blocked = set()
    for p in range(passes):
        h = home_state(t)
        unit = h["units"][unit_i]
        todo = [l for l in unit["lessons"] if _num(l["progress"]) < 0.999
                and not any(k.lower() in (l["name"] or "").lower() for k in skips)
                and l["name"] not in blocked]
        if not todo:
            print("all lessons complete")
            break
        print(f"-- pass {p + 1}: {len(todo)} lesson(s) to do")
        for l in todo:
            print(f"[{l['j']}] {l['name']} {pct(l['progress'])}", flush=True)
            if dry:
                continue
            nav = goto_lesson(t, unit_i, l["j"])
            if not str(nav).startswith("ok"):
                print("   nav failed:", nav)
                report["lessons"][l["name"]] = {"nav": str(nav)}
                continue
            rc, tail, dur = run_lesson(l["name"])
            print(f"   rc={rc} {dur}s | " + " / ".join(tail[-2:]), flush=True)
            if rc == 5:
                print("   lesson finished (lesson-lock exit)", flush=True)
            if rc == 3:
                blocked.add(l["name"])
                print("   SPEAK-BLOCKED -> skip this lesson in later passes", flush=True)
            report["lessons"][l["name"]] = {"rc": rc, "dur": dur, "tail": tail,
                                            "start_progress": l["progress"],
                                            "blocked": l["name"] in blocked}
        if dry:
            break

    h = home_state(t)
    unit = h["units"][unit_i]
    print(f"RESULT unit {pct(unit['progress'])}")
    for l in unit["lessons"]:
        print(f"  {l['name']}: {pct(l['progress'])}")
        report["lessons"].setdefault(l["name"], {})["final"] = l["progress"]
    report["unit_progress"] = unit["progress"]
    rname = "cover_report_u%d.json" % unit_i
    out_dir = os.path.abspath(REPORT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, rname), "w") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(out_dir, "cover_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("report:", rname)
    return 0


if __name__ == "__main__":
    sys.exit(main())
