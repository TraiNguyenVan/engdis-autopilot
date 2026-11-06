# Engdis Autopilot

Automated browser testing and exercise solver harness for English Discoveries courseware via Chrome DevTools Protocol (CDP) and multimodal LLMs.

> **Recommended**: Use the **Docker setup**. Running directly on the host requires matching Chromium binaries, FFmpeg, audio codecs, and fonts. The container packages the complete runtime with memory limits and process management out of the box.

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

Run via Docker Compose (recommended) or host CLI:

#### Docker Compose
```bash
# Dry run (simulation only, no task mutations)
ED_UNIT=8-9 ED_PASSES=1 ED_DRY_RUN=1 docker compose run --rm engdis

# Live execution for a single unit or multi-unit range
ED_UNIT=8 ED_PASSES=2 ED_DRY_RUN=0 docker compose run --rm engdis
ED_UNIT=8-9 ED_PASSES=1 ED_DRY_RUN=0 docker compose run --rm engdis
ED_UNITS=7,8,9 ED_DRY_RUN=0 docker compose run --rm engdis
ED_UNIT=all ED_DRY_RUN=0 docker compose run --rm engdis

# Optional: skip specific lessons (e.g. speech tasks)
ED_UNIT=7 ED_SKIP=Apologize ED_DRY_RUN=0 docker compose run --rm engdis
```

#### Host CLI
```bash
# Unit specifications support ranges (8-9, 8..9), lists (7,8,9), 'all', or single numbers (0-indexed)
python3 cover.py 8-9 2
python3 cover.py 8-9 2 --skip=Apologize
python3 cover.py all 1 --dry

# Or via shell wrapper
./cover_all.sh 8-9 2
./cover_all.sh 8 9 2
```

---

## Unit Index Reference

Course units are 0-indexed:

| Index | Unit Name | Typical Gating / Notes |
| :---: | :--- | :--- |
| `0` | Unit 1: Telling The Truth | Core foundation |
| `1` | Unit 2: Business Careers | Drag & drop ordering |
| `2` | Unit 3: Agreeing And Disagreeing | Listening & grammar |
| `3` | Unit 4: Too Much Work | Sequence matching |
| `4` | Unit 5: People With Problems | Logical connectors |
| `5` | Unit 6: Tell Me About it | Request & review |
| `6` | Unit 7: Economics | Adjectives & finance |
| `7` | Unit 8: Interviews | Career & writing tasks |
| `8` | Unit 9: Artificial Intelligence | AI reading & comprehension |
| `9` | Unit 10: Space Exploration | Exploration reading & test |

---

## Project Structure

```
├── config.py              # Centralized environment configuration and .env loader
├── cover.py               # Top-level supervisor and lesson batch runner
├── auto.py                # Task runner, stage detector, and DOM navigator
├── solver.py              # Multimodal LLM prompt builder and answer extractor
├── driver.py              # CDP connection, tab control, and network instrumentation
├── login.py               # Authentication handler and session recovery
├── tr.py / asr.py         # Audio extraction and base64 transcription client
├── bootstrap_browser.py   # Headless Chromium launcher with CDP health polling
├── compose.yaml           # Container definition with resource limits
├── Dockerfile             # Debian Bookworm container image with Chromium & FFmpeg
├── docs/                  # Detailed documentation
│   ├── architecture.md    # Container containment & execution models
│   ├── authentication.md  # Credential setup & secret mounting
│   ├── configuration.md   # Complete environment variable reference
│   └── dashboard.md       # Diagnostic dashboard setup
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
