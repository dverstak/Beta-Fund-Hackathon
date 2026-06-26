"""Vercel Python serverless entrypoint.

Vercel's @vercel/python runtime serves the module-level `app` ASGI object.
We just re-export the existing FastAPI app from `web/server.py` so the
deployed app is identical to `python -m web.server` locally.

All routes (static UI + /api/*) are rewritten to this function by vercel.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project root (for `web`) and `src` (for `auditor`) importable.
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from web.server import app  # noqa: E402  (path setup must run first)

# `app` is what Vercel invokes.
__all__ = ["app"]
