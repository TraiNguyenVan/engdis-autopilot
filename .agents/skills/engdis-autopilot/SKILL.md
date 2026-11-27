---
name: engdis-autopilot
description: Operate and debug Engdis courseware automation harness.
version: 0.3.0
author: Trai Nguyen (TraiNguyenVan), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [courseware, cdp, automation, ed22, ptit]
---

# Engdis Autopilot Skill

Operational procedures for AI coding agents running, diagnosing, and repairing the Engdis courseware automation harness.

## When to Use

- Launching unattended or Agent Yield batch runs across course units.
- Operating a visible local browser for an Assessment Center exam.
- Isolating and debugging failed exercises or navigation stalls via `logs/fixtures/stuck_*.json`.
- Running the offline test suite before committing engine patches.

## Run Modes: Routine Coursework vs Assessment Center Exams

- **Routine coursework** (lessons, practice, and **unit lesson tests**): Unit lesson tests are **ungraded** and only affect unit completion percentage. Run via Docker headless (`docker compose run --rm engdis` or `engdis_inspect`) or `--headed` locally if watching. Do not retake a passed unit lesson test (`--force`, `--retest`) unless intentionally replacing its percentage.
- **Agent Yield vs Unattended**: Default to Agent Yield mode (`cover.py` exits `rc=6` on stalls so you can inspect/patch). Reserve `--unattended` / `ED_UNATTENDED=1` for routine coverage when skipping stalled tasks is acceptable. Neither `cover.py` nor `solver.py` guarantees 100% completion or scores.
- Expect first-run friction across machines: browser/CDP availability, codecs, login state, model endpoints, and LMS timing vary. Start with a small non-critical run and confirm progress and results before scaling up.
- **Graded Assessment Center exams** (midterm, final, placement): Live outside the unit/lesson tree; `cover.py` cannot open them. This path is **unverified** (no Assessment Center fixture or verified live run in this repo—do not imply it is proven safe).
  1. Ask for any unclear/missing details first; check that port `9225` and `~/.ed-profile` are not already in use.
  2. Start visible local Chrome: `python3 bootstrap_browser.py --headed --port 9225 --profile ~/.ed-profile`, and verify the window and CDP connection.
  3. Stop and inform the user if the exam requires a real microphone (`bootstrap_browser.py` passes `--use-fake-device-for-media-stream`).
  4. Help log in if needed, then wait for the user to open the exam manually and authorize the attempt.
  5. Do **not** use `cover.py`, Docker, headless mode, or `--unattended`. Attach `auto.py` to the open exam tab, monitor every question, verify an answer is registered before advancing, stop without submitting on an empty question, stalled counter, reminder, or ambiguity, and submit only after every question is visibly answered.

## Prerequisites & Configuration

- **Dual Course Guarantee (Advanced 2 & 3)**: All automation logic, selectors, and solvers must work across both Advanced 2 and Advanced 3 curricula without regression. Never remove existing widget handlers.
- **Docker & Docker Compose**: Preferred runtime for routine coursework. Packages Chromium with required audio codecs, fonts, and memory limits.
- **Credentials & LLM Config (`.env` / `config.py`)**:
  - Auth: `ED_USER`, `ED_PASS` (or `ED_CRED` pointing to a protected file with two lines: username, then password).
  - LLM: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` (supports comma-separated fallback list in `LLM_MODELS`).
  - Listening STT (optional, recommended): `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_WHISPER_MODEL` (default `whisper-large-v3-turbo`).
  - Course/Runtime: `ED_COURSE`, `ED_CDP_PORT` (default `9225`), `ED_DRY_RUN`, `ED_SCRATCH`, `ED_REPORT_DIR`.
- **Chrome Flags (`bootstrap_browser.py`)**: Launches with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --autoplay-policy=no-user-gesture-required` (headless by default; pass `--headed` for visible window).

## Quick Reference

> **CRITICAL EXECUTION RULE**: Never run `python3 cover.py` for headless batch runs directly on the host machine; execute headless coursework via Docker. Never guess course or units—inspect active LMS state first (`--dry` / `ED_DRY_RUN=1`) or ask explicitly.

Compose defaults to `ED_DRY_RUN=1`: this inventories eligible lessons and does not run the solver. Set `ED_DRY_RUN=0` only for an authorized run. Compose does not forward the host's `ED_UNATTENDED` by default; use `docker compose run -e` to pass it explicitly.

