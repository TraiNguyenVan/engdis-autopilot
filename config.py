import os
from typing import List


def _load_dotenv(path: str = ".env") -> None:
    """Load key-value pairs from .env if present into os.environ without overwriting."""
    if os.environ.get("ED_SKIP_DOTENV") == "1":
        return
    candidates = [path, os.path.join(os.path.dirname(__file__), ".env"), os.path.join(os.path.dirname(__file__), "..", ".env")]
    target = next((p for p in candidates if os.path.exists(p)), None)
    if not target:
        return
    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv()


def _get_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    try:
        parsed = int(val)
        if parsed < 1 or parsed > 65535:
            raise ValueError(f"{key} must be between 1 and 65535, got {parsed}")
        return parsed
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {key}: {val}") from exc


def _get_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _build_chat_completions_url(base_or_full_url: str) -> str:
    url = base_or_full_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


CDP_PORT: int = _get_int("ED_CDP_PORT", 9225)
# Homelab container layout keeps the cache under /opt/data; a bare-metal clone
# keeps it inside the checkout so `solver.SCRATCH` is writable in both modes.
_SCRATCH_DEFAULT = (
    "/opt/data/cache/scratch/ed22u1"
    if os.path.isdir("/opt/data")
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "scratch")
)
SCRATCH: str = os.environ.get("ED_SCRATCH", _SCRATCH_DEFAULT)
REPORT_DIR: str = os.environ.get("ED_REPORT_DIR", ".")
CRED_PATH: str = os.environ.get("ED_CRED", "")
DRY_RUN: bool = _get_bool("ED_DRY_RUN", False)
CHROME_BIN: str = os.environ.get("CHROME_BIN", "chromium")
ED_COURSE: str = os.environ.get("ED_COURSE", "")

# OpenAI-compatible API Configuration
OPENAI_BASE_URL: str = (
    os.environ.get("OPENAI_BASE_URL")
    or os.environ.get("ED_LLM_URL")
    or "https://api.openai.com/v1"
)
OPENAI_API_KEY: str = (
    os.environ.get("OPENAI_API_KEY")
    or os.environ.get("NINEROUTER_API_KEY", "")
)
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL") or os.environ.get("ED_LLM_MODELS", "gpt-4o-mini")

LLM_URL: str = _build_chat_completions_url(OPENAI_BASE_URL)
LLM_KEY: str = OPENAI_API_KEY
LLM_MODELS: List[str] = [m.strip() for m in OPENAI_MODEL.split(",") if m.strip()]
LLM_TIMEOUT: int = _get_int("ED_LLM_TIMEOUT", 15)

# Groq Whisper STT Configuration
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL: str = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_WHISPER_MODEL: str = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
