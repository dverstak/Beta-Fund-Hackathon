"""FastAPI server for the Contractor Tax & Deduction Auditor UI.

Run:
    pip install -r web/requirements-web.txt
    python -m web.server            # binds 0.0.0.0:8080 (override with PORT/HOST)
    open http://127.0.0.1:8080

Endpoints
    GET  /                  -> the dashboard (static SPA)
    GET  /api/health        -> {status, backend_available}
    GET  /api/ledger        -> latest ledger on disk
    POST /api/jobs          -> upload files, returns 202 {job_id} (async pattern)
    GET  /api/jobs/{id}     -> job status + result when done
    POST /api/audit         -> synchronous audit (CLI/curl convenience; may 504
                               behind a gateway for large inputs -- prefer /api/jobs)

The async job pattern (POST /api/jobs + poll GET /api/jobs/{id}) exists because
HTTP gateways (including GMI AgentBox) close long-open connections with a 504.
An audit can take 30-120s, so the UI submits a job and polls instead of holding
the request open. Job state is in-process: fine for a single container; use an
external store (Redis/DB) if you scale to multiple replicas.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import adapter

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"
_ROOT = _HERE.parent

app = FastAPI(title="Contractor Tax & Deduction Auditor")

# ── in-process job registry ───────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_jobs_order: deque[str] = deque()
_MAX_JOBS = 100                       # cap memory; prune oldest
_executor = ThreadPoolExecutor(max_workers=4)


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _new_job() -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending"}
        _jobs_order.append(job_id)
        while len(_jobs_order) > _MAX_JOBS:
            _jobs.pop(_jobs_order.popleft(), None)
    return job_id


def _run_job(job_id: str, target: Path, out_dir: Path, cleanup: Path | None) -> None:
    try:
        _set_job(job_id, status="running")
        result = adapter.run_audit(target, out_dir)
        _set_job(job_id, status="done", result=result)
    except Exception as exc:  # noqa: BLE001 — surface to the poller, never crash the worker
        _set_job(job_id, status="error", error=str(exc))
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)


async def _stage_upload(files: list[UploadFile]) -> tuple[Path, Path, Path | None]:
    """Persist uploads to a temp dir that outlives the request (job runs later)."""
    tmp = Path(tempfile.mkdtemp(prefix="shoebox_"))
    in_dir = tmp / "in"
    out_dir = tmp / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        if f.filename:
            (in_dir / Path(f.filename).name).write_bytes(await f.read())
    # No files uploaded -> demo against the bundled sample data folder.
    target = in_dir if any(in_dir.iterdir()) else (_ROOT / "data")
    return target, out_dir, tmp


@app.get("/api/health")
def health():
    return {"status": "ok", "backend_available": adapter.backend_available()}


@app.get("/api/ledger")
def get_ledger():
    data = adapter.latest_ledger()
    if data is None:
        return JSONResponse({"error": "no ledger found"}, status_code=404)
    return data


@app.post("/api/jobs", status_code=202)
async def create_job(files: list[UploadFile] = File(default=[])):
    """Async pattern: accept the upload, start the audit, return a job id."""
    target, out_dir, cleanup = await _stage_upload(files)
    job_id = _new_job()
    _executor.submit(_run_job, job_id, target, out_dir, cleanup)
    return {"job_id": job_id, "status": "pending",
            "status_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        snapshot = dict(job) if job else None
    if snapshot is None:
        return JSONResponse({"error": "unknown job_id"}, status_code=404)
    out = {"job_id": job_id, "status": snapshot["status"]}
    if snapshot["status"] == "done":
        out["result"] = snapshot["result"]
    elif snapshot["status"] == "error":
        out["error"] = snapshot["error"]
    return out


@app.post("/api/audit")
async def post_audit(files: list[UploadFile] = File(default=[])):
    """Synchronous audit (CLI/curl convenience). Prefer /api/jobs behind a
    gateway -- this holds the connection open and can hit a 504 on big inputs."""
    target, out_dir, cleanup = await _stage_upload(files)
    try:
        return await run_in_threadpool(adapter.run_audit, target, out_dir)
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)


# Static SPA last so /api/* wins.
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(str(_STATIC / "index.html"))


if __name__ == "__main__":
    import os
    import uvicorn

    # 0.0.0.0 so the container is reachable; AgentBox maps external 443 ->
    # internal 8080. proxy_headers/forwarded-allow-ips so the app trusts the
    # gateway's X-Forwarded-* (correct scheme/host in any redirects).
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port,
                proxy_headers=True, forwarded_allow_ips="*")
