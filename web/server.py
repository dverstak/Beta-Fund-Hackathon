"""FastAPI server for the Contractor Tax & Deduction Auditor UI.

Run:
    pip install -r web/requirements-web.txt
    python -m web.server            # or: uvicorn web.server:app --reload
    open http://127.0.0.1:8000

Endpoints
    GET  /                 -> the dashboard (static SPA)
    GET  /api/health       -> {status, backend_available}
    GET  /api/ledger       -> latest ledger on disk
    POST /api/audit        -> upload files (multipart), run the audit, return ledger
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import adapter, auth

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"
_ROOT = _HERE.parent

app = FastAPI(title="Contractor Tax & Deduction Auditor")


@app.get("/api/health")
def health():
    return {"status": "ok", "backend_available": adapter.backend_available()}


@app.get("/api/clerk-config")
def clerk_config():
    """Public: non-secret values the browser needs to boot Clerk JS."""
    return auth.public_config()


@app.get("/api/ledger")
def get_ledger(user_id: str = Depends(auth.require_user)):
    data = adapter.latest_ledger()
    if data is None:
        return JSONResponse({"error": "no ledger found"}, status_code=404)
    return data


@app.post("/api/audit")
async def post_audit(
    files: list[UploadFile] = File(default=[]),
    user_id: str = Depends(auth.require_user),
):
    """Accept uploaded documents, run the audit, return the ledger."""
    with tempfile.TemporaryDirectory(prefix="shoebox_") as tmp:
        in_dir = Path(tmp) / "in"
        out_dir = Path(tmp) / "out"
        in_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            dest = in_dir / Path(f.filename).name
            dest.write_bytes(await f.read())

        # No files uploaded -> demo against the bundled sample data folder.
        target = in_dir if any(in_dir.iterdir()) else (_ROOT / "data")
        # The audit pipeline is a long, blocking (network) call. Run it in a
        # worker thread so the single uvicorn event loop stays responsive --
        # otherwise the page, static assets, and /api/health all freeze while
        # an audit is in flight.
        result = await run_in_threadpool(adapter.run_audit, target, out_dir)
    return result


# Static SPA last so /api/* wins.
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
def index():
    # Served to everyone; the browser-side Clerk gate (clerk-gate.js) redirects
    # signed-out visitors to the hosted sign-in page and only then boots the app.
    return FileResponse(str(_STATIC / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
