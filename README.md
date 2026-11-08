# Engdis Autopilot

Automated browser testing and exercise solver harness for English Discoveries courseware via Chrome DevTools Protocol (CDP) and multimodal LLMs.

> **Recommended**: Use **Docker Compose**. Packages Chromium with required audio codecs, fake media streams, and memory limits out of the box.

---

## Quickstart

### 1. Setup
```bash
cp .env.example .env
# Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL in .env

mkdir -p ~/.config/engdis
printf "%s\n%s\n" "your_student_id" "your_password" > ~/.config/engdis/cred
chmod 600 ~/.config/engdis/cred

docker compose build
```

### 2. Run
```bash
# Docker Compose (0-based unit index)
ED_COURSE="Advanced 3" ED_UNIT=0 ED_DRY_RUN=0 docker compose run --rm engdis
ED_COURSE="Advanced 3" ED_UNIT=5-9 ED_PASSES=2 ED_DRY_RUN=0 docker compose run --rm engdis

# Host CLI (requires local Chromium + FFmpeg)
python3 cover.py 5-9 2 --course="Advanced 3"
python3 cover.py 1 1 --course="Advanced 3" --test-only
```

---

## Delegating to AI Agents

Compatible with [Agent Skills](https://agentskills.io) (Claude Code, Cursor, Copilot, Hermes, Codex, OpenClaw).

<details open>
<summary><b>Example Prompts</b> (click to collapse)</summary>

- **Unattended Background Run**:
  > `/engdis-autopilot Run background supervisor for "Advanced 3", Units 5-9, 2 passes. Run as background task, minimize chat interactions, and report final completion.`
- **Fix Stalled Tasks from Fixture**:
  > `@engdis-autopilot Autopilot stalled on a lesson. Inspect latest JSON in logs/fixtures/stuck_*.json. Check DOM HTML and task type, patch solver.py or auto.py, and verify with tests.`
- **Targeted Single-Lesson Test**:
  > `$engdis-autopilot Re-run failing test in "Unit 2: Overcoming Difficulties", lesson "A Bit Deaf" with --test-only. Confirm exit code 0.`

*Syntax supported: `/engdis-autopilot`, `@engdis-autopilot`, `$engdis-autopilot`, or `@skills/engdis-autopilot/SKILL.md`.*
</details>

<details>
<summary><b>Agent Operating Protocol</b> (click to expand)</summary>

1. **Background Batch**: Launch `cover.py` in background to prevent chat context token burn.
2. **Inspect Fixtures**: When stalled (4 unchanged ticks), inspect `logs/fixtures/stuck_*.json` for task `body` and `html`.
3. **Targeted Fix**: Isolate fix with `--lesson="..."`, `--step="..."`, or `--test-only`.
4. **Test Gate**: Run `python3 -m unittest discover -s tests` before pushing.
</details>

---

## Features

- **CDP Automation**: Direct DOM instrumentation, interaction simulation, and navigation over Chrome DevTools Protocol.
- **Multimodal LLM Solvers**: Solves text, multiple-choice, fill-in-the-blank, and drag-and-drop tasks using OpenAI-compatible endpoints.
- **Unified Audio Transcription**: Transcribes listening exercises via base64 audio chat completions—no separate Whisper service needed.
- **Low-RAM Containment**: Strict container limits (1280 MB RAM, 256 MB SHM) and Chromium heap capping for low-spec hosts.
- **Dual Execution Modes**: Unattended autonomous execution with watchdog recovery, plus operator diagnostic capture.

---

## Project Structure

```
├── cover.py               # Supervisor and lesson batch runner
├── auto.py                # Task runner, stage detector, DOM navigator
├── solver.py              # LLM prompt builder and answer extractor
├── driver.py              # CDP connection, tab control, network instrumentation
├── login.py               # Auth handler and session recovery
├── asr.py                 # Audio extraction and base64 transcription client
├── poll.py                # Predicate polling and backoff utilities
├── bootstrap_browser.py   # Headless Chromium launcher with CDP health polling
├── compose.yaml           # Container definition with resource limits
├── Dockerfile             # Debian Bookworm container image with Chromium & FFmpeg
├── skills/
│   └── engdis-autopilot/  # In-repo operational skill (SKILL.md)
├── docs/                  # Detailed configuration, architecture, and auth guides
└── tests/                 # Unit and container test suite
```

---

## Documentation

- [Configuration Reference](docs/configuration.md) — All environment variables and LLM options.
- [Authentication Setup](docs/authentication.md) — Credential files and environment variable formats.
- [Architecture & Execution](docs/architecture.md) — Unattended vs. progressive patching and memory limits.
- [Diagnostic Dashboard](docs/dashboard.md) — Real-time web UI, screenshot stream, and JSONL events.

---

## Testing

```bash
# Local test suite
python3 -m unittest discover tests

# Containerized test suite
docker run --rm --entrypoint python3 engdis-autopilot:test -m unittest discover tests
```

---

## Safety & License

- **Safety & Ethics**: Review [SAFETY.md](SAFETY.md) and [SECURITY.md](SECURITY.md) before use.
- **License**: [MIT License](LICENSE) © 2026 Nguyễn Văn Trãi.
