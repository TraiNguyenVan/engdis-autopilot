# Configuration Reference

All parameters are configured via environment variables and can be supplied via a `.env` file (see `.env.example`):

## Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ED_COURSE` | *(empty)* | Course name, shorthand, or ID to select before running (e.g. `"Advanced 3"`, `a3`, `45742`). Defaults to currently active course. |
| `ED_UNIT` / `ED_UNITS` | `0` | Course unit(s) to process. Accepts single (`8`), range (`8-9`, `8..9`), list (`7,8,9`), or `all`. |
| `ED_PASSES` | `1` | Number of execution passes per unit (default: `1` in Docker, `2` on CLI) |
| `ED_DRY_RUN` | `1` | `1` or `true` for dry-run simulation mode |
| `ED_SKIP` | *(empty)* | Case-insensitive substring filter to skip matching lessons (e.g. `Apologize`, `Speech`) |
| `ED_CDP_PORT` | `9225` | Chrome remote debugging port |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint URL |
| `OPENAI_API_KEY` | *(empty)* | API key / token for LLM calls |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name (or comma-separated fallback chain) |
| `ED_CRED` | `/run/secrets/engdis_cred` | Path to credentials file (`username\npassword`) |
| `ED_SCRATCH` | `/data/cache` | Scratch directory for TTS audio and temp files |
| `ED_REPORT_DIR` | `/data/reports` | Directory where JSON run reports are written |

## LLM & Multimodal Audio Transcription

The harness uses a single OpenAI-compatible endpoint for both text reasoning and audio comprehension:

- **No external ASR keys needed**: No Groq, Whisper, or Deepgram API key required. Audio clips from listening exercises are base64-encoded and sent directly via standard `input_audio` chat completions.
- **Multimodal requirement**: For listening tasks, ensure `OPENAI_MODEL` points to a model with audio input support (e.g. Gemini 2.0/1.5 Flash via proxy, `gpt-4o-audio-preview`, or compatible OpenAI-like providers).
- **Fallback chain**: Specify comma-separated model names (e.g. `primary-model,backup-model`). The runner automatically tries the next model if an API error occurs.

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
ED_COURSE="Advanced 3" ED_UNIT=0 docker compose run --rm engdis
ED_COURSE="a3" ED_UNIT=0 docker compose run --rm engdis

# CLI flag (cover.py or cover_all.sh)
python3 cover.py 0 1 --course="Advanced 3"
python3 cover.py 0 1 --course=a3
python3 cover.py 0 1 --course=45742
```

Supported identifiers:
- Exact course title: `"Advanced 3"`, `"Basic 3"`, `"Intermediate 1"`
- Numeric Course ID: `45742`, `44205`
- Shorthand aliases: `a1`, `a2`, `a3`, `i1`, `i2`, `i3`, `b3`
- Case-insensitive substring match
