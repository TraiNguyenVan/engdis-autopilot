# Engdis Autopilot Docker Harness

Isolated, reproducible container execution harness for `engdis-autopilot`.

> **Recommended**: Use the **Docker setup**. Running directly on host requires matching Chromium binaries, FFmpeg, audio codecs, and specific fonts. The Docker image packages the entire runtime with pre-configured headless browser management, unprivileged security isolation, and strict RAM limits.

## Architecture & Resource Limits

- **Base Image**: `python:3.11-slim-bookworm` with Chromium, FFmpeg, curl, procps.
- **Security**: Runs as unprivileged user `engdis` (UID `1000:1000`).
- **Memory Limits**: Shipped with tight resource controls to protect low-RAM host environments:
  - Container RAM limit: `1280M` (`mem_limit: 1280m`, reservation `512m`)
  - Shared memory: `shm_size: 256m`
  - Chromium internal limits: `--js-flags=--max-old-space-size=768 --renderer-process-limit=2`
- **Isolation**: Runs an internal headless Chromium instance with automatic lock cleanup and CDP readiness polling.

## Configuration Parameters

All parameters are configured via environment variables (defined in `config.py`):

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ED_UNIT` | `0` | Course unit to process (`0` for all units) |
| `ED_PASSES` | `1` | Number of execution passes |
| `ED_DRY_RUN` | `1` | `1` or `true` for dry-run simulation mode |
| `ED_CDP_PORT` | `9225` | Chrome remote debugging port |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint URL |
| `OPENAI_API_KEY` | *(empty)* | API key / token for LLM calls |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name (or comma-separated list) |
| `ED_CRED` | `/run/secrets/engdis_cred` | Path to credentials file (`username\npassword`) |
| `ED_SCRATCH` | `/data/cache` | Scratch directory for TTS audio and temp files |
| `ED_REPORT_DIR` | `/data/reports` | Directory where JSON run reports are written |

## Execution Architecture: Unattended vs. Progressive Patching

The system supports two distinct operating models:

### 1. Unattended Execution (Standalone / Headless)

- **Mechanics**: Runs autonomously via the supervisor (`cover.py`) and task solver (`auto.py`). The runner navigates lessons, identifies known exercise types, executes interactions via Chrome DevTools Protocol (CDP), and logs progress.
- **Fault Tolerance**: When an unhandled interaction pattern or unresponsive widget is encountered, the per-lesson watchdog terminates the stalled worker with a timeout (`rc=-9`), logs the failure, and proceeds to the next lesson. Subsequent passes retry incomplete lessons.
- **Portability**: Fully functional on any standard Docker host, VM, or CI/CD environment with internet access, Chromium, FFmpeg, and an OpenAI-compatible LLM endpoint. No external supervisor or coding agent is required.

### 2. Progressive Patching (Operator-in-the-Loop)

- **Nature**: Progressive patching is **not** an internal auto-modifying heuristic. It is a human-or-agent-in-the-loop iterative development workflow.
- **Diagnostics**: When tasks stall or fail, `diag_logger.py` writes structured JSONL events (`logs_diag/events.jsonl`) and persists point-of-failure DOM snapshots and screenshots (`logs_diag/evidence/`). The optional diagnostic dashboard (`dashboard_server.py`) surfaces live status, recent events, and on-demand browser screenshots.
- **Patch Cycle**: An external operator (a developer or an interactive coding agent with workspace access) monitors the diagnostic stream, diagnoses the failing DOM structure or event sequence, applies targeted patches to `solver.py` or `auto.py`, and allows the supervisor's next pass to execute the corrected logic.
- **Environment Dependency**: On environments without an active operator or interactive coding agent, the harness operates strictly in **Unattended Execution** mode—gracefully bypassing edge cases via timeouts rather than self-modifying code.

## LLM & Audio Transcription

The harness uses a unified OpenAI-compatible endpoint for both text problem solving and audio transcription:

- **No separate speech-to-text API required**: You do **not** need a Groq, Whisper, or Deepgram API key. Audio clips from listening exercises are base64-encoded and sent directly via `input_audio` chat completions.
- **Model requirements**: For units containing listening comprehension tasks, set `OPENAI_MODEL` to a multimodal model that accepts audio input (e.g. Gemini 2.0/1.5 Flash via proxy, `gpt-4o-audio-preview`, or any OpenAI-compatible provider supporting audio).
- **Fallback chain**: `OPENAI_MODEL` supports comma-separated models (e.g. `primary-model,backup-model`). The solver automatically falls back to subsequent models if an API call fails.

## Authentication & Credentials Setup

The harness supports two ways to provide course login credentials:

### Option A: Credentials File (Recommended)

Create a 2-line file containing your username and password:

```bash
mkdir -p ~/.config/engdis
cat << 'EOF' > ~/.config/engdis/cred
your_student_id_or_username
your_password
EOF
chmod 600 ~/.config/engdis/cred
```

Point `ED_CRED` to this file path if using a custom location:
```bash
export ED_CRED="$HOME/.config/engdis/cred"
```

### Option B: Environment Variables

Set credentials directly in your environment:

```bash
export ED_USER="your_student_id_or_username"
export ED_PASS="your_password"
```

In Docker Compose, mount your credentials file into `/run/secrets/engdis_cred` or pass `ED_CRED_FILE=/path/to/cred`.

## Quickstart

### 1. Build Image

```bash
docker compose build
```

### 2. Run Single Unit (Dry Run)

```bash
ED_UNIT=5 ED_PASSES=1 ED_DRY_RUN=1 docker compose run --rm engdis
```

### 3. Run Live Execution

```bash
ED_UNIT=5 ED_PASSES=1 ED_DRY_RUN=0 docker compose run --rm engdis
```

### 4. Running with Standalone Docker

```bash
docker run --rm -it \
  --memory 1280m \
  --shm-size 256m \
  -e ED_UNIT=5 \
  -e ED_PASSES=1 \
  -e ED_DRY_RUN=1 \
  -v /path/to/cred:/run/secrets/engdis_cred:ro \
  -v engdis_data:/data \
  engdis-autopilot:test
```

## Running Tests

Run the test suite locally or inside container:

```bash
# Inside worktree
python3 -m unittest discover tests

# Inside container
docker run --rm --entrypoint python3 engdis-autopilot:test -m unittest discover tests
```

## Safety & Ethics

Please review [SAFETY.md](SAFETY.md) and [SECURITY.md](SECURITY.md) before deploying. This tool is designed for educational accessibility, CDP instrumentation research, and automated courseware regression testing. Ensure compliance with your institution's honor code and terms of service.

## License

[MIT License](LICENSE) © 2026 Nguyễn Văn Trãi
