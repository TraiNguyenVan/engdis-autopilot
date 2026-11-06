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

import edlib, login, poll
import config

HOME = "https://ed22.engdis.com/ptithcm#/home"
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = config.REPORT_DIR
PER_LESSON_TIMEOUT = int(os.environ.get("ED_LESSON_TIMEOUT", "450"))

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
    poll.wait_until(
        lambda: t.js("(() => document.querySelectorAll('.home__unitW').length > 0)()"),
        lambda v: bool(v), timeout=15.0, interval=0.3)
    for _ in range(6):
        d = t.js(HOME_JS)
        if isinstance(d, dict) and d.get("units"):
            return d
        time.sleep(1.5)
    return {}


def goto_lesson(t, unit_i, lesson_j):
    t.goto(HOME)
    poll.wait_until(
        lambda: t.js("(() => document.querySelectorAll('.home__unitW').length > 0)()"),
        lambda v: bool(v), timeout=15.0, interval=0.3)
    res = 'no units'
    for _ in range(5):
        res = t.js(GOTO_JS % (unit_i, lesson_j))
        if isinstance(res, str) and res.startswith('ok'):
            break
        time.sleep(1.5)
    poll.wait_until(
        lambda: t.js("(() => location.href.includes('learningArea') && document.querySelectorAll('ed-la-dropdownlist').length >= 2)()"),
        lambda v: bool(v), timeout=15.0, interval=0.3)
    return res


def run_lesson(lesson_name, max_iter=90):
    """Run auto.py once; bounded, never raises."""
    cmd = [sys.executable, "-u", "auto.py", str(max_iter)]
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


def parse_unit_specs(spec, total_units=10):
    """Parse unit specifications like '8', '8-9', '8..9', '0,2,4-6', 'all'.
    Returns a sorted list of unique 0-based unit indices within [0, total_units - 1].
    """
    if spec is None:
        return [0]
    spec = str(spec).strip().lower()
    if not spec:
        return [0]
    if spec == "all":
        return list(range(total_units))

    indices = set()
    parts = [p.strip() for p in spec.replace(";", ",").split(",") if p.strip()]
    for part in parts:
        if ".." in part:
            start_s, end_s = part.split("..", 1)
            start, end = int(start_s), int(end_s)
            indices.update(range(start, end + 1))
        elif "-" in part and not part.startswith("-"):
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            indices.update(range(start, end + 1))
        elif part.isdigit():
            indices.add(int(part))
        else:
            raise ValueError(f"Invalid unit spec: {part!r}")

    valid = sorted(i for i in indices if 0 <= i < total_units)
    if not valid:
        raise ValueError(f"No valid units parsed from spec: {spec!r} (total={total_units})")
    return valid


def cover_unit(t, unit_i, passes=2, dry=False, skips=None):
    skips = skips or []
    h = home_state(t)
    if not h.get("units") or unit_i >= len(h["units"]):
        print(f"no home data or invalid unit index {unit_i}")
        return None
    unit = h["units"][unit_i]
    print(f"\n==========================================")
    print(f"UNIT {unit_i}: {unit['name']} {pct(unit['progress'])} | {len(unit['lessons'])} lessons")
    print(f"==========================================")

    report = {"unit": unit["name"], "unit_index": unit_i, "lessons": {}, "passes": passes}
    blocked = set()
    for p in range(passes):
        if os.path.exists(os.path.join(HERE, "STOP")):
            print("STOP file present, halting passes")
            break
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
            if os.path.exists(os.path.join(HERE, "STOP")):
                print("STOP file present, halting lessons")
                break
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
    print(f"RESULT unit {unit_i} ({unit['name']}): {pct(unit['progress'])}")
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
    return report


def main():
    pos_args = []
    flags = []
    for a in sys.argv[1:]:
        if a.startswith("--"):
            flags.append(a)
        else:
            pos_args.append(a)

    raw_spec = pos_args[0] if pos_args else os.environ.get("ED_UNITS") or os.environ.get("ED_UNIT") or "1"
    passes = int(pos_args[1]) if len(pos_args) > 1 and pos_args[1].isdigit() else 2
    for f in flags:
        if f.startswith("--passes="):
            passes = int(f.split("=", 1)[1])
    dry = "--dry" in flags
    skips = [f.split("=", 1)[1] for f in flags if f.startswith("--skip=")]

    t = edlib.tab()
    if not login.ensure_login(t):
        print("LOGIN-FAIL")
        return 4
    h = home_state(t)
    if not h.get("units"):
        print("no home data", h)
        return 2

    target_units = parse_unit_specs(raw_spec, total_units=len(h["units"]))
    print(f"Target units: {target_units} (passes={passes}, dry={dry}, skips={skips})")

    all_reports = []
    for u_idx in target_units:
        if os.path.exists(os.path.join(HERE, "STOP")):
            print("STOP file present, stopping multi-unit walk")
            break
        rep = cover_unit(t, u_idx, passes=passes, dry=dry, skips=skips)
        if rep:
            all_reports.append(rep)

    if len(target_units) > 1:
        print("\n================ MULTI-UNIT SUMMARY ================")
        for r in all_reports:
            print(f"Unit {r['unit_index']} ({r['unit']}): {pct(r['unit_progress'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
