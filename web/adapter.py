"""Integration seam between the web UI and the audit backend.

╔══════════════════════════════════════════════════════════════════════════╗
║  THIS IS THE ONE FILE THE BACKEND TEAMMATE NEEDS TO TOUCH.                ║
║                                                                          ║
║  `run_audit()` already calls the real pipeline (`auditor.pipeline.run`). ║
║  If the backend isn't importable / no GMI key is set, it transparently   ║
║  falls back to the last-known ledger so the frontend is always demoable. ║
║  When the backend is ready, nothing here has to change.                  ║
╚══════════════════════════════════════════════════════════════════════════╝

Contract (what the UI consumes — keep this stable):

    run_audit(input_dir: Path, out_dir: Path) -> dict
        returns {"ledger": <dict>, "respan": <dict>, "paths": <dict>, "source": str}

    where `ledger` matches `auditor.ledger.build()`:
        {
          "tax_year": int,
          "summary": {gross_receipts, total_deductible,
                      estimated_net_profit_schedule_c, ...},
          "schedule_c_lines": {"Line 24a": {label, count, claimed, deductible}, ...},
          "line_items": [ <LineItem.to_dict()>, ... ],
        }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# Make `src/` importable so we can call the real pipeline directly.
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Fallback ledgers the UI can render with zero backend wired up.
_FALLBACK_LEDGERS = [
    _ROOT / "audit_out" / "ledger.json",   # last real run
    _ROOT / "web" / "sample_ledger.json",  # bundled demo
]


def backend_available() -> bool:
    """True if the real audit pipeline can be imported."""
    try:
        import auditor.pipeline  # noqa: F401
        return True
    except Exception:
        return False


def run_audit(input_dir: Path, out_dir: Path) -> dict:
    """Run the audit on a folder of documents.

    Tries the real backend first; on any failure, returns the most recent
    ledger so the UI never breaks during a live demo.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from auditor.pipeline import run as pipeline_run
        result = pipeline_run(input_dir, out_dir, verbose=False)
        return {
            "ledger": result["ledger"],
            "respan": result.get("respan", {}),
            "paths": result.get("paths", {}),
            "source": "live",
        }
    except Exception as exc:  # noqa: BLE001 — demo must keep working
        fallback = _load_fallback()
        if fallback is None:
            raise
        fallback["source"] = "fallback"
        fallback["fallback_reason"] = str(exc)
        return fallback


def latest_ledger() -> Optional[dict]:
    """Return the most recent ledger on disk (for GET /api/ledger)."""
    return _load_fallback()


def _load_fallback() -> Optional[dict]:
    for path in _FALLBACK_LEDGERS:
        if path.exists():
            ledger = json.loads(path.read_text(encoding="utf-8"))
            respan = {}
            respan_path = path.parent / "respan_metrics.json"
            if respan_path.exists():
                respan = json.loads(respan_path.read_text(encoding="utf-8"))
            return {"ledger": ledger, "respan": respan, "paths": {}, "source": "fallback"}
    return None
