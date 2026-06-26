"""Configuration and lightweight .env loader (no external deps)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    """Minimal .env loader so we don't depend on python-dotenv."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env()

# --- GMI Cloud (OpenAI-compatible inference) ---
GMI_API_KEY = os.environ.get("GMI_API_KEY", "")
GMI_BASE_URL = os.environ.get("GMI_BASE_URL", "https://api.gmi-serving.com/v1")

# Multimodal model for parsing chaotic receipts / 1099 scans.
VISION_MODEL = os.environ.get("GMI_VISION_MODEL", "google/gemini-3-flash-preview")
# Text model for Schedule C reasoning / categorization.
REASONING_MODEL = os.environ.get("GMI_REASONING_MODEL", "Qwen/Qwen3.5-27B")

# --- Respan (observability) ---
# Inference always runs on GMI; when a Respan key is present, every call is
# additionally logged to Respan's telemetry API (request-logs) tagged by
# document profile, so token/cost is monitored centrally. Local metering
# always runs regardless.
RESPAN_API_KEY = os.environ.get("RESPAN_API_KEY", "")
RESPAN_BASE_URL = os.environ.get("RESPAN_BASE_URL", "https://api.respan.ai/api")
RESPAN_LOG_PATH = os.environ.get("RESPAN_LOG_PATH", "/request-logs/create/")

# Tax year under audit.
TAX_YEAR = int(os.environ.get("TAX_YEAR", "2025"))


def require_gmi_key() -> str:
    if not GMI_API_KEY:
        raise RuntimeError(
            "GMI_API_KEY is not set. Add it to .env (see README)."
        )
    return GMI_API_KEY
