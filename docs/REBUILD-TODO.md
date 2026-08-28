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

> Deploy target is **Railway** (backend) + Cloudflare Pages (SPA). `railway.toml`
> at the repo root; `backend/fly.toml` kept as an alt. See SETUP §4.

### 1.1 Backend
- [x] `backend/app/main.py` — FastAPI app, CORS, gzip, `/health`, lifespan opens the pool, all routers registered.
- [x] `backend/app/config.py` — env settings (`pydantic-settings`), incl. `frontend_base` for callback redirects.
- [x] `backend/app/db.py` — `psycopg_pool` (transaction pooler) + `backend/app/reused_db.py` (psycopg2 for the reused repo modules).
- [x] `backend/app/auth.py` — verify Supabase JWT (HS256, `aud=authenticated`) → `AuthedUser` dependency.
- [x] `backend/app/schemas.py` — the `PageResponse` API contract (scope + KPIs + charts + named tables).
- [x] `backend/app/deps.py` (`FilterParams`), `backend/app/cache.py` (`@cached` TTL), `backend/app/oauth_state.py` (signed state).
- [x] `backend/app/routers/overview.py` — `GET /api/overview` (PageResponse; real numbers land with `services/overview.py`).
- [x] `backend/app/routers/analytics.py` — `GET /api/{customers,products,explore,lifecycle}` stubs on the contract.
- [x] `backend/tests/` — `/health`, auth guards, analytics stub shape, OAuth state guard. `pytest` green (7).

### 1.2 Supabase Auth
- [ ] **(you)** Create the team's user accounts (Auth → Users), or enable email magic-link.
- [ ] **(you)** Restrict sign-ups (allowlist domain or disable public sign-up).

### 1.3 Frontend
- [x] `web/` — Vite + React + TS scaffold. Installs, typechecks, builds.
- [x] `src/lib/supabase.ts` — Supabase client.
- [x] `src/lib/api.ts` — fetch wrapper attaching the Supabase access token.
- [x] `src/lib/format.ts` — currency / int / percent / delta formatters (labels.py counterpart).
- [x] `src/auth/` — `AuthProvider`, `LoginPage`, `RequireAuth`.
- [x] `src/components/AppShell.tsx` — nav rail + header (Mantine).
- [x] `src/filters/useFilters.ts` + `src/filters/FilterBar.tsx` — scope bound to the URL query string.
- [ ] `src/pages/OverviewPage.tsx` — upgrade the stub to real KPI cards + the first live ECharts (needs the `/api/overview` service).

### 1.4 Deploy
- [ ] **(you)** Create the Fly.io app; set backend secrets. — see SETUP §4
- [ ] `backend/Dockerfile` + `backend/fly.toml` (`min_machines_running = 1`). *(scaffolded)*
- [ ] `fly deploy` — `/health` reachable at the public URL.
- [ ] **(you)** Create the Cloudflare Pages project pointed at `web/`. — see SETUP §5
- [ ] Set `web/` build env vars; deploy; SPA loads.
- [ ] Wire CORS: backend `ALLOWED_ORIGINS` ← the Pages URL.

### 1.5 OAuth callbacks + connections
- [x] `backend/app/routers/oauth.py` — `GET /auth/gmail/callback` + `GET /auth/qbo/callback`: verify the signed state, exchange the code (reused `gmail_client` / `qbo_client`), 302 back to `/settings?connect=...`.
- [x] `backend/app/routers/connections.py` — `GET /api/connections` (status), `/{provider}/authorize`, `/{provider}/disconnect`, `/qbo/sync`.
- [ ] **(you)** Add the new redirect URIs in Google Cloud Console + the Intuit app (keep the Streamlit ones during overlap). — SETUP §7

**Exit:** a teammate logs in at the production URL, sees the live Overview page, < 1s warm.

---

## Phase 2 — Read-only analytics pages  ·  ~2.5 weeks

