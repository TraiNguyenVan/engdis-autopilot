# Configuration Reference

All parameters are configured via environment variables and can be supplied via a `.env` file (see `.env.example`):

## Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ED_USER` | *(empty)* | LMS student username/ID. Top priority auth method. |
| `ED_PASS` | *(empty)* | LMS password. |
| `OPENAI_API_KEY` | *(empty)* | API key / token for LLM reasoning and multimodal tasks. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint URL. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name (or comma-separated fallback chain). |
| `ED_COURSE` | *(empty)* | Course name, shorthand, or ID to select before running (e.g. `a3`, `45742`). Defaults to currently active course. |
| `ED_UNIT` / `ED_UNITS` | `0` | Course unit(s) to process. Accepts single (`8`), range (`8-9`, `8..9`), list (`7,8,9`), or `all`. |
| `ED_PASSES` | `1` | Number of execution passes per unit (default: `1` in Docker, `2` on CLI) |
| `ED_DRY_RUN` | `1` | `1` or `true` for dry-run simulation mode |
| `ED_SKIP` | *(empty)* | Case-insensitive substring filter to skip matching lessons (e.g. `Apologize`, `Speech`) |
| `ED_CDP_PORT` | `9225` | Chrome remote debugging port |
| `ED_CRED` | *(empty)* | Optional path to credentials file (`username\npassword`). Alternative to `ED_USER`/`ED_PASS`. |
| `ED_SCRATCH` | `/data/cache` | Scratch directory for TTS audio and temp files |
| `ED_REPORT_DIR` | `/data/reports` | Directory where JSON run reports are written |

## LLM & Multimodal Audio Transcription

The harness uses an OpenAI-compatible endpoint for text reasoning, with optional dedicated Groq Whisper for audio transcription:

- **Recommended Free Setup (AnyRouter + Groq)**:
  - **Reasoning**: Set `OPENAI_BASE_URL=https://anyrouter.dev/api/v1` and `OPENAI_MODEL=anyrouter/free`. Get free key at [anyrouter.dev/keys](https://anyrouter.dev/keys).
  - **Audio STT**: Set `GROQ_API_KEY=gsk_...` with model `whisper-large-v3-turbo`. Transcribes listening tests in ~0.5s at zero cost. Get free key at [console.groq.com/keys](https://console.groq.com/keys).
- **Multimodal LLM Fallback**: If `GROQ_API_KEY` is omitted, the harness falls back to sending base64 audio directly via `input_audio` chat completions to `OPENAI_MODEL` (e.g. Gemini 2.0 Flash via Google AI Studio at [aistudio.google.com](https://aistudio.google.com/)).
- **Fallback Chain**: Specify comma-separated model names (e.g. `primary-model,backup-model`). The runner automatically tries the next model if an API error occurs.

## Local Configuration (`.env`)

Copy `.env.example` to `.env` to override settings locally without editing code:

```bash
cp .env.example .env
```

`config.py` automatically loads `.env` on startup when present. `.env` is ignored by Git.

## Course Selection

Select target course via environment variable, Docker Compose, or CLI:

```bash
# Environment variable / Docker Compose
ED_COURSE="<COURSE>" ED_UNIT=<UNIT_IDX> docker compose run --rm engdis

# Development container (engdis_inspect)
docker exec engdis_inspect python3 cover.py 0 1 --course="<COURSE>"
docker exec engdis_inspect python3 cover.py 0 1 --course=a3
docker exec engdis_inspect python3 cover.py 0 1 --course=45742
```

Supported identifiers:
- Exact course title: `"Advanced 3"`, `"Basic 3"`, `"Intermediate 1"`
- Numeric Course ID: `45742`, `44205`
- Shorthand aliases: `a1`, `a2`, `a3`, `i1`, `i2`, `i3`, `b3`
- Case-insensitive substring match
