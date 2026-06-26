"""Orchestrate: ingest -> vision-extract -> categorize -> risk-flag -> ledger."""
from __future__ import annotations

from pathlib import Path

from . import ingest, extract, categorize as categ, risk, ledger as ledger_mod
from .gmi_client import GMIClient
from .models import LineItem
from .respan import RespanMeter


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

    # 2. extract
    items: list[LineItem] = []
    for path, profile in docs:
        try:
            if profile == "spreadsheet":
                new = extract.extract_spreadsheet(path)
            else:
                new = extract.extract_image(client, path, profile)
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
    meter.write_report(out_dir / "respan_metrics.json")
    paths["respan_metrics"] = str(out_dir / "respan_metrics.json")

    log(f"[ledger] written -> {out_dir}")
    return {"ledger": ledger, "paths": paths, "respan": meter.summary()}
