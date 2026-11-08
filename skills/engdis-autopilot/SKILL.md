---
name: engdis-autopilot
description: Operate and debug Engdis courseware automation harness.
version: 0.2.0
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

- Launching unattended batch runs across course units.
- Isolating and debugging failed exercises or navigation stalls.
- Inspecting auto-dumped task fixtures (`logs/fixtures/stuck_*.json`).
- Running tests before committing engine patches.

## Prerequisites

- **Docker & Docker Compose**: Preferred runtime. Packages Chromium with required audio codecs, fonts, and resource caps.
- **Chrome Flags**: If running on host, Chrome must launch with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --autoplay-policy=no-user-gesture-required`.
- **Credentials**: Stored in `~/.config/engdis/cred` or environment variables `ED_USER` / `ED_PASS`.
- **LLM Endpoint**: OpenAI-compatible API configured in `.env` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`).

## Quick Reference

```bash
# Multi-unit batch run (e.g. Units 5 to 9, 2 passes)
python3 cover.py 5-9 2 --course="Advanced 3"

# Single lesson targeting
python3 cover.py 1 1 --course="Advanced 3" --lesson="IFL Broadcast"

# Test-only pass (skips Explore & Practice if already done)
python3 cover.py 1 1 --course="Advanced 3" --test-only

# Specific step debugging
python3 cover.py 1 1 --course="Advanced 3" --step="Practice"

# Dry-run inspection (inspects current LMS state without solving)
python3 cover.py 0-9 1 --course="Advanced 3" --dry
```

## Operational Procedures

### 1. Diagnosing Stalled Exercises via Fixtures
When `auto.py` detects 4 consecutive unchanged ticks, it dumps the full task state to:
`logs/fixtures/stuck_<lesson>_<task>_<timestamp>.json`

The fixture includes:
- `body`: Visible text of the task.
- `html`: Raw HTML DOM of the exercise container.
- `compState`: Angular component properties (`doneProgress`, `isSubmitted`, `currentState`, `taskType`).
- `interactives`: List of all visible clickable elements (`tag`, `cls`, `id`, `text`, `rect`).
- `screenshot`: Base64 PNG viewport capture.

To inspect a stalled task:
```python
import json, glob
path = sorted(glob.glob("logs/fixtures/stuck_*.json"))[-1]
data = json.load(open(path))
print("URL:", data.get("url"))
print("BODY:", data.get("body", "")[:300])
print("COMP STATE:", data.get("compState"))
print("CLICKABLES:", [(el["tag"], el["cls"], el["text"][:30]) for el in data.get("interactives", [])])
```
Use this to identify missing exercise selectors in `solver.py` without needing a live browser session.

### 2. Media Acceleration (Explore Steps)
Audio and video playback in Explore steps can be accelerated to 16x:
```javascript
document.querySelectorAll('audio,video').forEach(m => {
  try { m.playbackRate = 16.0; } catch(e){}
});
```
This triggers server completion beacons in 2–4 seconds instead of waiting full media duration.
If Step 1 Explore shows `Progress >= 0.999`, skip media replay immediately and switch to Step 2 Practice via dropdown `solver.set_step(t, 1)`.

### 3. Speaking Gates & Fake Stream Simulation
Interactive speaking tasks (`Interact 1` / `Practice 1`) require audio input.
With `--use-fake-device-for-media-stream`:
1. Click `.button.continue` / `Start`.
2. Wait 3.5s while streaming fake audio.
3. Verify task counter changes or `done=True`.
If microphone error 505 or repeated `Try again` occurs, record as `SPEAK-BLOCKED` (rc=3) to prevent burning supervisor restart budgets.

### 4. Course Navigation Drift Guard
When recovering from modal locks or step-switch stalls via `t.goto(HOME)`, always verify and re-bind active course:
```python
target_course = os.environ.get("ED_COURSE") or config.ED_COURSE
if target_course:
    cover.ensure_course(t, target_course)
```
Pass `ED_COURSE` down to all child worker subprocesses to avoid dropping back to Unit 1 of Advanced 1 (`rc=4 UNIT-CHANGED`).

### 5. DOM Transcript Extraction Before LLM ASR
Always inspect `#textContainer`, `.seeTextContainer`, and `.learning__RATextW` before invoking audio transcription. Video and listening tasks frequently embed full transcripts in the markup. Extracting DOM text avoids ASR timeouts and saves token budget.

