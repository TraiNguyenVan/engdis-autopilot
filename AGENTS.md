# AGENTS.md

Instructions, conventions, and operational patterns for AI coding agents (Claude Code, Cursor, Codex, Antigravity, OpenClaw, Hermes) working in this repository.
For detailed contribution protocols, fixture reproduction steps, and PR gates, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 1. Core Operating Principles

1. **Top-Level Configuration**: Supply credentials and LLM settings via `.env` (`ED_USER`, `ED_PASS`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`).
2. **Dual Course Guarantee (Advanced 2 & 3)**: All automation logic, selectors, and solvers must work seamlessly on both Advanced 2 and Advanced 3 curricula without regression. Never remove existing widget handlers.
3. **Zero Chat-Token Burn**: Never run supervisor loops interactively in conversation turns. Always launch batches as non-blocking background tasks and report only final completion status or actionable blockers.
4. **Single-Owner Browser Rule**: Never open ad-hoc WebSocket connections to CDP port 9225 while a background `cover.py` or `auto.py` process is active. Concurrent DevTools connections cause CDP packet drops, tab race conditions, and runner timeouts.
5. **Reproduce via Offline Fixtures First**: When an exercise stalls, inspect auto-dumped state in `logs/fixtures/stuck_*.json`. Write a mock unit test in `tests/` recreating the task DOM before editing `solver.py` or `auto.py`.
6. **Mandatory Test Suite Gate**: Run `python3 -m unittest discover -s tests` before committing any changes. All 58+ tests must pass.

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

### Speaking Gate Failure (`rc=3 SPEAK-BLOCKED`) - Known Limitation
- **Status**: **Unsupported / Not Solved Yet**. Genuine mic audio synthesis (TTS pipe to virtual mic) is not implemented.
- **Cause**: Lessons with microphone practice (`Interact 1`, `Practice 1`, e.g. Lesson 3 across most units) require spoken audio. Headless Chromium feeds fake silence (`--use-fake-device-for-media-stream`), which the LMS server-side ASR rejects with "Try again".
- **Expected Behavior**: Lessons containing speaking tasks will deliberately fail closed with `rc=3 SPEAK-BLOCKED` after 3 failed attempts, capping at **67% progress**.
- **Agent Rule**: **Do NOT treat 67% on speaking lessons as an actionable bug or stall.** Do not attempt to retry or fix them in code until a virtual audio loopback/TTS bridge is added. The supervisor records them in the `blocked` set and safely skips them on later passes.

### Sequence Reordering Widgets
- **Cause**: Sequence items in `.sequenceZone` start pre-filled across target slots without a staging bank.
- **Fix**: Query item ordering, resolve target permutation via LLM, and execute `t.drag_xy` directly between slot coordinate centers with fresh box model measurements between drops.

### Autonomous Yield Protocol (`rc=6`) & Unattended Mode
The harness signals coding agents via `rc=6` and `[AGENT-ACTION-REQUIRED]` on `stderr` under two failure conditions:

1. **Exercise Stall**: If a task does not advance after 4 unchanged ticks, `auto.py` dumps full DOM/compState/screenshot to `logs/fixtures/stuck_*.json`, emits `[AGENT-ACTION-REQUIRED]`, and exits `rc=6`.
2. **Under-Completion Gate**: At the end of a batch, if any lesson finished below 100% progress (and wasn't skipped due to microphone permissions), `cover.py` lists the incomplete lessons, emits `[AGENT-ACTION-REQUIRED]`, and exits `rc=6`.

```text
[AGENT-ACTION-REQUIRED]
Batch finished with incomplete lesson(s):
- Unit 5: Truth And Lies -> News (33%)
Re-run with targeted lesson command to finish.
```

**Fast-Forward Resumption**:
When retrying an incomplete lesson, `auto.py` automatically checks step progress and fast-forwards directly to the first incomplete step (e.g. skipping passed Explore media or Practice), preventing wasted tokens or redundant work.

- In **Unattended mode** (`--unattended` or `ED_UNATTENDED=1`), stalls and incomplete lessons are logged to report JSON and the batch exits `rc=0` without waking the agent.

### Ambiguity Gate (Grill-Me Protocol)
If user instruction lacks complete precision (e.g., "run it", "test the rest", "fix issues"), **do not execute immediately and do NOT assume course or units**.
Inspect LMS state first (`docker compose run --rm -e ED_DRY_RUN=1 engdis` or query active course/units), then ask:
1. Target Course & Units to cover?
2. Mode: Agent Yield (`rc=6` on stall) vs Unattended (`--unattended`)?
3. Scope: Full lesson vs `--test-only` vs specific `--lesson`?

---

## 4. Operational Commands Cheat-Sheet

> **CRITICAL EXECUTION RULE**: The harness requires headless Chromium on port 9225 with fake media stream flags.
> **NEVER execute `python3 cover.py` directly on the host.**
> Always run inside Docker via `docker compose run` or `docker exec`.

### Mode A: Production / Unattended Runner (Fresh Container)
```bash
# 1. Unattended batch run (specify exact course and units)
ED_COURSE="<COURSE>" ED_UNITS="<UNITS>" ED_PASSES=2 ED_UNATTENDED=1 docker compose run --rm engdis

# 2. Agent Yield mode (rc=6 on stall)
ED_COURSE="<COURSE>" ED_UNITS="<UNITS>" ED_PASSES=2 docker compose run --rm engdis

# 3. Dry-run LMS status audit (shows real course progress)
ED_COURSE="<COURSE>" ED_UNITS="0-9" ED_DRY_RUN=1 docker compose run --rm engdis
```

### Mode B: Development / Interactive Container (`engdis_inspect`)
If long-running browser container `engdis_inspect` is active:
```bash
# 1. Background batch run (Agent Yield mode)
docker exec engdis_inspect python3 -u cover.py <UNITS> 2 --course="<COURSE>"

# 2. Unattended batch run
docker exec engdis_inspect python3 -u cover.py <UNITS> 2 --course="<COURSE>" --unattended

# 3. Targeted lesson remediation
docker exec engdis_inspect python3 cover.py <UNIT_IDX> 1 --course="<COURSE>" --lesson="<LESSON_NAME>"

# 4. Dry-run LMS status audit
docker exec engdis_inspect python3 cover.py 0-9 1 --course="<COURSE>" --dry
```

### Mode C: Diagnostic & Test Suite (Host OK)
```bash
# 1. Run offline unit tests (no browser needed)
python3 -m unittest discover -s tests

# 2. Check stuck task dump
python3 -c 'import json, glob; print(json.load(open(sorted(glob.glob("logs/fixtures/stuck_*.json"))[-1]))["body"][:300])'
```
