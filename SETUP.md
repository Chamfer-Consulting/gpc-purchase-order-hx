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

## 2. Dashboard (hosted Postgres + Streamlit)

Separate venv — Streamlit's Pillow requirement conflicts with pdfplumber's, so don't install dashboard deps into `.venv312`.

```bash
python3.12 -m venv .venv_dashboard
.venv_dashboard/bin/pip install -r dashboard/requirements.txt
```

**Secrets** (never committed — `.streamlit/secrets.toml` is gitignored):

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# then edit it: dashboard_password + database_url (Neon connection string)
```

**Publish local data to the dashboard database** (run after any extraction batch):

```bash
export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
.venv312/bin/python sync_dashboard.py --db po_data.db
```

**Run the dashboard locally:**

```bash
.venv_dashboard/bin/streamlit run dashboard/app.py
```

**If `validate_math()`'s logic ever changes**, re-check already-extracted data without re-calling the API, then re-sync:

```bash
.venv312/bin/python recompute_math_checks.py --db po_data.db
.venv312/bin/python sync_dashboard.py --db po_data.db
```

## 3. Deploy the dashboard (Streamlit Community Cloud)

1. Push this repo to GitHub (private repo recommended — it contains customer PO data logic).
2. share.streamlit.io → New app → pick this repo → main file: `dashboard/app.py`.
3. App Settings → Secrets → paste the same `dashboard_password` / `database_url` from your local `.streamlit/secrets.toml`.
4. Set the app to **private**, restrict viewers to your email, for a second layer of access control beyond the password.

## 4. Cloud extraction pipeline (Gmail-sourced, automatic + manual)

See [GMAIL_SETUP.md](GMAIL_SETUP.md) for the one-time Google Cloud + OAuth setup
this needs (enabling the Gmail API, creating an OAuth client, consent screen
choices). The ingestion script, GitHub Actions workflow, and in-dashboard connect
flow are separate, in-progress work — this doc only covers getting credentials.

## Notes

- `po_data.db` (SQLite) is the source of truth for the local pipeline; Neon Postgres is a published copy for the dashboard. Re-run `sync_dashboard.py` any time you want the dashboard to reflect new local extractions.
- `files/`, `*.db`, `*.xlsx`, `*.log`, and both venvs are gitignored — customer PO data and secrets never get committed.
