# Configuration Reference

All parameters are configured via environment variables and can be supplied via a `.env` file (see `.env.example`):

## Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `ED_UNIT` | `0` | Course unit to process (`0` for all units) |
| `ED_PASSES` | `1` | Number of execution passes |
| `ED_DRY_RUN` | `1` | `1` or `true` for dry-run simulation mode |
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
