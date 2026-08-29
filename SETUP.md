# Setup — quick reference

## 1. Extraction pipeline (local)

```bash
# One-time: Python 3.12+ venv (macOS: brew install python@3.12 if needed)
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt

# API key — export it yourself each session, never paste it into chat:
export ANTHROPIC_API_KEY="sk-ant-..."

# Run extraction (skips already-processed files via po_data.db content-hash cache)
.venv312/bin/python extract_pos.py --input files --output gpc_po_data.xlsx --db po_data.db --workers 5

# If it pauses with "out of API credits" (exit code 3): add credits, rerun the
# exact same command — already-done files are skipped automatically.

# Retry only files that errored:
.venv312/bin/python extract_pos.py --input files --output gpc_po_data.xlsx --retry-failed gpc_po_data_failed.txt --workers 1
```

## 2. Dashboard (hosted Postgres + FastAPI + React)

> The Streamlit dashboard was retired. The app is now a FastAPI backend (`backend/`)
> + a React SPA (`web/`) on Supabase Postgres. **Provisioning + deploy:
> [`docs/REBUILD-SETUP.md`](docs/REBUILD-SETUP.md)**; the three shared data modules
> live in [`shared/`](shared/README.md).

**Publish local data to the hosted database** (run after any extraction batch):

```bash
export DATABASE_URL="postgresql://...supabase.com:5432/postgres"   # session string
.venv312/bin/python sync_dashboard.py --db po_data.db
```

**Run the backend locally** (needs its own env — see `backend/.env.example`):

```bash
python3.12 -m venv .venv_api && .venv_api/bin/pip install -r backend/requirements.txt
cd backend && ../.venv_api/bin/uvicorn app.main:app --reload      # http://localhost:8000
```

**Run the frontend locally** (`web/.env.local` from `web/.env.example`):

```bash
cd web && npm install && npm run dev                              # http://localhost:5173
```

**If `validate_math()`'s logic ever changes**, re-check already-extracted data without re-calling the API, then re-sync:

```bash
.venv312/bin/python recompute_math_checks.py --db po_data.db
.venv312/bin/python sync_dashboard.py --db po_data.db
```

## 3. Cloud extraction pipeline (Gmail-sourced, automatic + manual)

Runs independently of the local pipeline above — reads labeled PO emails
(attachments and body text) straight from Gmail and writes straight to Postgres,
via `run_cloud_extraction.py`, on a GitHub Actions schedule or manual dispatch
(`.github/workflows/extract_pos.yml`).

See [GMAIL_SETUP.md](GMAIL_SETUP.md) for full setup: enabling the Gmail API,
creating an OAuth client, the one-time "Connect Gmail" flow (the app's Settings
page), the `GMAIL_LABELS` value, and the GitHub Actions repo secrets.

Manual local run (own `ANTHROPIC_API_KEY`, same idempotency-by-content-hash model
as the local pipeline — already-processed messages are skipped automatically):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
export GMAIL_CLIENT_ID="..."       # from the Google Cloud OAuth client (GMAIL_SETUP.md)
export GMAIL_CLIENT_SECRET="..."
export GMAIL_LABELS="..."          # see GMAIL_SETUP.md
.venv312/bin/python run_cloud_extraction.py            # incremental
.venv312/bin/python run_cloud_extraction.py --full-backlog   # ignore the cursor, scan everything
```

## Notes

- `po_data.db` (SQLite) is the source of truth for the local pipeline; the hosted Postgres is a published copy the app reads. Re-run `sync_dashboard.py` any time you want it to reflect new local extractions.
- `files/`, `*.db`, `*.xlsx`, `*.log`, `.env` files, and the venvs are gitignored — customer PO data and secrets never get committed.
