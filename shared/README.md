# `shared/` — data modules used by both the API and the pipeline

Three modules that the FastAPI backend (`backend/`) and the scheduled
GitHub Actions scripts (`run_qbo_sync.py`, `run_doc_capture.py`) both import:

| Module | What it is |
|--------|------------|
| `data.py` | Postgres data access + pandas frame prep for the analytics endpoints (invoice/PO loaders, `prepare_invoices`, `order_lifecycle`, reference-price / hidden-product / saved-view CRUD, `month_over_month_movers`, `compare_periods_by_group`, the colour palette). |
| `qbo_client.py` | QuickBooks Online REST client — OAuth token exchange/refresh, item & invoice sync, `fetch_invoice_pdf`. |
| `qbo_matcher.py` | PO ↔ invoice matching engine — `run_matching`, `get_needs_review`, `get_unlinked_pos`, `confirm_link` / `reject_link`, `manual_link`, `customers_match`. |

These were formerly `dashboard/data.py` etc. under the retired Streamlit app.
They import cleanly **without Streamlit** — `data.py` / `qbo_client.py` carry a
tiny `try: import streamlit` / else-shim so a `@st.cache_data` decorator and a
`st.secrets` lookup still resolve when Streamlit isn't installed.

**How they're found:** the backend adds `shared/` + the repo root to `sys.path`
via `backend/app/reuse.py`; the runner scripts do the same `sys.path.insert`.
So they're imported by bare name (`import qbo_matcher`), not `shared.qbo_matcher`.

Repo-root modules they depend on: `product_catalog`, `math_check`,
`extraction_reviews`.
