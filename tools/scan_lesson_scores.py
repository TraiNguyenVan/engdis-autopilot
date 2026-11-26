"""Read-only lesson-test score scanner for English Discoveries.

Ported from the upstream handoff package (`scan_all_lesson_test_scores.py`),
with the Windows-specific bits removed:

- no hardcoded ``d:\\lab\\...`` import/output paths;
- courses and the output directory come from ``--course`` / ``--out``;
- nothing is submitted, clicked into a test, or re-attempted: the scanner only
  walks lessons and reads the step dropdown text.

Usage (inside the Docker harness, where CDP is reachable)::

    docker compose run --rm engdis python3 tools/scan_lesson_scores.py \
        --course "Advanced 2" --course "Advanced 3" --out /data/reports

Output: one JSON file per course, ``<slug>_test_scores.json``, holding a list of
``{course, unitIdx, unitName, lessonIdx, lessonName, testScore}`` records.
``testScore`` is ``null`` when the dropdown never showed a percentage - keep it
as unknown rather than treating it as 0.
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cover  # noqa: E402
import edlib  # noqa: E402

STEPS_JS = """(() => {
    const dd = document.querySelectorAll('ed-la-dropdownlist');
    return dd[1] ? dd[1].innerText : '';
})()"""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "course"


def read_test_score(steps_text: str):
    """Return the recorded test percentage from the step dropdown text.

    The dropdown lists one step per line (``1. Explore``, ``3. Test 77%``), so a
    ``N%`` on the Test line - or on the next two lines, where the LMS sometimes
    wraps the score - is that lesson's test score.
    """
    lines = [ln.strip() for ln in (steps_text or "").split("\n") if ln.strip()]
    for idx, line in enumerate(lines):
        if "test" not in line.lower():
            continue
        for candidate in lines[idx:idx + 3]:
            match = re.search(r"(\d+)%", candidate)
            if match:
                return int(match.group(1))
    return None


def scan_course(tab, course: str):
    print("Scanning course: %s ..." % course, flush=True)
    cover.ensure_course(tab, course)
    time.sleep(2)

    home = cover.home_state(tab)
    units = home.get("units", [])
    print("Found %d units in %s" % (len(units), course), flush=True)

    results = []
    for unit in units:
        for lesson in unit.get("lessons", []):
            cover.goto_lesson(tab, unit["i"], lesson["j"], target_course=course)
            time.sleep(1.5)
            score = read_test_score(tab.js(STEPS_JS))
            print("  U%d (%s) - L%d (%s): Test = %s%%"
                  % (unit["i"] + 1, unit["name"], lesson["j"] + 1,
                     lesson["name"], score), flush=True)
            results.append({
                "course": course,
                "unitIdx": unit["i"],
                "unitName": unit["name"],
                "lessonIdx": lesson["j"],
                "lessonName": lesson["name"],
                "testScore": score,
            })
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan lesson test scores (read-only)")
    parser.add_argument("--course", action="append", required=True,
                        help="course name or CourseId; repeatable")
    parser.add_argument("--out", default=os.environ.get("ED_REPORT_DIR", "/data/reports"),
                        help="directory for the <course>_test_scores.json files")
    args = parser.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    tab = edlib.tab()

    for course in args.course:
        results = scan_course(tab, course)
        path = os.path.join(args.out, "%s_test_scores.json" % slugify(course))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)
        sub100 = [r for r in results
                  if r["testScore"] is not None and r["testScore"] < 100]
        unknown = [r for r in results if r["testScore"] is None]
        print("%s: %d lessons, %d below 100%%, %d unknown -> %s"
              % (course, len(results), len(sub100), len(unknown), path), flush=True)


if __name__ == "__main__":
    main()
