# PO Dashboard Rebuild — Todo Plan

Working branch: `po-dashboard-rebuild`. Plan: `docs/po-dashboard-rebuild-plan.html`.
Setup / provisioning: `docs/REBUILD-SETUP.md`.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done · **(you)** = needs the
account owner / a browser · **(code)** = doable in the repo.

---

## Phase 0 — Supabase cutover & service layer  ·  ~3–5 days

### 0.1 Provision
- [ ] **(you)** Create the Supabase project (region nearest the team). — see SETUP §1
- [ ] **(you)** Enable the `pg_cron` extension (Database → Extensions).
- [ ] **(you)** Grab both connection strings: transaction pooler (`:6543`) and session (`:5432`).
- [ ] **(you)** Grab the project URL, `anon` key, `service_role` key, and JWT secret.

### 0.2 Migrate the database
- [ ] **(you)** `pg_dump` the Neon database (`--no-owner --no-privileges`). — see SETUP §2
- [ ] **(you)** Restore into Supabase via the session connection.
- [ ] **(code)** `scripts/verify_migration.py` — compare `count(*)` for every table Neon vs Supabase.
- [ ] Sign-off: row counts match on every table.

### 0.3 Repoint connection strings
- [ ] **(you)** `.streamlit/secrets.toml` → `database_url` = Supabase **transaction pooler**.
- [ ] **(you)** GitHub Actions secret `DATABASE_URL` → Supabase **session** string (used by `extract_pos.yml`, `qbo_sync.yml`, `eval_extraction.yml`).
- [ ] Run the Streamlit dashboard against Supabase — every page loads, numbers unchanged.
- [ ] Manually run `run_cloud_extraction.py --limit 5` against Supabase — succeeds.
- [ ] Manually run `run_qbo_sync.py` against Supabase — succeeds.
- [ ] Trigger each of the 3 GitHub Actions once — all green.

### 0.4 Extract the service layer  *(code — incremental, own commits)*
- [ ] Create `backend/` scaffold (done in the first build commit).
- [ ] Move `dashboard/data.py` DB + transform functions into `backend/app/services/`:
  - [ ] `services/context.py` — the `AppContext` assembly (`load_data`, `prepare`, `prepare_invoices`, filter application)
  - [ ] `services/overview.py` — home KPIs, revenue series, YoY
  - [ ] `services/customers.py` — customer 360
  - [ ] `services/products.py` — products & sizes, size analysis
  - [ ] `services/explore.py` — pivot / compare-periods / movers
  - [ ] `services/lifecycle.py` — order lifecycle / requested-vs-delivered
  - [ ] `services/quality.py` — data quality, match anomalies, invoice recon
  - [ ] `services/review.py` — extraction review queue, revision candidates
  - [ ] `services/matching.py` — thin wrappers over `qbo_matcher`
  - [ ] `services/settings.py` — reference prices, hidden products, saved views, connections
- [ ] Leave `dashboard/data.py` as a **re-export shim** so Streamlit keeps working.
- [ ] `pytest` smoke: every moved function importable with no `streamlit` dependency.

**Exit:** Streamlit runs unchanged on Supabase, all scheduled jobs pass, logic modules import without `streamlit`.

---

## Phase 1 — Skeleton, auth & first deploy  ·  ~1 week

### 1.1 Backend
- [ ] `backend/app/main.py` — FastAPI app, CORS, `/health`, router registration. *(scaffolded)*
- [ ] `backend/app/config.py` — env settings via `pydantic-settings`. *(scaffolded)*
- [ ] `backend/app/db.py` — `psycopg_pool` connection pool (transaction pooler). *(scaffolded)*
- [ ] `backend/app/auth.py` — verify Supabase JWT (`SUPABASE_JWT_SECRET`, HS256) as a FastAPI dependency. *(scaffolded)*
- [ ] `backend/app/routers/overview.py` — `GET /api/overview` returning real KPI numbers + data series.
- [ ] `backend/tests/` — a test client hitting `/health` and `/api/overview` with a signed test JWT.

### 1.2 Supabase Auth
- [ ] **(you)** Create the team's user accounts (Auth → Users), or enable email magic-link.
- [ ] **(you)** Restrict sign-ups (allowlist domain or disable public sign-up).

### 1.3 Frontend
- [ ] `web/` — Vite + React + TS scaffold. *(scaffolded)*
- [ ] `npm install` and `npm run dev` runs locally.
- [ ] `src/lib/supabase.ts` — Supabase client. *(scaffolded)*
- [ ] `src/lib/api.ts` — fetch wrapper attaching the Supabase access token. *(scaffolded)*
- [ ] `src/auth/` — `AuthProvider`, `LoginPage`, `RequireAuth`. *(scaffolded)*
- [ ] `src/components/AppShell.tsx` — nav rail + header (Mantine). *(scaffolded)*
- [ ] `src/components/FilterBar.tsx` — date range + customer/product/size, state bound to the URL query string.
- [ ] `src/pages/OverviewPage.tsx` — real page: KPI cards (Tremor) + first-pass ECharts.

### 1.4 Deploy
- [ ] **(you)** Create the Fly.io app; set backend secrets. — see SETUP §4
- [ ] `backend/Dockerfile` + `backend/fly.toml` (`min_machines_running = 1`). *(scaffolded)*
- [ ] `fly deploy` — `/health` reachable at the public URL.
- [ ] **(you)** Create the Cloudflare Pages project pointed at `web/`. — see SETUP §5
- [ ] Set `web/` build env vars; deploy; SPA loads.
- [ ] Wire CORS: backend `ALLOWED_ORIGINS` ← the Pages URL.

