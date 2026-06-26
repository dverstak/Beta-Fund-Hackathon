# ShoeboxIQ — Frontend / Web UI

The dashboard for the Independent Contractor Tax & Deduction Auditor.
Drag in a "digital shoebox" (1099-NEC forms, receipt photos, bank CSVs) →
get an audit-ready Schedule C ledger, audit-risk review, and an
estimated self-employment tax.

## Run it

```bash
pip install -r web/requirements-web.txt
python -m web.server          # http://127.0.0.1:8000
```

The UI **works immediately**, even before the backend is wired up: with no
GMI key / backend deps installed it renders the last real ledger
(`audit_out/ledger.json`) or the bundled `web/sample_ledger.json`. Click
**"Use sample shoebox"** for an instant demo.

> For pure static hosting (no Python), the frontend falls back to
> `web/static/sample_ledger.json` + `sample_respan.json`, so you can also just
> open `web/static/index.html` through any static server.

## The integration boundary  ← backend teammate reads this

There is exactly **one** seam: [`web/adapter.py`](adapter.py).

```python
run_audit(input_dir: Path, out_dir: Path) -> dict
```

It already calls the real pipeline:

```python
from auditor.pipeline import run as pipeline_run
result = pipeline_run(input_dir, out_dir)   # your code
```

When the backend becomes importable (deps installed + `GMI_API_KEY` set),
`/api/audit` automatically returns `source: "live"`. **Nothing in the frontend
changes.** If the import or a call fails, it falls back to the last ledger so a
live demo never breaks.

### The data contract (keep this stable)

`run_audit` returns `{ "ledger", "respan", "paths", "source" }`, where `ledger`
is exactly what `auditor.ledger.build()` already produces:

```jsonc
{
  "tax_year": 2025,
  "summary": {
    "gross_receipts": 51250.0,
    "total_expenses_claimed": 6024.83,
    "total_deductible": 5242.08,
    "estimated_net_profit_schedule_c": 46007.92,
    "flagged_items": 8, "high_risk_items": 6
  },
  "schedule_c_lines": {
    "Line 24a": { "label": "Travel", "count": 2, "claimed": 800.4, "deductible": 800.4 }
  },
  "line_items": [ /* LineItem.to_dict(): vendor, date, amount, kind,
                     schedule_c_line, deductible_pct, deductible_amount,
                     confidence, rationale, risk_level, flags[], raw{} */ ]
}
```

The Schedule SE (self-employment tax) figure is computed in the frontend from
`estimated_net_profit_schedule_c` (deterministic IRS formula) — no backend
field required, but feel free to add one and the UI will prefer it later.

## Endpoints

| Method | Path           | Purpose                                   |
|--------|----------------|-------------------------------------------|
| GET    | `/`            | The dashboard (SPA)                        |
| GET    | `/api/health`  | `{status, backend_available}`              |
| GET    | `/api/ledger`  | Latest ledger on disk                      |
| POST   | `/api/audit`   | Multipart upload → run audit → ledger JSON |

`POST /api/audit` with **no files** runs against the bundled `data/` sample
folder — handy for demos.

## Files

```
web/
  server.py            FastAPI app (static SPA + JSON API)
  adapter.py           ← the only backend integration point
  requirements-web.txt
  sample_ledger.json   offline demo data
  static/
    index.html         layout
    styles.css         theme
    app.js             render + interactions (pure vanilla JS, no build step)
```
