"""Respan-style observability: per-document-profile token & cost metering.

Respan is the sponsor LLM-engineering platform (observability + AI gateway).
When a RESPAN_API_KEY is configured, every GMI call is logged to Respan's
telemetry API tagged by document profile so spend is tracked centrally. We also
keep a local meter so the auditor can prove per-document cost-efficiency at high
volume -- the core value prop for batch tax auditing. Telemetry is sent off the
critical path (background threads) and never blocks or breaks the audit.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Approx blended USD price per 1M tokens for GMI-hosted models. Used for local
# cost estimation; Respan provides authoritative numbers when wired up.
_PRICE_PER_M = {
    "google/gemini-3-flash-preview": (0.10, 0.40),
    "Qwen/Qwen3.5-27B": (0.10, 0.30),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "_default": (0.20, 0.60),
}


@dataclass
class CallRecord:
    profile: str          # document profile: receipt | form_1099nec | spreadsheet | reasoning
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cost_usd: float


class RespanLogger:
    """Best-effort client for Respan's telemetry API (request-logs).

    Each LLM call is logged tagged with the document profile so Respan's
    dashboards break down token spend per profile. Failures never interrupt
    the audit (observability must not block the pipeline).
    """

    def __init__(self, api_key: str, base_url: str, log_path: str):
        self.url = base_url.rstrip("/") + log_path
        self.api_key = api_key
        self.enabled = bool(api_key)
        self.sent = 0
        self.errors = 0
        self._lock = threading.Lock()
        # Small pool so telemetry POSTs run off the audit's critical path.
        self._pool = ThreadPoolExecutor(max_workers=2) if self.enabled else None

    def log(self, *, profile: str, model: str, prompt_tokens: int,
            completion_tokens: int, cost: float, latency_s: float,
            prompt_messages: list, completion_text: str) -> None:
        if not self.enabled or self._pool is None:
            return
        payload = {
            "model": model,
            "prompt_messages": _redact(prompt_messages),
            "completion_message": {"role": "assistant", "content": completion_text[:2000]},
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost,
            "generation_time": round(latency_s, 3),
            "customer_identifier": profile,            # per-profile dimension
            "metadata": {"document_profile": profile, "app": "contractor-tax-auditor"},
        }
        # Fire-and-forget: submit and return immediately.
        self._pool.submit(self._send, json.dumps(payload).encode())

    def _send(self, data: bytes) -> None:
        req = urllib.request.Request(
            self.url, data=data, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            with self._lock:
                self.sent += 1
        except (urllib.error.URLError, TimeoutError, OSError):
            with self._lock:
                self.errors += 1

    def flush(self) -> None:
        """Wait for in-flight telemetry POSTs to finish (called once at end)."""
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None


def _redact(messages: list) -> list:
    """Strip base64 image payloads before shipping logs off-box."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for p in content:
                if p.get("type") == "image_url":
                    parts.append({"type": "image_url", "image_url": {"url": "<image redacted>"}})
                else:
                    parts.append(p)
            out.append({"role": m.get("role"), "content": parts})
        else:
            out.append({"role": m.get("role"), "content": content})
    return out


@dataclass
class RespanMeter:
    records: list[CallRecord] = field(default_factory=list)
    logger: Optional[RespanLogger] = None

    def _cost(self, model: str, pt: int, ct: int) -> float:
        pin, pout = _PRICE_PER_M.get(model, _PRICE_PER_M["_default"])
        return round(pt / 1e6 * pin + ct / 1e6 * pout, 6)

    def track(self, profile: str, model: str, usage, latency_s: float,
              prompt_messages: Optional[list] = None,
              completion_text: str = "") -> CallRecord:
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        rec = CallRecord(profile, model, pt, ct, round(latency_s, 3),
                         self._cost(model, pt, ct))
        self.records.append(rec)
        if self.logger and self.logger.enabled and prompt_messages is not None:
            self.logger.log(profile=profile, model=model, prompt_tokens=pt,
                            completion_tokens=ct, cost=rec.cost_usd,
                            latency_s=latency_s, prompt_messages=prompt_messages,
                            completion_text=completion_text)
        return rec

    def flush(self) -> None:
        """Block until queued telemetry has been delivered (for accurate
        logs_sent counts and to avoid losing logs at process exit)."""
        if self.logger is not None:
            self.logger.flush()

    # ---- aggregates ----
    def summary(self) -> dict:
        by_profile: dict[str, dict] = defaultdict(
            lambda: {"docs": 0, "prompt_tokens": 0, "completion_tokens": 0,
                     "cost_usd": 0.0, "latency_s": 0.0})
        for r in self.records:
            b = by_profile[r.profile]
            b["docs"] += 1
            b["prompt_tokens"] += r.prompt_tokens
            b["completion_tokens"] += r.completion_tokens
            b["cost_usd"] = round(b["cost_usd"] + r.cost_usd, 6)
            b["latency_s"] = round(b["latency_s"] + r.latency_s, 3)
        total_tokens = sum(r.prompt_tokens + r.completion_tokens for r in self.records)
        total_cost = round(sum(r.cost_usd for r in self.records), 6)
        return {
            "calls": len(self.records),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_cost_per_call_usd": round(total_cost / len(self.records), 6)
            if self.records else 0.0,
            "respan_telemetry": {
                "enabled": bool(self.logger and self.logger.enabled),
                "logs_sent": self.logger.sent if self.logger else 0,
                "log_errors": self.logger.errors if self.logger else 0,
            },
            "by_profile": dict(by_profile),
        }

    def write_report(self, path: Path) -> None:
        path.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")


def timed():
    """Return a monotonic start timestamp for latency measurement."""
    return time.monotonic()
