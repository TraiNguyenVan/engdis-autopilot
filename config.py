import os

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

CDP_PORT: int = _get_int("ED_CDP_PORT", 9225)
LLM_URL: str = os.environ.get("ED_LLM_URL", "http://100.85.59.117:20128/v1/chat/completions")
SCRATCH: str = os.environ.get("ED_SCRATCH", "/opt/data/cache/scratch/ed22u1")
REPORT_DIR: str = os.environ.get("ED_REPORT_DIR", ".")
CRED_PATH: str = os.environ.get("ED_CRED", "/opt/data/.config/engdis/cred")
DRY_RUN: bool = _get_bool("ED_DRY_RUN", False)
CHROME_BIN: str = os.environ.get("CHROME_BIN", "chromium")
