# Engdis Autopilot Docker Harness

Isolated, reproducible container execution harness for `engdis-autopilot`.

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
| `ED_LLM_URL` | `http://100.85.59.117:20128/v1/chat/completions` | 9router LLM gateway endpoint |
| `NINEROUTER_API_KEY` | *(empty)* | Optional API token for LLM calls |
| `ED_CRED` | `/run/secrets/engdis_cred` | Path to credentials file (`username\npassword`) |
| `ED_SCRATCH` | `/data/cache` | Scratch directory for TTS audio and temp files |
| `ED_REPORT_DIR` | `/data/reports` | Directory where JSON run reports are written |

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