### 1.5 Move the OAuth callbacks
- [ ] `backend/app/routers/auth_gmail.py` — `GET /auth/gmail/callback` (adapt `dashboard/app.py`'s handler).
- [ ] `backend/app/routers/auth_qbo.py` — `GET /auth/qbo/callback` (adapt `qbo_client.exchange_code_for_tokens`).
- [ ] **(you)** Add the new redirect URIs in Google Cloud Console + the Intuit app (keep the Streamlit ones during overlap).

**Exit:** a teammate logs in at the production URL, sees the live Overview page, < 1s warm.

---

## Phase 2 — Read-only analytics pages  ·  ~2.5 weeks

### 2.1 Chart & shell layer *(the design investment — do first, ~3–4 days)*
- [ ] `web/src/charts/theme.ts` — ECharts theme: the colour-blind-safe palette (light + dark), one hairline gridline set, no tick marks, top-strip legend, `tabular-nums`, muted axis labels. Port from `dashboard/data.py:style()` / `LIGHT` / `DARK`.
- [ ] `web/src/charts/Chart.tsx` — wrapper around `echarts-for-react` (theme, responsive, empty state, download).
- [ ] `web/src/components/KpiCard.tsx` — Tremor KPI card: value, delta, sparkline.
- [ ] `web/src/components/DataGrid.tsx` — table wrapper (sorting, column formatting from a `labels`-style map, CSV export).
- [ ] `web/src/components/ScopeBar.tsx` — "N orders in scope" strip.
- [ ] Storybook-style demo route `/_kitchen-sink` exercising every chart + component.

### 2.2 Endpoint pattern
- [ ] Decide the shared query params: `?start=&end=&customers=&products=&sizes=&include_samples=`.
- [ ] `backend/app/deps.py` — a `FilterParams` dependency + a per-request cached `context` builder.
- [ ] TTL cache (`cachetools`) on the expensive context build.

### 2.3 Pages (each: 1 endpoint file + 1 React page)
- [ ] Customer 360 — `routers/customers.py` + `pages/Customer360Page.tsx`
- [ ] Products & Sizes — `routers/products.py` + `pages/ProductsPage.tsx`
- [ ] Explore — `routers/explore.py` + `pages/ExplorePage.tsx`
- [ ] Order Lifecycle — `routers/lifecycle.py` + `pages/LifecyclePage.tsx`
- [ ] Overview — upgrade to the full chart theme

### 2.4 Client caching
- [ ] TanStack Query `staleTime` per endpoint; stale-while-revalidate.

**Exit:** the four analytics pages match Streamlit number-for-number, all charts through the shared theme, instant on return visits.

---

## Phase 3 — Interactive & editing pages  ·  ~1.5 weeks

- [ ] Match & Reconcile — `routers/matching.py` (`POST /api/matching/run`, `/confirm`, `/reject`) + page with the candidate review UI
- [ ] Data Quality — `routers/quality.py` + page (the fix queue, category segmented control)
- [ ] Extraction Review — `routers/review.py` (`GET queue`, `POST decision`, `DELETE decision`, revision candidates) + page with the verdict form + line-item editor
- [ ] Supabase Realtime subscription on the review queue table → live updates
- [ ] Edit PO — `routers/po_edit.py` (`GET /api/po/{id}`, `POST /api/po/{id}` wrapping `save_po_edit` **unchanged**) + AG Grid editor + optimistic mutation
- [ ] Reference Prices — `routers/pricing.py` + editable grid
- [ ] Settings & Connections — `routers/settings.py` + `routers/connections.py` (QBO/Gmail connect+disconnect, sync buttons, product hiding, saved views)
- [ ] Port `dashboard/attention.py` digest → `routers/overview.py` "needs attention" block

**Exit:** every Streamlit page has an equivalent; a full day's real work needs no Streamlit.

---

## Phase 4 — Cut over & retire Streamlit  ·  ~2–3 days

- [ ] Parallel run 1–2 weeks; Streamlit stays reachable.
- [ ] **(you)** Remove the Streamlit OAuth redirect URIs from Google + Intuit.
- [ ] **(you)** Turn off the Streamlit deployment.
- [ ] `git rm -r dashboard/` (history keeps it); update `AGENTS.md`, `README.md`, `GMAIL_SETUP.md` references.
- [ ] Merge `po-dashboard-rebuild` → `main`.

**Exit:** Streamlit is off and nobody has asked for it back.

---

## Phase 5 — Harden for speed  ·  ~3–5 days

- [ ] Materialized views for revenue / product-mix / customer rollups.
- [ ] **(you)** `pg_cron` job (or a step in the scheduled Actions) to `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
- [ ] Brotli/gzip on the API (`starlette` middleware); `Cache-Control` on stable endpoints.
- [ ] **(you)** Sentry project; wire the FastAPI + React DSNs.
- [ ] **(you)** Uptime check on `/health`.
- [ ] Decide scale: one Fly machine, or two + move the TTL cache to Supabase/Redis.

**Exit:** every page < ~400ms warm; errors reach Sentry before a user reports them.

---

## Cross-cutting checklist (revisit each phase)

- [ ] Every new endpoint requires a valid Supabase JWT.
- [ ] No secret in `web/` beyond the Supabase URL + `anon` key + API base.
- [ ] Pipeline scripts on the **session** connection; API on the **transaction pooler**.
- [ ] Each merged phase leaves `po-dashboard-rebuild` in a deployable state.
