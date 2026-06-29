"""Orchestrate: ingest -> vision-extract -> categorize -> risk-flag -> ledger."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ingest, extract, categorize as categ, risk, ledger as ledger_mod
from .gmi_client import GMIClient
from .models import LineItem
from .respan import RespanMeter

# Vision extraction is network-bound; run documents concurrently so a shoebox
# of receipts isn't a serial chain of round-trips.
_EXTRACT_WORKERS = 6


def run(input_path: Path, out_dir: Path, verbose: bool = True) -> dict:
    meter = RespanMeter()
    client = GMIClient(meter=meter)

    def log(msg: str):
        if verbose:
            print(msg, flush=True)

    # 1. ingest
    docs = ingest.discover(input_path)
    log(f"[ingest] {len(docs)} document(s) discovered "
        f"(inference: GMI Cloud | observability: {client.observability})")

    # 2. extract -- spreadsheets locally, images concurrently via GMI vision
    items: list[LineItem] = []

    def _extract_one(path: Path, profile: str) -> list[LineItem]:
        if profile == "spreadsheet":
            return extract.extract_spreadsheet(path)
        return extract.extract_image(client, path, profile)

    with ThreadPoolExecutor(max_workers=_EXTRACT_WORKERS) as pool:
        futures = {pool.submit(_extract_one, p, prof): (p, prof)
                   for p, prof in docs}
        for fut in futures:
            path, profile = futures[fut]
            try:
                new = fut.result()
                items.extend(new)
                log(f"[extract] {path.name} ({profile}) -> {len(new)} line item(s)")
            except Exception as e:  # noqa: BLE001 - keep batch resilient
                log(f"[extract] ERROR {path.name}: {e}")

    # 3. categorize (expenses)
    log(f"[categorize] mapping {sum(1 for i in items if i.kind=='expense')} "
        f"expense(s) to Schedule C lines")
    if items:
        categ.categorize(client, items)

    # 4. risk flagging
    risk.flag(items)
    log(f"[risk] {sum(1 for i in items if i.risk_level=='high')} high-risk, "
        f"{sum(1 for i in items if i.risk_level=='medium')} medium-risk")

    # 5. ledger
    ledger = ledger_mod.build(items)
    paths = ledger_mod.write_all(ledger, items, out_dir)
    # Drain background telemetry so logs_sent counts are accurate.
    meter.flush()
    meter.write_report(out_dir / "respan_metrics.json")
    paths["respan_metrics"] = str(out_dir / "respan_metrics.json")

    log(f"[ledger] written -> {out_dir}")
    return {"ledger": ledger, "paths": paths, "respan": meter.summary()}
