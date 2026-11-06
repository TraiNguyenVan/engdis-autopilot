import os
from typing import List


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
SCRATCH: str = os.environ.get("ED_SCRATCH", "/opt/data/cache/scratch/ed22u1")
REPORT_DIR: str = os.environ.get("ED_REPORT_DIR", ".")
CRED_PATH: str = os.environ.get("ED_CRED", "/opt/data/.config/engdis/cred")
DRY_RUN: bool = _get_bool("ED_DRY_RUN", False)
CHROME_BIN: str = os.environ.get("CHROME_BIN", "chromium")

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
