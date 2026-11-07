"""Best-effort unit coverage.

Walks every lesson of a unit, runs auto.py on each one, records where it
failed, and moves on to the next lesson instead of stopping. Prints a
summary and writes cover_report.json.

Usage:  python3 cover.py [unit_index] [passes] [--dry]
        unit_index is 0-based (Unit 2 == 1)
"""
import json
from datetime import datetime, timezone
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
  let courseName = null;
  let courseId = null;
  const curCourse = localStorage.getItem('Course');
  if (curCourse) {
    try {
      const p = JSON.parse(curCourse);
      courseName = p.CourseName || p.Name;
      courseId = p.CourseId || p.NodeId;
    } catch(e) {}
  }
  return {
    course: courseName,
    courseId: courseId,
    units: (c.units||[]).map((u,i) => ({
      i: i, name: u.Name, progress: u.Progress,
      lessons: (u.Children||[]).map((l,j) => ({
        j: j, name: l.Name, id: l.NodeId, progress: l.Progress, done: !!l.IsDone
      }))
    }))
  };
})()"""

GET_COURSES_JS = """(() => {
  const raw = localStorage.getItem('Courses');
  if (!raw) return [];
  try { return JSON.parse(raw); } catch(e) { return []; }
})()"""

SELECT_COURSE_JS = """((targetCourseId) => {
  const curCourse = localStorage.getItem('Course');
  if (curCourse) {
    try {
      const parsed = JSON.parse(curCourse);
      if (Number(parsed.CourseId) === Number(targetCourseId)) {
        return { switched: false, current: parsed.CourseName, id: parsed.CourseId };
      }
    } catch(e) {}
  }
  const carousel = document.querySelector('.home__courseCarouselSec') || document.querySelector('.home__courseCarouselW');
  if (!carousel) return { err: 'no carousel' };
  let s = angular.element(carousel).scope();
  while (s && !s.bindSpecificCourse) s = s.$parent;
  if (!s || !s.bindSpecificCourse) return { err: 'no bindSpecificCourse' };
  s.bindSpecificCourse(targetCourseId);
  return { switched: true, targetId: targetCourseId };
})(%d)"""

def match_course(target: str, available_courses: list[dict]) -> dict | None:
    if not target or not available_courses:
        return None
    raw = str(target).strip()
    if not raw:
        return None

    # 1. Exact CourseId match
    for c in available_courses:
        cid = str(c.get("CourseId") or c.get("id") or "")
        if cid and cid == raw:
            return c

    # 2. Exact name match (case-insensitive)
    for c in available_courses:
        cname = str(c.get("courseName") or c.get("name") or "").strip()
        if cname.lower() == raw.lower():
            return c

    # 3. Normalized alphanumeric match
    def _norm(s):
        import re
        return re.sub(r"[^a-z0-9]", "", s.lower())

    norm_target = _norm(raw)
    for c in available_courses:
        cname = str(c.get("courseName") or c.get("name") or "")
        if _norm(cname) == norm_target:
            return c

    # 4. Common shorthands: "a3" -> "advanced3", "adv3" -> "advanced3"
    shorthands = {
        "a1": "advanced1", "adv1": "advanced1",
        "a2": "advanced2", "adv2": "advanced2",
        "a3": "advanced3", "adv3": "advanced3",
        "i1": "intermediate1", "int1": "intermediate1",
        "i2": "intermediate2", "int2": "intermediate2",
        "i3": "intermediate3", "int3": "intermediate3",
        "b3": "basic3"
    }
    expanded = shorthands.get(norm_target, norm_target)
    for c in available_courses:
        cname = str(c.get("courseName") or c.get("name") or "")
        if _norm(cname) == expanded:
            return c

    # 5. Substring match
    for c in available_courses:
        cname = str(c.get("courseName") or c.get("name") or "")
        if norm_target in _norm(cname):
            return c

    return None

def ensure_course(t, target_course: str) -> dict | None:
    if not target_course:
        return None
    units_exist = t.js("(() => document.querySelectorAll('.home__unitW').length > 0)()")
    if not units_exist:
        t.goto(HOME)
        poll.wait_until(
            lambda: t.js("(() => document.querySelectorAll('.home__unitW').length > 0 || !!document.querySelector('.home__courseCarouselSec'))()"),
            lambda v: bool(v), timeout=15.0, interval=0.3)
    # Fast-check if already on target course
    cur_raw = t.js("(() => localStorage.getItem('Course'))()")
    if cur_raw:
        try:
            cur = json.loads(cur_raw)
            cname = cur.get("CourseName") or cur.get("Name") or ""
            cid = cur.get("CourseId") or cur.get("NodeId") or 0
            if match_course(target_course, [{"CourseId": cid, "courseName": cname}]):
                return {"CourseId": cid, "courseName": cname}
        except Exception:
            pass
    courses = t.js(GET_COURSES_JS)
    if not courses or not isinstance(courses, list):
        print("warning: could not read available courses from localStorage")
        return None
    matched = match_course(target_course, courses)
    if not matched:
        avail = [c.get("courseName") for c in courses if c.get("courseName")]
        raise ValueError(f"Course '{target_course}' not found. Available courses: {avail}")

    cid = matched.get("CourseId") or matched.get("id") or 0
    cname = matched.get("courseName") or matched.get("name") or "unknown"
    res = t.js(SELECT_COURSE_JS % int(cid))
    if isinstance(res, dict) and res.get("switched"):
        print(f"Switched course to: {cname} (ID: {cid})")
        time.sleep(2.0)
        poll.wait_until(
            lambda: t.js("(() => document.querySelectorAll('.home__unitW').length > 0)()"),
            lambda v: bool(v), timeout=15.0, interval=0.3)
    else:
        print(f"Course active: {cname} (ID: {cid})")
    return matched

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
  u.IsLocked = false;
  l.IsLocked = false;
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


def goto_lesson(t, unit_i, lesson_j, target_course=None):
    if target_course:
        try:
            ensure_course(t, target_course)
        except Exception:
            pass
    else:
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
    loaded = poll.wait_until(
        lambda: t.js("(() => location.href.includes('learningArea') && document.querySelectorAll('ed-la-dropdownlist').length >= 2)()"),
        lambda v: bool(v), timeout=15.0, interval=0.3)
    if not loaded:
        return 'err nav timeout'
    return res


def run_lesson(lesson_name, max_iter=90, extra_env: dict | None = None):
    """Run auto.py once; bounded, never raises."""
    cmd = [sys.executable, "-u", "auto.py", str(max_iter)]
    started = time.time()
    log_dir = os.environ.get("ED_LOG_DIR") or os.path.join(HERE, "logs")
    os.makedirs(log_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in lesson_name).strip()
    lp = os.path.join(log_dir, safe + ".log")
    tail = []
    try:
        with open(lp, "a") as lf:
            def log(message):
                lf.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}\n")
                lf.flush()
            log(f"start lesson={lesson_name!r} max_iter={max_iter}")
            env = dict(os.environ, ED_LESSON_LOCK="1")
            if extra_env:
                env.update(extra_env)
            p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, env=env,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1)
            timed_out = threading.Event()
            def kill_timed_out():
                if p.poll() is None:
                    timed_out.set()
                    p.kill()
            killer = threading.Timer(PER_LESSON_TIMEOUT, kill_timed_out)
            killer.start()
            try:
                assert p.stdout is not None
                with p.stdout:
                    for line in p.stdout:
                        log("worker " + line.rstrip("\r\n"))
                        if line.strip():
                            tail.append(line.rstrip())
                            tail = tail[-6:]
                p.wait()
            finally:
                killer.cancel()
            rc = "timeout" if timed_out.is_set() else p.returncode
            log(f"exit rc={rc} duration={int(time.time() - started)}s")
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


def filter_lessons(lessons: list[dict], lesson_spec: str | None = None, test_only: bool = False, skips: list[str] | None = None) -> list[dict]:
    skips = [s.lower() for s in (skips or [])]
    filtered = []
    for l in lessons:
        name = l.get("name") or ""
        j = l.get("j", 0)
        p = _num(l.get("progress"))
        if any(k in name.lower() for k in skips):
            continue
        if test_only and (p < 0.60 or p >= 0.999):
            continue
        if lesson_spec is not None:
            raw = str(lesson_spec).strip()
            if raw.isdigit() and int(raw) != j:
                continue
            elif not raw.isdigit() and raw.lower() not in name.lower():
                continue
        filtered.append(l)
    return filtered


def cover_unit(t, unit_i, passes=2, dry=False, skips=None, target_course=None,
               lesson_spec=None, test_only=False, target_step=None):
    skips = skips or []
    if target_course:
        try:
            ensure_course(t, target_course)
        except Exception as e:
            print(f"warning: ensure_course failed: {e}")
    h = home_state(t)
    if not h.get("units") or unit_i >= len(h["units"]):
        print(f"no home data or invalid unit index {unit_i}")
        return None
    unit = h["units"][unit_i]
    c_prefix = f"[{h.get('course')}] " if h.get("course") else ""
    print(f"\n==========================================")
    print(f"{c_prefix}UNIT {unit_i}: {unit['name']} {pct(unit['progress'])} | {len(unit['lessons'])} lessons")
    print(f"==========================================")

    report = {
        "course": h.get("course"),
        "course_id": h.get("courseId"),
        "unit": unit["name"],
        "unit_index": unit_i,
        "lessons": {},
        "passes": passes
    }
    blocked = set()
    for p in range(passes):
        if os.path.exists(os.path.join(HERE, "STOP")):
            print("STOP file present, halting passes")
            break
        if target_course:
            try:
                ensure_course(t, target_course)
            except Exception as e:
                print(f"warning: ensure_course pass {p} failed: {e}")
        h = home_state(t)
        unit = h["units"][unit_i]
        unblocked = [l for l in unit["lessons"] if _num(l["progress"]) < 0.999 and l["name"] not in blocked]
        todo = filter_lessons(unblocked, lesson_spec=lesson_spec, test_only=test_only, skips=skips)
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
            nav = goto_lesson(t, unit_i, l["j"], target_course=target_course)
            if not str(nav).startswith("ok"):
                print("   nav failed:", nav)
                report["lessons"][l["name"]] = {"nav": str(nav)}
                continue
            extra_env = {}
            if target_step:
                extra_env["ED_TARGET_STEP"] = target_step
            elif test_only:
                extra_env["ED_TARGET_STEP"] = "Test"
            rc, tail, dur = run_lesson(l["name"], extra_env=extra_env if extra_env else None)
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

    if target_course:
        try:
            ensure_course(t, target_course)
        except Exception:
            pass
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
    lesson_spec = next((f.split("=", 1)[1] for f in flags if f.startswith("--lesson=")), None)
    target_step = next((f.split("=", 1)[1] for f in flags if f.startswith("--step=")), None)
    test_only = "--test-only" in flags

    target_course = None
    for f in flags:
        if f.startswith("--course="):
            target_course = f.split("=", 1)[1]
    if not target_course:
        target_course = os.environ.get("ED_COURSE") or config.ED_COURSE

    t = edlib.tab()
    if not login.ensure_login(t):
        print("LOGIN-FAIL")
        return 4

    if target_course:
        try:
            ensure_course(t, target_course)
        except Exception as e:
            print("COURSE-ERROR:", e)
            return 8

    h = home_state(t)
    if not h.get("units"):
        print("no home data", h)
        return 2

    c_info = f"[{h.get('course')}] " if h.get("course") else ""
    target_units = parse_unit_specs(raw_spec, total_units=len(h["units"]))
    print(f"{c_info}Target units: {target_units} (passes={passes}, dry={dry}, skips={skips}, lesson={lesson_spec}, test_only={test_only}, step={target_step})")

    all_reports = []
    for u_idx in target_units:
        if os.path.exists(os.path.join(HERE, "STOP")):
            print("STOP file present, stopping multi-unit walk")
            break
        rep = cover_unit(t, u_idx, passes=passes, dry=dry, skips=skips, target_course=target_course,
                         lesson_spec=lesson_spec, test_only=test_only, target_step=target_step)
        if rep:
            all_reports.append(rep)

    if len(target_units) > 1:
        print("\n================ MULTI-UNIT SUMMARY ================")
        for r in all_reports:
            print(f"Unit {r['unit_index']} ({r['unit']}): {pct(r['unit_progress'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
