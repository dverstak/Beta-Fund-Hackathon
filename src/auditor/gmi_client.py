"""GMI Cloud client (OpenAI-compatible) with Respan metering baked in.

All model traffic goes through here so every call is metered by profile. When a
RESPAN_API_KEY is set, every call is also logged to Respan's telemetry API.
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from . import config
from .respan import RespanMeter, RespanLogger

# Receipts/forms don't need full camera resolution to OCR. Downscaling the long
# edge to this before upload cuts payload size, vision tokens, and latency
# dramatically (a 5312px phone photo -> 1600px) with no accuracy loss.
_MAX_IMAGE_EDGE = 1600


def _encode_image(image_path: Path) -> tuple[str, str]:
    """Return (mime, base64). Downscale large images via Pillow when available;
    fall back to the raw bytes if Pillow is missing or the file isn't an image
    we can open."""
    raw = image_path.read_bytes()
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    try:
        from PIL import Image  # optional dependency
        with Image.open(io.BytesIO(raw)) as img:
            if max(img.size) <= _MAX_IMAGE_EDGE:
                return mime, base64.b64encode(raw).decode()
            img = img.convert("RGB")
            img.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return "image/jpeg", base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — never let preprocessing break extraction
        return mime, base64.b64encode(raw).decode()


class GMIClient:
    def __init__(self, meter: Optional[RespanMeter] = None):
        self.meter = meter or RespanMeter()
        # Inference always runs on GMI Cloud.
        self.client = OpenAI(api_key=config.require_gmi_key(),
                             base_url=config.GMI_BASE_URL)
        # Respan = observability layer (telemetry logging), not the inference path.
        if config.RESPAN_API_KEY and self.meter.logger is None:
            self.meter.logger = RespanLogger(
                config.RESPAN_API_KEY, config.RESPAN_BASE_URL,
                config.RESPAN_LOG_PATH)
        self.observability = "respan" if config.RESPAN_API_KEY else "local"

    # ---- low level ----
    def _chat(self, profile: str, model: str, messages: list,
              json_mode: bool = True, max_tokens: int = 2048) -> str:
        kwargs = dict(model=model, messages=messages, temperature=0,
                      max_tokens=max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        start = time.monotonic()
        resp = self.client.chat.completions.create(**kwargs)
        latency = time.monotonic() - start
        content = resp.choices[0].message.content or ""
        if getattr(resp, "usage", None):
            self.meter.track(profile, model, resp.usage, latency,
                             prompt_messages=messages, completion_text=content)
        return content

    # ---- vision: parse a receipt / 1099 image or PDF page ----
    def extract_from_image(self, profile: str, image_path: Path,
                           instruction: str, schema_hint: str) -> dict:
        mime, b64 = _encode_image(image_path)
        messages = [
            {"role": "system", "content":
                "You are a meticulous bookkeeping OCR/extraction engine. "
                "Read the document image and return STRICT JSON only."},
            {"role": "user", "content": [
                {"type": "text", "text": f"{instruction}\n\nReturn JSON shaped like:\n{schema_hint}"},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ]
        raw = self._chat(profile, config.VISION_MODEL, messages, json_mode=True)
        return _safe_json(raw)

    # ---- text reasoning: categorize / risk ----
    def reason_json(self, profile: str, system: str, user: str,
                    max_tokens: int = 2048) -> dict:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        raw = self._chat(profile, config.REASONING_MODEL, messages,
                          json_mode=True, max_tokens=max_tokens)
        return _safe_json(raw)


def _safe_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # salvage the outermost {...}
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(raw[s:e + 1])
            except json.JSONDecodeError:
                pass
        return {"_parse_error": True, "_raw": raw[:500]}
