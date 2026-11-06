# Architecture & Execution Models

## Container Architecture & Containment

The Docker harness packages the full execution environment to eliminate host dependency divergence:

- **Base Image**: `python:3.11-slim-bookworm` with Chromium, FFmpeg, curl, procps.
- **Security**: Runs as unprivileged user `engdis` (UID `1000:1000`).
- **RAM Limits**:
  - Container RAM limit: `1280M` (`mem_limit: 1280m`, reservation `512m`)
  - Shared memory: `shm_size: 256m`
  - Chromium V8 heap cap: `--js-flags=--max-old-space-size=768 --renderer-process-limit=2`
- **Headless Bootstrap**: `bootstrap_browser.py` cleans stale profile locks, launches headless Chromium, and polls CDP readiness on port `9225` before launching the supervisor.

## Execution Modes

### 1. Unattended Execution (Standalone / Headless)

- **Mechanics**: Runs autonomously via the supervisor (`cover.py`) and task solver (`auto.py`). The runner navigates lessons, identifies known exercise types, executes interactions via Chrome DevTools Protocol (CDP), and logs progress.
- **Fault Tolerance**: When an unhandled interaction pattern or unresponsive widget is encountered, the per-lesson watchdog terminates the stalled worker with a timeout (`rc=-9`), logs the failure, and proceeds to the next lesson. Subsequent passes retry incomplete lessons.
- **Portability**: Fully functional on any standard Docker host, VM, or CI/CD environment with internet access, Chromium, FFmpeg, and an OpenAI-compatible LLM endpoint. No external supervisor or coding agent is required.

### 2. Progressive Patching (Operator-in-the-Loop)

- **Nature**: Progressive patching is an iterative development workflow where an external human or coding agent refines solvers against new exercise patterns.
- **Diagnostics**: When tasks stall or fail, `diag_logger.py` writes structured JSONL events (`logs_diag/events.jsonl`) and persists point-of-failure DOM snapshots and screenshots (`logs_diag/evidence/`). The optional diagnostic dashboard (`dashboard_server.py`) surfaces live status, recent events, and on-demand browser screenshots.
- **Patch Cycle**: An operator inspects the diagnostic stream, diagnoses the failing DOM structure or event sequence, applies targeted patches to `solver.py` or `auto.py`, and allows the supervisor's next pass to execute the corrected logic.
- **Graceful Fallback**: Without an active operator, the harness operates in unattended mode—bypassing unhandled edge cases via timeouts.