### 6. Typed / Open-Ended Task Registration
Assigning `.value` alone does not count towards activity completion. Angular open-ended text areas require keyboard triggers:
1. Focus textarea: `ta.focus()`.
2. Insert text: CDP `Input.insertText`.
3. Dispatch keyup: `ta.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}))`.
Verify `componentInstance.doneProgress === true`.

### 7. Sequence Reordering Widgets
Widgets using `.sequenceZone` / `.prSeq__zone--txt` start with items pre-filled across target zones with no bank placeholder. Use `solve_sequence(t, src)` to extract order, query 1-based order array, and perform direct CDP drags (`t.drag_xy`) between zone centers with fresh rect measurements between drops.

### 8. Single-Owner Browser Rule
Never open ad-hoc WebSocket connections to CDP port 9225 while `cover.py` or `auto.py` is running in the background. Concurrent connections lock the DevTools loop and cause command timeouts. Read status non-invasively via `status.py`, `live_status.json`, or log tails.

### 9. Test Score Screen Auto-Advance
When assessment displays `"Your test score is: 100%"` or `"Review your answers"`, do not retry questions. Click the next arrow button (`.arrow-right`, `.nextStepArrow`) or invoke `solver.set_next_step()` to complete lesson handoff.

### 10. Autonomous Agent Yield & Hot-Fix Protocol
The harness halts and signals coding agents with exit code `rc=6` and an actionable `[AGENT-ACTION-REQUIRED]` block on `stderr` when:
1. **Exercise Stall**: Any exercise fails to advance for 4 consecutive ticks. DOM HTML, Angular `compState`, and base64 PNG screenshot are dumped to `logs/fixtures/stuck_*.json`.
2. **Under-Completion Gate**: The supervisor batch finishes, but one or more lessons remain `< 100%` complete.

**Fast-Forward Resumption**:
When targeted to fix an incomplete lesson (`--lesson="..."`), `auto.py` reads the step progress from `ed-la-dropdownlist` and automatically fast-forwards directly to the first incomplete step, preserving already completed work and saving tokens.

- In **Unattended mode** (`--unattended` flag or `ED_UNATTENDED=1`), stalls and under-completions are logged, and the harness exits `rc=0` without blocking.

If you are a coding agent executing the harness via terminal:
- The command finish returns control immediately to your active chat turn.
- Read the fixture path printed in the error block.
- Follow the 4-step remediation loop:
  1. Inspect fixture DOM and `compState`.
  2. Add reproducer test in `tests/test_stuck_cases.py`.
  3. Patch `solver.py` or `auto.py`.
  4. Run `python3 -m unittest discover -s tests` and re-run with `--lesson="..."`.

### 11. Grill-Me Ambiguity Gate (Pre-Execution Interview)
Never guess or extrapolate vague user instructions. If a user request lacks 100% clarity regarding targets, modes, or boundaries (e.g. "run the course", "fix the test", "do it again"):
**Do not execute commands immediately.** Stop and grill the user with a single structured round of numbered questions:
- Each question must include your recommended option first.
- Word recommendations so a simple "yes" or choice selection confirms it.
- Never ask what you can verify from tools/files (check current course and progress via LMS/reports first).

**Clarification Checklist**:
1. **Target Course & Unit Scope**: Exact course name (e.g. `"Advanced 3"`) and unit range (e.g. `0-9` vs `5-9`).
2. **Execution Mode**: Agent Yield mode (stops on stalls to let agent fix) vs Unattended mode (`--unattended`, logs & continues).
3. **Step Scope**: Full lesson vs `--test-only` vs specific `--step="Practice"`.
4. **Retry Budget**: Number of passes (default 2).

**Template**:
```text
Before launching, confirm your exact run configuration:
1. Target Course & Units: Run "Advanced 3" Units 5-9? (Recommended) [Yes / Other range]
2. Execution Mode: Agent Yield mode (rc=6 halts to fix stalls)? (Recommended) [Agent Yield / Unattended]
3. Step Scope: Full lessons (Explore + Practice + Test)? (Recommended) [Full / Test-Only]
```

## Verification

Run the offline mock test suite:
```bash
python3 -m unittest discover -s tests
```
All tests must pass before committing any changes to `auto.py`, `cover.py`, or `solver.py`.