```bash
# Multi-unit batch run via Docker (Agent Yield mode: exits rc=6 on stall)
ED_COURSE="<COURSE>" ED_UNITS="<UNITS>" ED_PASSES=2 ED_DRY_RUN=0 docker compose run --rm engdis

# Multi-unit unattended run via Docker (skips stalled tasks; other failures can still exit nonzero)
ED_COURSE="<COURSE>" ED_UNITS="<UNITS>" ED_PASSES=2 ED_DRY_RUN=0 docker compose run --rm -e ED_UNATTENDED=1 engdis

# Long-running inspect container (engdis_inspect)
docker exec engdis_inspect python3 -u cover.py <UNITS> 2 --course="<COURSE>"
docker exec engdis_inspect python3 -u cover.py <UNITS> 2 --course="<COURSE>" --unattended
docker exec engdis_inspect python3 cover.py <UNIT_IDX> 1 --course="<COURSE>" --lesson="<LESSON_NAME>"
docker exec engdis_inspect python3 cover.py <UNIT_IDX> 1 --course="<COURSE>" --test-only
docker exec engdis_inspect python3 cover.py <UNIT_IDX> 1 --course="<COURSE>" --step="Practice"
docker exec engdis_inspect python3 cover.py 0-9 1 --course="<COURSE>" --dry

# Local visible browser (optional for watching unit lesson tests; required for Assessment Center)
python3 bootstrap_browser.py --headed --port 9225 --profile ~/.ed-profile
```

## Operational Procedures

### 1. Diagnosing Stalled Exercises via Fixtures
When `auto.py` detects 4 consecutive unchanged ticks, it attempts to dump task state to `ED_FIXTURE_DIR` or `/data/logs/fixtures`, falling back to the repo's `logs/fixtures` if the directory cannot be created. The filename is `stuck_<lesson>_<counter>_<timestamp>.json`; inspect the reported path or dump error.

The fixture can include `url`, `body` (visible text), `html` (raw DOM), `practiceData`, `compState` (Angular properties like `doneProgress`, `isSubmitted`, `currentState`, `taskType`), and `interactives` (visible clickables with `tag`, `cls`, `id`, `text`, `rect`). `screenshot` may be `null`: `dump_task` calls `t.cdp`, but `driver.Tab` has no `cdp` method; capture can also fail. Do not assume an image was recorded.

```python
import json
path = "<reported fixture path>"
with open(path, encoding="utf-8") as f:
    data = json.load(f)
print("URL:", data.get("url"))
print("BODY:", data.get("body", "")[:300])
print("COMP STATE:", data.get("compState"))
print("CLICKABLES:", [(el["tag"], el["cls"], el["text"][:30]) for el in data.get("interactives", [])])
```

### 2. Media Acceleration (Explore Steps)
`solver.play_media(t)` attempts playback at `playbackRate = 16.0`; accelerated or started playback does not prove server completion. Verify saved progress after playback and navigation. If the step remains incomplete, inspect the actual activity rather than skipping it.

### 3. Speaking Gates & Fake Stream Simulation (Known Limitation)
Speaking tasks may reject fake audio. A rejected recording returns `speak: blocked`; the main loop counts speaking attempts and exits `SPEAK-BLOCKED` (`rc=3`) after three on the same task. Treat actual speech recognition and saved completion as unverified; do not infer a fixed completion percentage from a speaking exercise. Inspect unfinished activities individually. The current disabled-Start fallback calls an internal progress setter; do not rely on it as evidence that speech was completed or use it to manufacture progress.

### 4. Course Navigation Drift Guard
When recovering from modal locks or step-switch stalls via `t.goto(HOME)`, re-bind the active course:
```python
target_course = os.environ.get("ED_COURSE") or config.ED_COURSE
if target_course:
    cover.ensure_course(t, target_course)
```
Propagate `ED_COURSE` to child worker subprocesses to avoid dropping back to Unit 1 of Advanced 1 (`rc=4 UNIT-CHANGED`).

### 5. Audio/Video Transcript Resolution (DOM + ASR)
- `solver.attach_transcript(t, src, label="--", prefer_last_media=False)` checks DOM transcripts first (`dom_transcript(t)` inspecting `#textContainer`, `.seeTextContainer`, `.learning__RATextW`) before falling back to `solver.media_url(t, prefer_last=prefer_last_media)` and `transcript_for(u, key)` (cached by `stem_ext` via `_media_cache_key`), wrapping output in `AUDIO TRANSCRIPT:\n...\n[/AUDIO TRANSCRIPT]`.
- `solver.media_url(t, prefer_last=False)` filters `<audio, video>` elements that have `currentSrc || src`, prefers visible elements, and scopes to `ed-la-practicearea, #pmContainer` before `ed-la-resourcearea` (or picks the last matching URL when `prefer_last=True`, used by `auto.handle_test`).
- `auto.py` calls `solver.resolve_task_transcript(t, task_src, (s.get("lesson"), s.get("step")), transcript_state)` on non-speaking practice tasks so the transcript is retained across questions in the same `(lesson, step)` activity and cleared when the activity or `media_url` changes.

