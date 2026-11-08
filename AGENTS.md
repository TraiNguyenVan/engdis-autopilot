# AGENTS.md

Instructions, conventions, and operational patterns for AI coding agents (Claude Code, Cursor, Codex, Antigravity, OpenClaw, Hermes) working in this repository.

---

## 1. Core Operating Principles

1. **Zero Chat-Token Burn**: Never run supervisor loops interactively in conversation turns. Always launch batches as non-blocking background tasks and report only final completion status or actionable blockers.
2. **Single-Owner Browser Rule**: Never open ad-hoc WebSocket connections to CDP port 9225 while a background `cover.py` or `auto.py` process is active. Concurrent DevTools connections cause CDP packet drops, tab race conditions, and runner timeouts.
3. **Reproduce via Offline Fixtures First**: When an exercise stalls, inspect auto-dumped state in `logs/fixtures/stuck_*.json`. Write a mock unit test in `tests/` recreating the task DOM before editing `solver.py` or `auto.py`.
4. **Mandatory Test Suite Gate**: Run `python3 -m unittest discover -s tests` before committing any changes. All 58+ tests must pass.

---

## 2. Platform Architecture & State Model

The English Discoveries courseware (ED22 / PTIT LMS) is an Angular SPA backed by SCORM-like completion beacons:

- **Hierarchy**: Course -> Units (0-indexed or 1-indexed depending on view) -> Lessons -> Steps (`Explore`, `Practice`, `Test`).
- **Explore Steps**: Audio/video listening and reading. Completion requires media beacons to fire. Harness accelerates media to 16x (`playbackRate = 16.0`) to trigger beacons in 2–4s.
- **Practice Steps**: Interactive tasks (MCQ, fill-in-the-blank, open-ended writing, sequence drag-and-drop, interactive speaking).
- **Test Steps**: Scored assessments. Once submitted, displays test score screen (`Your test score is: 100%`). The harness auto-clicks the next arrow or triggers `set_next_step()`.

---

## 3. Proven Failure Modes & Recovery Recipes

### Modal Lock & Course Drift (`rc=4 UNIT-CHANGED`)
- **Cause**: On task timeouts or step-switch locks, `auto.py` calls `t.goto(HOME)` to clear modals. Without active course enforcement, the LMS lands on the default course (often Unit 1 of Advanced 1), causing the child worker to abort with `UNIT-CHANGED`.
- **Fix**: Propagate `ED_COURSE` to child worker environments in `cover.py`. In `auto.py`, call `cover.ensure_course(t, target_course)` after navigating to `HOME`.

### Open-Ended Writing Stalls (`rc=0 STUCK` / `test-unanswered`)
- **Cause**: Prompts with `<div class="answersWrapper writingEditFrame OpenEndedQ">` get categorized as `other` if selectors only look for standard quiz inputs. Setting `.value` via JS does not notify Angular of changes.
- **Fix**:
  1. Detect open-ended writing tasks via `.writingEditFrame`, `textarea.writingTextarea`, or `OpenEndedQ`.
  2. Synthesize input using CDP `Input.insertText` after focusing the textarea.
  3. Dispatch `KeyboardEvent('keyup', {bubbles: true})` so Angular's `componentInstance.doneProgress` flips to `true`.

### Explore Audio Stalls (`rc=2 LESSON-INCOMPLETE [0, 1, 1]`)
- **Cause**: Moving to Practice before Explore media completes leaves Step 1 at `progress: 0`.
- **Fix**: Check `Progress >= 0.999`. If Explore is already marked done on LMS, skip media replay and switch straight to Practice via `solver.set_step(t, 1)`. If incomplete, set `playbackRate = 16.0` on all audio/video elements and poll `currentTime >= duration - 0.5` or `ended`.

### Speaking Gate Failure (`rc=3 SPEAK-BLOCKED`)
- **Cause**: Lessons with microphone practice (`Interact 1`, `Practice 1`) stall on audio permission dialogs or speech evaluation timeouts.
- **Fix**: Always run Chromium with `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`. Click `.button.continue` / `Start`, stream fake audio for 3.5s, and verify completion. If platform throws error 505 or loops on `Try again`, exit immediately with `rc=3` to avoid wasting retry budgets.

### Sequence Reordering Widgets
- **Cause**: Sequence items in `.sequenceZone` start pre-filled across target slots without a staging bank.
- **Fix**: Query item ordering, resolve target permutation via LLM, and execute `t.drag_xy` directly between slot coordinate centers with fresh box model measurements between drops.

---

## 4. Operational Commands Cheat-Sheet

```bash
# 1. Background batch run (recommended)
python3 -u cover.py 5-9 2 --course="Advanced 3"

# 2. Targeted lesson remediation
python3 cover.py 1 1 --course="Advanced 3" --lesson="IFL Broadcast"

# 3. Test-only run (skips already passed Explore/Practice)
python3 cover.py 1 1 --course="Advanced 3" --test-only

# 4. Dry-run LMS status audit (no changes made)
python3 cover.py 0-9 1 --course="Advanced 3" --dry

# 5. Check stuck task dump
python3 -c 'import json, glob; print(json.load(open(sorted(glob.glob("logs/fixtures/stuck_*.json"))[-1]))["body"][:300])'

# 6. Run test suite
python3 -m unittest discover -s tests
```
