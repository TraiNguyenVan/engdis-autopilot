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

- **Recommended Free Setup (Groq)**:
  - **Audio STT**: Set `GROQ_API_KEY=gsk_...` with model `whisper-large-v3-turbo`. Transcribes listening tests in ~0.5s at zero cost. Get free key at [console.groq.com/keys](https://console.groq.com/keys).
  - **Text reasoning**: Any OpenAI-compatible endpoint (e.g. Google AI Studio at [aistudio.google.com](https://aistudio.google.com/) or OpenRouter free models at [openrouter.ai/keys](https://openrouter.ai/keys)). Set `OPENAI_BASE_URL` and `OPENAI_MODEL` accordingly.
- **Multimodal LLM Fallback**: If `GROQ_API_KEY` is omitted, the harness falls back to sending base64 audio directly via `input_audio` chat completions to `OPENAI_MODEL` (e.g. Gemini 3.8 Flash via Google AI Studio at [aistudio.google.com](https://aistudio.google.com/)).
- **Fallback Chain**: Specify comma-separated model names (e.g. `primary-model,backup-model`). The runner automatically tries the next model if an API error occurs.

## Transcript cache and legacy migration

Media and transcripts in `ED_SCRATCH` use a SHA-256 key of the complete URL
(including query, excluding fragment). This keeps different paths, hosts and
query-selected media separate, without putting the URL or token in filenames.
A refreshed signed URL produces a different entry and may trigger another
transcription. Hashes are not encryption; protect the cache and logs.

Older `tr_<stem>.txt`, `tr_<filename>.txt`, `tr_<stem>_<ext>.txt` and
`m_<stem>...` files are left untouched but are not automatically trusted:
none proves which full URL it came from, even when an old media file exists.
To reuse a paid transcript, first independently verify its exact source URL,
then run Python locally with the same `ED_SCRATCH` as the runner:

```python
import solver
solver.migrate_legacy_transcript(verified_url, legacy_transcript_path)
```

Supply these variables interactively in a private environment; do not put signed
URLs or tokens in shell history, logs, or committed files. Migration copies the
text without deleting the original and refuses to overwrite an existing URL-keyed
entry. Migrating for a later changed token requires re-verification and another
migration. Incorrect provenance maps the wrong transcript; if uncertain, allow a
fresh download/transcription instead.

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
