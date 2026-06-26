# Deploying Audit AI to Vercel

The app is configured to run on Vercel's Python runtime: the FastAPI app in
[web/server.py](web/server.py) is exposed as a serverless function via
[api/index.py](api/index.py), and every route (static UI + `/api/*`) is rewritten
to it by [vercel.json](vercel.json).

## One-time setup

```bash
npm i -g vercel        # install the CLI
vercel login           # opens a browser to authenticate YOUR Vercel account
```

## Set the secrets (do NOT commit keys)

```bash
vercel link            # link this folder to a Vercel project (first time)
vercel env add GMI_API_KEY production        # paste your GMI Cloud key
# optional:
vercel env add RESPAN_API_KEY production      # enables Respan telemetry logging
vercel env add GMI_VISION_MODEL production     # default google/gemini-3-flash-preview
vercel env add GMI_REASONING_MODEL production  # default Qwen/Qwen3.5-27B
vercel env add TAX_YEAR production             # default 2025
```

(Or set them in the Vercel dashboard → Project → Settings → Environment Variables.)

## Deploy

```bash
vercel              # preview deployment -> unique URL
vercel --prod       # promote to production
```

## What works, and the one caveat

- **Static UI**: served from the function; the dashboard loads instantly and,
  if a live audit fails or no key is set, falls back to the bundled sample
  ledger — so the deployed site is always demoable.
- **`GET /api/health`, `/api/ledger`, exports**: fast, no issue.
- **`POST /api/audit` (live audit)** is the one to watch. Each receipt/1099
  vision call + the Schedule C reasoning call can take ~60–80s
  (see [audit_out/respan_metrics.json](audit_out/respan_metrics.json)). Vercel
  function limits:
  - **Hobby**: 60s max (`maxDuration` in `vercel.json` is set to 60). A
    multi-document shoebox will likely **time out**.
  - **Pro**: raise `maxDuration` to up to `300` and it comfortably handles
    small/medium batches.

  > If you need to audit large shoeboxes reliably, the right fix is to make the
  > audit asynchronous (kick off a job, poll for the ledger) rather than running
  > it inside one request — serverless isn't built for long blocking calls.
  > For a hackathon demo, run small inputs or lean on the sample fallback.

## Bundle notes

- `vercel.json` `includeFiles` bundles `web/`, `src/`, `data/`, and `audit_out/`
  so the function can serve the UI, import `auditor`, run the sample-data demo,
  and read the fallback ledger.
- Python deps come from the root [requirements.txt](requirements.txt) (Vercel
  installs it automatically). `uvicorn`/`pillow` are local-only and unused on
  Vercel.
