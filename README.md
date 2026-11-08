# Engdis Autopilot

Automated browser testing and exercise solver harness for English Discoveries courseware via Chrome DevTools Protocol (CDP) and multimodal LLMs.

> **Recommended**: Use the **Docker setup**. Running directly on the host requires matching Chromium binaries, FFmpeg, audio codecs, and fonts. The container packages the complete runtime with memory limits and process management out of the box.

---

## Agent Operations & Example Prompts

This repository is optimized for autonomous AI coding agents (Hermes, Claude Code, Codex, Antigravity, OpenClaw).

### Example Prompts for AI Agents

Under the [Agent Skills open standard](https://agentskills.io), invoke the bundled skill directly using slash commands (`/engdis-autopilot`), mentions (`@engdis-autopilot`, `$engdis-autopilot`), or file references (`@skills/engdis-autopilot/SKILL.md`):

#### 1. Unattended Background Course Run
```text
/engdis-autopilot Run the background supervisor for course "Advanced 3", covering Units 5 through 9 with 2 passes. Launch the process as a background task, minimize chat interactions to conserve LLM tokens, and report back only the final completion percentage and any stalled units.
```

#### 2. Debug & Fix Stalled Tasks from Fixtures
```text
@engdis-autopilot The autopilot stalled on a lesson. Inspect the latest JSON dump in `logs/fixtures/stuck_*.json`. Analyze the recorded DOM HTML and task type, identify why the current solver in `solver.py` or `auto.py` failed to click or answer, add a reproducer test in `tests/`, patch the logic, and verify against the test suite.
```

#### 3. Targeted Single-Lesson Remediation
```text
$engdis-autopilot Re-run only the failing test in "Unit 2: Overcoming Difficulties", lesson "A Bit Deaf". Use the test-only flag `--test-only` to avoid re-running already completed explore steps. Confirm the final exit code is 0.
```

*(Supported invocation syntax across agents: `/engdis-autopilot` in Claude Code / Copilot / Cursor, `@engdis-autopilot` or `$engdis-autopilot` in agent harnesses supporting skill mentions, or direct path `@skills/engdis-autopilot/SKILL.md`).*

### Autonomous Operating Protocol
When an agent is tasked with running or fixing courses, follow this loop:

1. **Launch Non-Blocking Background Batch**:
   Run supervisor in background to avoid consuming chat context tokens:
   ```bash
   python3 -u cover.py 5-9 2 --course="Advanced 3"
   ```
2. **Inspect Fixtures on Stall**:
   When exercises cannot be solved or reach 4 unchanged ticks, the harness auto-dumps task state to:
   ```bash
   ls -lt logs/fixtures/stuck_*.json
   ```
   Inspect `body` and `html` in the JSON fixture to identify missing DOM selectors or task types without needing a live browser session.
3. **Targeted Remediation & Re-run**:
   Isolate and verify the fix on the exact failing lesson and step:
   ```bash
   # Test-only pass
   python3 cover.py 1 1 --course="Advanced 3" --test-only

   # Step-specific pass
   python3 cover.py 1 1 --course="Advanced 3" --step="Practice"
   ```
4. **Offline Test Suite Gate**:
   Always run the unit test suite before pushing patches:
   ```bash
   python3 -m unittest discover -s tests
   ```

---

## Key Features

- **CDP Automation**: Direct DOM instrumentation, interaction simulation, and navigation over Chrome DevTools Protocol.
- **Multimodal LLM Solvers**: Solves text, multiple-choice, fill-in-the-blank, and drag-and-drop tasks using OpenAI-compatible endpoints.
- **Unified Audio Transcription**: Transcribes listening exercises via base64 audio chat completions—no separate Groq or Whisper API key required.
- **Low-RAM Containment**: Strict container limits (1280 MB RAM, 256 MB SHM) and Chromium heap capping for low-spec hosts.
- **Dual Execution Modes**: Unattended autonomous execution with watchdog recovery, plus operator-in-the-loop diagnostic capture.

---

## Quickstart (Docker Compose)

### 1. Configure Environment
Copy the example environment file and set your credentials:
```bash
cp .env.example .env
# Edit .env with your OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL
```

Provide course login credentials (see [Authentication Guide](docs/authentication.md)):
```bash
mkdir -p ~/.config/engdis
cat << 'EOF' > ~/.config/engdis/cred
your_username_or_student_id
your_password
EOF
chmod 600 ~/.config/engdis/cred
```

### 2. Build the Image
```bash
docker compose build
```

### 3. Run

```bash
# Docker Compose (single unit, range, or list; 0-based index)
ED_UNIT=8 ED_DRY_RUN=0 docker compose run --rm engdis
ED_UNIT=8-9 ED_PASSES=1 ED_DRY_RUN=0 docker compose run --rm engdis
ED_UNITS=7,8,9 ED_SKIP=Apologize ED_DRY_RUN=0 docker compose run --rm engdis
ED_COURSE="Advanced 3" ED_UNIT=0 ED_DRY_RUN=0 docker compose run --rm engdis

# Host CLI
python3 cover.py 8-9 2
python3 cover.py 8-9 2 --skip=Apologize
python3 cover.py 0 1 --course="Advanced 3"
python3 cover.py 1 1 --course="Advanced 3" --lesson="IFL Broadcast"
python3 cover.py 1 1 --course="Advanced 3" --test-only
```

---

## Project Structure

```
├── config.py              # Centralized environment configuration and .env loader
├── cover.py               # Top-level supervisor and lesson batch runner
├── auto.py                # Task runner, stage detector, and DOM navigator
├── solver.py              # Multimodal LLM prompt builder and answer extractor
├── driver.py              # CDP connection, tab control, and network instrumentation
├── login.py               # Authentication handler and session recovery
├── asr.py                 # Audio extraction and base64 transcription client
├── poll.py                # Predicate polling and backoff utilities
├── bootstrap_browser.py   # Headless Chromium launcher with CDP health polling
├── compose.yaml           # Container definition with resource limits
├── Dockerfile             # Debian Bookworm container image with Chromium & FFmpeg
├── skills/
│   └── engdis-autopilot/  # Operational skill for AI coding agents
├── docs/                  # Detailed documentation
│   ├── architecture.md    # Container containment & execution models
│   ├── authentication.md  # Credential setup & secret mounting
│   ├── configuration.md   # Complete environment variable reference
│   └── dashboard.md       # Diagnostic dashboard setup
├── tools/
│   └── spikes/            # Archived exploratory spikes and reverse-engineering probes
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

Run unit tests locally or inside the container:

```bash
# Local test suite
python3 -m unittest discover tests

# Containerized test suite
docker run --rm --entrypoint python3 engdis-autopilot:test -m unittest discover tests
```

---

## Safety & License

- **Safety & Ethics**: Review [SAFETY.md](SAFETY.md) and [SECURITY.md](SECURITY.md) before use. Ensure compliance with institutional policies and platform terms.
- **License**: [MIT License](LICENSE) © 2026 Nguyễn Văn Trãi.
