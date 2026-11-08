---
name: engdis-autopilot
description: Operate and debug Engdis courseware automation harness.
version: 0.1.0
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

To inspect a stalled task:
```python
import json
data = json.load(open("logs/fixtures/stuck_Lesson_1__Call_In_5_20261107_182023.json"))
print(data.keys())       # ['meta', 'html', 'practiceData', 'body', 'url']
print(data["body"])      # Visible text of the task
print(data["html"])      # Raw HTML DOM of the exercise container
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

### 3. Speaking Gates
Interactive speaking tasks (Interact 1 / 2) require microphone input.
With `--use-fake-device-for-media-stream`, click **Start**, wait 3.5s for the fake audio stream, and let the speech session register the attempt. The server marks the step completed once an attempt is recorded.

### 4. Course Navigation Drift Guard
When recovering from modal locks via `t.goto(HOME)`, always ensure the active course matches `ED_COURSE`:
```python
target_course = os.environ.get("ED_COURSE") or config.ED_COURSE
if target_course:
    cover.ensure_course(t, target_course)
```

## Verification

Run the offline mock test suite:
```bash
python3 -m unittest discover -s tests
```
All tests must pass before committing any changes to `auto.py`, `cover.py`, or `solver.py`.