### 2.1 Chart & shell layer *(the design investment — done up-front)*
- [x] `web/src/charts/palette.ts` — the colour-blind-safe `LIGHT` / `DARK` sets + `colorMapFor`, ported verbatim from `dashboard/data.py`.
- [x] `web/src/charts/echartsCore.ts` — tree-shaken ECharts (line/bar/pie + grid/tooltip/legend/title/dataZoom/markLine/markArea + Canvas). ~200 KB gzip vs Plotly's ~1 MB.
- [x] `web/src/charts/theme.ts` — the house style from `data.py:style()` as two registered ECharts themes: hairline horizontal gridlines only, no ticks/spines, top-strip legend, dashed cursor spike, unified hover, brand colourway.
- [x] `web/src/charts/Chart.tsx` — the one chart component: takes a plain option, applies the theme for the active colour scheme, responsive, empty state.
- [x] `web/src/charts/options.ts` — `lineOption` / `barOption` / `stackedBarOption` / `horizontalBarOption` / `sparklineOption` so pages pass data, not raw config.
- [x] `web/src/components/KpiCard.tsx` — Mantine card + ECharts sparkline (value, delta with semantic colour). *(Tremor dropped — needs Tailwind, conflicts with Mantine.)*
- [x] `web/src/components/DataGrid.tsx` — click-to-sort, right-aligned numerics, per-column formatting, CSV export.
- [x] `web/src/components/ScopeBar.tsx` — "N POs in scope · date range" strip.
- [x] `web/src/components/EmptyState.tsx`.
- [x] `/_kitchen-sink` route — exercises every chart + component; toggle the OS colour scheme to check both themes.

### 2.2 Endpoint pattern
- [x] Shared query params: `?start=&end=&customers=&products=&sizes=&include_samples=` — `backend/app/deps.py:FilterParams` + `filter_params` dependency (mirrors `web/src/filters/useFilters.ts`).
- [x] `backend/app/cache.py` — `@cached(key_fn)` TTL cache (5 min), the `st.cache_data(ttl=)` counterpart.
- [ ] Per-request `context` builder wired to `FilterParams` (needs the service layer).

### 2.3 Pages
- [x] Frontend for all read-only pages is done: `pages/AnalyticsPage.tsx` (generic — FilterBar + `usePage` + `PageRenderer`), routed for `/customers` `/products` `/explore` `/lifecycle`; `OverviewPage` on the same renderer; `components/PageRenderer.tsx` turns a `PageResponse` into scope bar → KPI grid → charts → tables.
- [x] `dashboard/data.py` made **import-safe headless** (streamlit shim) — the backend calls it directly, no logic fork.
- [x] `services/context.py` (filtered invoice/product frames, product-revenue basis, fuzzy customer match) + `services/customers.py` + `services/products.py` — real KPIs / charts / tables, wired + `@cached`.
- [x] `services/explore.py` (revenue by month/customer/product + MoM movers via `data.month_over_month_movers`) + `services/lifecycle.py` (requested/revised/shipped per PO via `data.prepare` + `order_lifecycle` + `load_matched_line_items`). All 4 analytics endpoints now real + `@cached`.
- [ ] Explore's full pivot configurator (measure × dimension × grain, compare-two-periods) — needs extra query params; the first cut ships the common cuts.

### 2.4 Client caching
- [ ] TanStack Query `staleTime` per endpoint; stale-while-revalidate.

**Exit:** the four analytics pages match Streamlit number-for-number, all charts through the shared theme, instant on return visits.

---

## Phase 3 — Interactive & editing pages  ·  ~1.5 weeks

- [x] **Match & Reconcile** — `routers/matching.py` wraps `qbo_matcher` verbatim (`get_needs_review` / `get_line_items_for_review` / `get_unlinked_pos` / `run_matching` / `confirm_link` / `reject_link`). `pages/MatchPage.tsx`: side-by-side PO↔invoice cards + Run.
- [x] **Data Quality** — `routers/quality.py`, plain aggregations over `purchase_orders` / `line_items` (real). `pages/DataQualityPage.tsx` via `PageRenderer` — extraction failures / math-check / price-anomaly tables.
- [x] **Extraction Review** — decision CRUD straight through `extraction_reviews.py` (`routers/review.py`); queue + revision candidates are real SQL in `services/review_queue.py`. `pages/ReviewPage.tsx`: Queue / Possible revisions / All decisions tabs + verdict form.
- [ ] Supabase Realtime subscription on the review queue table → live updates.
- [x] Edit PO — `services/po_edit.py` (ported `save_po_edit` + a `get_po` reader; `math_check.validate_math` reused). `routers/po_edit.py` = `GET/POST /api/po/{id}`. `pages/EditPoPage.tsx` — editable header + line-item table, math-check feedback, `edited=TRUE` guard. `DataGrid` `linkTo` makes every `po_id` cell link to `/po/:id`.
- [ ] Reference Prices — `routers/pricing.py` + editable grid.
- [ ] Settings — product hiding, saved views (connections already done in Phase 1.5).
- [x] "Needs attention" digest — `routers/overview.py:_attention` (direct SQL for math/error/price/mods + the reused matcher + `review_queue`). `PageResponse.attention` + `AttentionList` component, rendered top of every page that returns it.

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
