# Contributing to Engdis Autopilot

Welcome! This guide outlines our standard operating procedures, architectural boundaries, and quality gates. It is optimized for both human engineers and AI coding agents (Claude Code, Cursor, Codex, Antigravity, OpenClaw, Hermes) to start working immediately without trial-and-error.

---

## 1. Quickstart for AI Coding Agents

If you are an AI coding agent tasked with fixing an exercise, adding a feature, or resolving a stall:

1. **Do not run tests with live network or LMS accounts**: The test suite runs 100% offline using mock DOM trees and fixture dictionaries.
2. **Never execute the live runner on host**: Live runs require headless Chromium with fake media devices inside Docker (`docker compose run` or `docker exec engdis_inspect`).
3. **Reproduce via offline fixture first**: Never edit `solver.py` or `auto.py` before adding a reproducer test in `tests/test_stuck_cases.py` using dumped fixture data.
4. **Mandatory gate**: All tests in `tests/` must pass (`python3 -m unittest discover -s tests`).

---

## 2. Standard Bugfix & Remediation Workflow

When an exercise stalls during an automated run or a new widget type is encountered:

### Step 1: Inspect the Auto-Dumped Fixture
When a task fails to advance for 4 unchanged ticks, `auto.py` writes a snapshot to `logs/fixtures/stuck_<lesson>_<task>_<timestamp>.json`.

Inspect it offline:
```bash
python3 -c 'import json, glob; data = json.load(open(sorted(glob.glob("logs/fixtures/stuck_*.json"))[-1])); print("BODY:", data.get("body", "")[:300]); print("COMP STATE:", data.get("compState"))'
```

Key fields in fixtures:
- `body`: Visible text of the prompt and options.
- `html`: Outer and inner DOM markup of the exercise container.
- `compState`: Angular component properties (`doneProgress`, `isSubmitted`, `currentState`).
- `interactives`: List of clickable DOM nodes with coordinates, classes, and IDs.

### Step 2: Write an Offline Unit Test
Recreate the DOM environment in `tests/test_stuck_cases.py` using mock tab objects (`edlib.MockTab` or custom mocks). Ensure the test reproduces the failure (e.g. classifier returning `other` or setter failing to flip `doneProgress`).

### Step 3: Implement the Minimal Fix
- For selector / classification bugs: update `auto.py` (`classify_task`, `is_test`, or handler dispatch).
- For interaction / typing bugs: update `solver.py`.
- For Angular state sync: synthesize user events (e.g. `KeyboardEvent('keyup', {bubbles: true})` or CDP `Input.insertText`).

### Step 4: Run the Offline Test Suite Gate
```bash
python3 -m unittest discover -s tests
```
Ensure all 58+ tests pass with zero network requests.

---

## 3. Security & Cleanliness Gates

We enforce strict security and repository cleanliness gates:

1. **Zero Credential Leaks**:
   - Never commit `.env`, credentials files (`~/.config/engdis/cred`), tokens, passwords, cookies, or live session dumps.
   - Sanitize all test fixtures before committing: scrub any student IDs, institution IDs, student names, or authorization Bearer tokens.
2. **Single-Issue PR Scope**:
   - Keep Pull Requests focused: one widget fix, one feature, or one documentation update per PR.
   - Include the reproducer unit test in every PR that fixes an exercise.
3. **No Drive-by Refactors**:
   - Preserve existing function signatures in `solver.py`, `driver.py`, and `auto.py`.
   - Respect repository coding conventions: standard library and existing dependencies only.

---

## 4. Operational Testing (Live Browser in Docker)

To verify a fix against the real LMS platform:

```bash
# Targeted single-lesson verification inside Docker
ED_COURSE="<COURSE>" docker compose run --rm engdis python3 cover.py <UNIT_IDX> 1 --course="<COURSE>" --lesson="<LESSON_NAME>"

# Dry-run audit (read-only verification of course tree)
ED_COURSE="<COURSE>" docker compose run --rm -e ED_DRY_RUN=1 engdis
```

Do not run live batch supervisor loops in interactive agent turns. Use non-blocking background jobs or `--unattended` mode.