### 6. Typed / Open-Ended Task Registration
Assigning `.value` alone does not notify Angular. Open-ended text areas (`.writingEditFrame`, `textarea.writingTextarea`, `.OpenEndedQ`) require:
1. Focus textarea: `ta.focus()`.
2. Insert text via CDP `Input.insertText`.
3. Dispatch keyup: `ta.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}))`.
Verify `componentInstance.doneProgress === true`.

### 7. Drag-and-Drop & Sequence Reordering Widgets
- **Drag-and-drop (`solver.solve_drag`)**:
  - Excludes the word bank (`_BANK_ZONE = "TTpTablePlaceHolder"`, checked via `dg_name` or `id` in `_is_bank_zone`) from target zones.
  - Clears pre-filled target zones back to the bank before re-dropping.
  - Retries drops across `_DRAG_DROP_OFFSETS = ((0, 0), (-25, 0), (25, 0), (0, -4), (0, 4), (0, 8))`, clamped to target width (`_clamp_drop_offset`).
  - Uses `_scroll_drag_into_view` (skipping scroll when both endpoints are already visible, checking ancestor overflow clipping and `elementFromPoint`) plus `_endpoints_reachable` / `_too_far_for_offsets` so unreachable targets fail cleanly with `UNREACHABLE`.
  - `edlib.rects(t)` returns `id`, `w`, `h` alongside `cx`, `cy`, `n`, `count`.
- **Sequence reordering (`solver.solve_sequence`)**:
  - Widgets using `.sequenceZone` / `.prSeq__zone--txt` start with items pre-filled across target zones with no bank placeholder. Extracts current order, queries a 1-based target order array, and performs direct CDP drags (`t.drag_xy`) between zone centers with fresh rect measurements between drops.

### 8. Single-Owner Browser Rule
Never open ad-hoc WebSocket connections to CDP port 9225 while `cover.py` or `auto.py` is running in the background. Concurrent connections lock the DevTools loop and cause command timeouts. Read status non-invasively via `status.py`, `live_status.json`, or log tails.

### 9. Test Score Screen Auto-Advance
`auto.py` attempts to advance on score text or on `"Review your answers"` combined with `"next arrow"`; review text alone does not prove a final result or lesson completion. Distinguish lesson-test, assessment-section, and final assessment screens; verify the saved score and each required step separately. Do not retry or submit an already recorded test without explicit authorization. If the screen or transition is ambiguous, stop and inspect it rather than assuming handoff succeeded.

### 10. Autonomous Agent Yield & Hot-Fix Protocol
The harness halts and signals coding agents with exit code `rc=6` and `[AGENT-ACTION-REQUIRED]` on `stderr` when:
1. **Exercise Stall**: The task signature is unchanged for 4 consecutive ticks; the worker attempts a fixture dump and reports its path or error.
2. **Under-Completion Gate**: In supervised mode, the final check examines all reported lessons, including lessons outside the selected scope, excluding those marked blocked. It flags normalized final progress `< 0.999` and returns `rc=6`; exclusion does not establish completion. The gate also runs after a dry inventory, so `rc=6` alone does not prove a solver ran or that a selected lesson stalled.

**Fast-Forward Resumption**: When targeted with `--lesson="..."`, `auto.py` reads step progress from `ed-la-dropdownlist` and fast-forwards to the first incomplete step. In `--unattended` / `ED_UNATTENDED=1` mode, a stalled worker logs a warning and exits `rc=0`, and the supervisor skips its final under-completion gate. Other failures can still produce nonzero exits; `rc=0` does not prove completion.

Remediation loop on `rc=6`:
1. Inspect the dumped fixture DOM and `compState`.
2. Add an offline reproducer test in `tests/` (e.g., `tests/test_fixture_dump.py` or a targeted `tests/test_<area>.py` module).
3. Patch `solver.py` or `auto.py`.
4. Run `python3 -m unittest discover -s tests` and re-run with `--lesson="..."`.

### 11. Grill-Me Ambiguity Gate (Pre-Execution Interview)
Never guess or extrapolate vague user instructions (e.g. "run the course", "fix the test", "do it again"). Stop and ask a single structured round of numbered questions (recommended option first, never asking what can be verified from LMS/files):
1. **Target Course & Unit Scope**: Exact course name and unit range.
2. **Execution Mode**: Agent Yield mode (`rc=6` halts on stalls) vs Unattended (`--unattended`, logs & continues).
3. **Step Scope**: Full lessons (Explore + Practice + Test) vs `--test-only` vs `--step="Practice"`.
4. **Retry Budget**: Number of passes (default `2`).

## Verification

Run the offline mock test suite before committing changes:
```bash
python3 -m unittest discover -s tests
```
