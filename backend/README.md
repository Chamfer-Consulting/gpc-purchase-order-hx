# PO Dashboard API

FastAPI backend for the rebuilt dashboard. Replaces the Streamlit app's data layer.
See `../docs/po-dashboard-rebuild-plan.html` and `../docs/REBUILD-TODO.md`.

## Local dev

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL + SUPABASE_JWT_SECRET at minimum
uvicorn app.main:app --reload
```

- `GET /health` — no auth
- `GET /api/overview` — requires `Authorization: Bearer <supabase access token>`
- Docs: http://localhost:8000/docs

## Layout

```
app/
  main.py        FastAPI app, CORS, gzip, lifespan (opens the pool)
  config.py      env settings (pydantic-settings) — no streamlit
  db.py          one psycopg3 pool against the Supabase transaction pooler
  auth.py        verify the Supabase JWT -> AuthedUser dependency
  reuse.py       sys.path shim so the reused repo modules import (transitional)
  routers/       one module per page (JSON endpoints)
  services/      DB queries + pandas transforms, framework-free (filled in Phase 0.4 / 2)
```

## Deploy

Fly.io, from the repo root (Dockerfile needs repo-root context):

```bash
fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile
```

Secrets via `fly secrets set` — see `../docs/REBUILD-SETUP.md` §4.

## Connection strings

This API uses the Supabase **transaction pooler** (`:6543`). The pipeline scripts
(`run_cloud_extraction.py`, `run_qbo_sync.py`) keep using the **session**
connection (`:5432`) — they need long transactions / `execute_values`.
