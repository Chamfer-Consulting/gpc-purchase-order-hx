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
- [ ] **(you)** Grab the project URL, the **publishable** key (SPA) and **secret**
      key (backend Storage); set `SUPABASE_URL` so the API verifies tokens via the
      JWKS endpoint. Only copy the legacy JWT secret if the project still signs
      HS256. (Legacy `anon`/`service_role`/JWT-secret work until end of 2026.)

### 0.2 Migrate the database
- [ ] **(you)** `pg_dump` the Neon database (`--no-owner --no-privileges`). — see SETUP §2
- [ ] **(you)** Restore into Supabase via the session connection.
- [ ] **(code)** `scripts/verify_migration.py` — compare `count(*)` for every table Neon vs Supabase.
- [ ] Sign-off: row counts match on every table.

### 0.3 Repoint connection strings
- [ ] **(you)** GitHub Actions secret `DATABASE_URL` → Supabase **session** string (used by `extract_pos.yml`, `qbo_sync.yml`, `eval_extraction.yml`, `doc_capture.yml`).
- [ ] **(you)** Railway / local `backend/.env` `DATABASE_URL` → Supabase **transaction pooler** string.
- [ ] Run `scripts/verify_migration.py` + a local `uvicorn app.main:app` smoke check against Supabase — analytics numbers unchanged.
- [ ] Manually run `run_cloud_extraction.py --limit 5` against Supabase — succeeds.
- [ ] Manually run `run_qbo_sync.py` against Supabase — succeeds.
- [ ] Trigger each GitHub Action once — all green.

### 0.4 Service layer  *(done — approach changed: `data.py` stays the source of truth)*
- [x] `backend/` scaffold.
- [x] `dashboard/data.py` made **import-safe without streamlit** (a `_NoStreamlit`
      shim) — the backend imports it and calls its functions directly, no fork,
      Streamlit unaffected.
- [x] `services/context.py` — `build_context(fp)`: filtered invoice/product frames,
      product-revenue basis, date/customer(fuzzy)/product/size/sample filters.
- [x] `services/customers.py`, `services/products.py`, `services/explore.py`,
      `services/lifecycle.py` — real `PageResponse`s; wired + `@cached`.
- [x] `services/review_queue.py` — the SQL-only slice of `load_review_queue` /
      `load_revision_candidates` (no pandas).
- [x] `services/po_edit.py` — `save_po_edit` + `get_po` ported.
- [x] Matching / quality / review / connections routers wrap the reused repo
      modules (`qbo_matcher`, `extraction_reviews`, `qbo_client`, `gmail_client`)
      directly on psycopg2 conns (`app/reused_db.py`).
- [x] `services/overview.py` — the Overview page's scoped revenue/invoice KPIs
      (deltas vs. the preceding period, trailing sparklines), monthly series, and
      year-over-year annual comparison. `context.py` split into `prepared_frames()`
      + `slice_by_date()` for the prev-period reuse.
- [x] `services/settings.py` + `services/pricing.py` — reference-price editor
      (`routers/pricing.py`), hidden-products + saved views (`routers/settings.py`).

**Exit:** every analytics endpoint returns real data; Streamlit + the scheduled jobs unaffected.

---

## Phase 1 — Skeleton, auth & first deploy  ·  ~1 week

> Deploy target is **Railway** (backend) + Cloudflare Pages (SPA). Railway is
> configured in its dashboard — its Config-as-Code (`railway.toml`) was deprecated
> 2026-08-28 and a new service can't opt in, so there's no `railway.toml` in the
> repo. `backend/fly.toml` is kept as an alt (Fly's config is unaffected). See SETUP §4.

### 1.1 Backend
- [x] `backend/app/main.py` — FastAPI app, CORS, gzip, `/health`, lifespan opens the pool, all routers registered.
- [x] `backend/app/config.py` — env settings (`pydantic-settings`), incl. `frontend_base` for callback redirects.
- [x] `backend/app/db.py` — `psycopg_pool` (transaction pooler) + `backend/app/reused_db.py` (psycopg2 for the reused repo modules).
- [x] `backend/app/auth.py` — verify Supabase JWT (HS256, `aud=authenticated`) → `AuthedUser` dependency.
- [x] `backend/app/schemas.py` — the `PageResponse` API contract (scope + KPIs + charts + named tables).
- [x] `backend/app/deps.py` (`FilterParams`), `backend/app/cache.py` (`@cached` TTL), `backend/app/oauth_state.py` (signed state).
- [x] `backend/app/routers/overview.py` — `GET /api/overview` (PageResponse; real numbers land with `services/overview.py`).
- [x] `backend/app/routers/analytics.py` — `GET /api/{customers,products,explore,lifecycle}` wired to real services + `@cached`.
- [x] `backend/tests/` — `/health`, auth guards on every data route, `FilterParams` contract, OAuth state guard. `pytest` green (12).

### 1.2 Supabase Auth
- [x] Login UI does **Google SSO** (`signInWithOAuth`, `/auth/callback` route) + email/password (`LoginPage.tsx`, `AuthCallback.tsx`).
- [ ] **(you)** Enable the Google provider in Supabase + add the Supabase callback URL to the Google OAuth client; set Redirect URLs to `.../auth/callback` (SETUP §6 / §6.1).
- [ ] **(you)** Create any email/password accounts (Auth → Users).
- [ ] **(you)** Restrict sign-ups — OAuth consent screen = Internal (Workspace), or a Before-User-Created hook allowlisting `@garfieldproduce.com`, or disable public sign-up + pre-create users.

### 1.3 Frontend
- [x] `web/` — Vite + React + TS scaffold. Installs, typechecks, builds.
- [x] `src/lib/supabase.ts` — Supabase client.
- [x] `src/lib/api.ts` — fetch wrapper attaching the Supabase access token.
- [x] `src/lib/format.ts` — currency / int / percent / delta formatters (labels.py counterpart).
- [x] `src/auth/` — `AuthProvider`, `LoginPage` (Google SSO + password), `AuthCallback`, `RequireAuth`.
- [x] `src/components/AppShell.tsx` — nav rail + header (Mantine).
- [x] `src/filters/useFilters.ts` + `src/filters/FilterBar.tsx` — scope bound to the URL query string.
- [x] `src/pages/OverviewPage.tsx` — renders `PageRenderer` (real KPIs + the needs-attention digest). Revenue charts land with `services/overview.py`.

### 1.4 Deploy — target: `api.garfieldproduce.com` (Railway) + `dashboard.garfieldproduce.com` (Cloudflare Pages), DNS at DreamHost
- [x] `backend/Dockerfile` (`$PORT`-aware, repo-root build context) + `backend/fly.toml` (alt). *(Railway Config-as-Code deprecated 2026-08-28 — configure the service in the dashboard per SETUP §4; no `railway.toml`.)* `web/public/_redirects` = the SPA fallback for Pages.
- [ ] **(you)** Create the Railway project from the repo; set Build = Dockerfile `backend/Dockerfile`, healthcheck `/health`, then the Variables (SETUP §4).
- [ ] **(you)** Smoke-test the generated `*.up.railway.app` `/health`.
- [ ] **(you)** Create the Cloudflare Pages project — **Root directory = `web`**, output `dist`, framework Vite; set the 3 `VITE_` vars (SETUP §5).
- [ ] **(you)** Custom domains — add `dashboard.` on Pages + `api.` on Railway, then the two CNAMEs at DreamHost (SETUP §5.1). Redeploy Pages so `VITE_API_BASE` takes.

### 1.5 OAuth callbacks + connections
- [x] `backend/app/routers/oauth.py` — `GET /auth/gmail/callback` + `GET /auth/qbo/callback`: verify the signed state, exchange the code (reused `gmail_client` / `qbo_client`), 302 back to `/settings?connect=...`.
- [x] `backend/app/routers/connections.py` — `GET /api/connections` (status), `/{provider}/authorize`, `/{provider}/disconnect`, `/qbo/sync`.
- [ ] **(you)** Add the Railway redirect URIs in Google Cloud Console + the Intuit app (leave any older ones in place until the backend is verified, then prune). — SETUP §7

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
- [x] Per-request `context` builder — `services/context.py:build_context(fp)`.

### 2.3 Pages
- [x] Frontend for all read-only pages is done: `pages/AnalyticsPage.tsx` (generic — FilterBar + `usePage` + `PageRenderer`), routed for `/customers` `/products` `/explore` `/lifecycle`; `OverviewPage` on the same renderer; `components/PageRenderer.tsx` turns a `PageResponse` into scope bar → KPI grid → charts → tables.
- [x] `dashboard/data.py` made **import-safe headless** (streamlit shim) — the backend calls it directly, no logic fork.
- [x] `services/context.py` (filtered invoice/product frames, product-revenue basis, fuzzy customer match) + `services/customers.py` + `services/products.py` — real KPIs / charts / tables, wired + `@cached`.
- [x] `services/explore.py` (revenue by month/customer/product + MoM movers via `data.month_over_month_movers`) + `services/lifecycle.py` (requested/revised/shipped per PO via `data.prepare` + `order_lifecycle` + `load_matched_line_items`). All 4 analytics endpoints now real + `@cached`.
- [x] Explore's full pivot configurator — `GET /api/explore/pivot`
      (`?measure=revenue|orders|quantity&grain=day|week|month|quarter|year|all&dims=customer,product,size`)
      returns a PageResponse (totals KPIs + a top-12-series time chart, rest
      bucketed "Other", + the flat result table) and `GET /api/explore/compare`
      (`?a_start&a_end&b_start&b_end`) returns the two-period invoice/revenue
      KPIs with deltas + a biggest-movers-by-customer table
      (`explore.compare_periods_by_group` reused). `pages/ExplorePage.tsx`
      replaces the generic AnalyticsPage for `/explore`: measure/grain
      segmented controls, a break-by MultiSelect, and a Compare-two-periods
      panel. Both endpoints honour the FilterBar scope and are `@cached`.

### 2.4 Client caching
- [x] TanStack Query `staleTime` per endpoint; stale-while-revalidate. Global 60s
      default in `lib/queryClient.ts`; analytics pages at 5 min + `keepPreviousData`
      (no loading flash on a filter change) to match the backend `@cached` TTL;
      pricing / settings / connections / filter-options tuned individually.

**Exit:** the four analytics pages match Streamlit number-for-number, all charts through the shared theme, instant on return visits.

---

## Phase 3 — Interactive & editing pages  ·  ~1.5 weeks

- [x] **Match & Reconcile** — `routers/matching.py` wraps `qbo_matcher` verbatim (`get_needs_review` / `get_line_items_for_review` / `get_unlinked_pos` / `run_matching` / `confirm_link` / `reject_link`). `pages/MatchPage.tsx`: side-by-side PO↔invoice cards + Run.
- [x] **Data Quality** — `routers/quality.py`, plain aggregations over `purchase_orders` / `line_items` (real). `pages/DataQualityPage.tsx` via `PageRenderer` — extraction failures / math-check / price-anomaly tables.
- [x] **Extraction Review** — decision CRUD straight through `extraction_reviews.py` (`routers/review.py`); queue + revision candidates are real SQL in `services/review_queue.py`. `pages/ReviewPage.tsx`: Queue / Possible revisions / All decisions tabs + verdict form.
- [x] Supabase Realtime subscription on the review queue table → live updates.
      `web/src/lib/realtime.ts:useRealtimeInvalidate` + `ReviewPage.tsx` (subscribes
      to `purchase_orders` and `extraction_reviews`). No-ops if Realtime is off.
- [x] Edit PO — `services/po_edit.py` (ported `save_po_edit` + a `get_po` reader; `math_check.validate_math` reused). `routers/po_edit.py` = `GET/POST /api/po/{id}`. `pages/EditPoPage.tsx` — editable header + line-item table, math-check feedback, `edited=TRUE` guard. `DataGrid` `linkTo` makes every `po_id` cell link to `/po/:id`.
- [x] Reference Prices — `routers/pricing.py` (`GET/POST /api/pricing`,
      `GET /api/pricing/history`) + `services/pricing.py`; `pages/PricingPage.tsx`
      = unit-price history chart (per customer, per product/size) + an editable
      reference-price table (add / edit / delete, save-diff against the loaded
      seed). Nav entry under Data Quality.
- [x] Settings — product hiding (`GET/POST /api/settings/hidden-products` +
      "Product visibility" card) and saved views (`GET/POST/DELETE
      /api/settings/views` + `SavedViewsControl` in the FilterBar, scoped per
      analytics page). Connections already done in Phase 1.5.
- [x] "Needs attention" digest — `routers/overview.py:_attention` (direct SQL for math/error/price/mods + the reused matcher + `review_queue`). `PageResponse.attention` + `AttentionList` component, rendered top of every page that returns it.

**Exit:** every Streamlit page has an equivalent; a full day's real work needs no Streamlit.

---

## Phase 4 — Cut over & retire Streamlit  ·  ~2–3 days

- [x] Streamlit removed from the branch — `dashboard/app.py`, `dashboard/views/`,
      `ui_kit`/`theme`/`filters`/`labels`/`attention`, `dashboard/requirements.txt`,
      `.streamlit/secrets.toml.example` deleted; `streamlit` dep gone. The three
      shared data modules moved to **`shared/`** (`data.py`, `qbo_client.py`,
      `qbo_matcher.py`) — imported by the API (`backend/app/reuse.py`) and the
      runner scripts (`run_qbo_sync.py`, `run_doc_capture.py`); `backend/Dockerfile`
      copies `shared/`. They still carry a no-Streamlit import shim.
- [ ] **(you)** Turn off the Streamlit Community Cloud deployment (it runs off
      `main`; unaffected until this branch merges).
- [ ] **(you)** Remove stale Streamlit OAuth redirect URIs from Google + Intuit
      once the Railway backend's URIs are verified.
- [ ] Rewrite the legacy setup guides for the new stack — `SETUP.md` /
      `GMAIL_SETUP.md` still describe the Streamlit deployment; `docs/REBUILD-SETUP.md`
      is the current runbook. (No `AGENTS.md` / `README.md` at the repo root.)
- [ ] Merge `po-dashboard-rebuild` → `main`.

**Exit:** Streamlit is off and nobody has asked for it back.

---

## Phase 5 — Harden for speed  ·  ~3–5 days

- [ ] Materialized views for revenue / product-mix / customer rollups.
- [ ] **(you)** `pg_cron` job (or a step in the scheduled Actions) to `REFRESH MATERIALIZED VIEW CONCURRENTLY`.
- [ ] Brotli/gzip on the API (`starlette` middleware); `Cache-Control` on stable endpoints.
- [ ] **(you)** Sentry project; wire the FastAPI + React DSNs.
- [ ] **(you)** Uptime check on `/health`.
- [ ] Decide scale: one Railway instance, or two + move the TTL cache to Supabase/Redis.

**Exit:** every page < ~400ms warm; errors reach Sentry before a user reports them.

---

## Cross-cutting checklist (revisit each phase)

- [ ] Every new endpoint requires a valid Supabase JWT.
- [ ] No secret in `web/` beyond the Supabase URL + publishable/`anon` key + API base.
- [x] DB locked to the server: RLS deny-all on every `public` table + no `anon`/`authenticated` grants (`0005_rls_lockdown.sql`, applied to the live project). Any new table auto-gets RLS via the `ensure_rls` event trigger. Don't add a `supabase-js` `.from()` call without revisiting this.
- [ ] Pipeline scripts on the **session** connection; API on the **transaction pooler**.
- [ ] Each merged phase leaves `po-dashboard-rebuild` in a deployable state.

---

## Admin CRUD for purchase orders (2026-08-28)

Full editor/admin control over POs, revisions, cancellations, voided items, and
manual linking — on `po-dashboard-rebuild` (React + FastAPI), Streamlit untouched.
Model: **soft delete** (a `status` enum, rows preserved) + an **audit_log**.

- [x] Schema — `purchase_orders.status` (active/draft/cancelled/withdrawn/voided/deleted) + `status_reason`/`status_at`/`deleted_at`/`edited_by`; `line_items.voided`/`void_reason`; `audit_log` table. In `schema.sql`, `supabase/migrations/0002_admin_crud.sql`, and self-applied by `backend/app/admin_schema.py` on boot.
- [x] Pipeline guard — `sync_dashboard.py` upsert now also requires `COALESCE(status,'active') = 'active'`; every admin mutation stamps `edited = TRUE` so non-active / touched POs are never overwritten or resurrected.
- [x] Reports hide non-active POs — `overview`, `data-quality`, `review_queue`, `lifecycle` all scope to `status = 'active'`.
- [x] Backend — `services/po_admin.py` + `services/audit.py`; `routers/po_admin.py`: `POST /api/po` (create), `DELETE /api/po/{id}` (soft), `POST /api/po/{id}/{status,restore,customer,regroup}`, `POST /api/po/{id}/line/{lid}/void`, `POST|DELETE /api/links`, `GET /api/invoices?search=`, `GET /api/po/{id}/{detail,audit}`. `GET /api/po/{id}` now returns status + revision chain + links + audit.
- [x] Frontend — `EditPoPage` gains a lifecycle panel (status change + reason, soft delete / restore), per-line void toggle, revision-chain panel (regroup / standalone), invoice-links panel with search, and a collapsible audit trail. New `/po/new` route (`NewPoPage`). `MatchPage` gains a manual-link workbench + clickable unlinked-PO list.
- [x] Reactivation is gated by an inline warning block (Edit PO → "Reactivate order…") spelling out the consequences before a non-active PO goes back to `active`.
- [x] Archive page (`/archive`, in the nav) — `GET /api/archive`; tabs per status bucket (All / Cancelled / Withdrawn / Voided / Deleted / Draft) with counts, each row tagged with its status badge and linking to the PO. This is how non-active POs are found.
- [x] Document capture — `po_documents` table (bytes inline). `services/po_docs.py` + `routers/po_docs.py`: `GET /api/po/{id}/documents`, `GET .../documents/{doc_id}` (streams the PDF), `POST .../documents/capture` `{sources:["gmail","qbo"]}`, `POST .../documents/upload` (base64), `DELETE .../documents/{doc_id}`. Gmail = the thread's PDF attachments (`gmail_client`); QBO = `qbo_client.fetch_invoice_pdf` (new — the Print/Save-as-PDF endpoint) for each confirmed linked invoice. `GET /api/po/{id}` now also returns `sources` (the email-thread deep link) and `links[].qbo_url`. Frontend: a Documents panel in `EditPoPage` (capture buttons, upload, view/delete, deep links).
- [x] Tests — auth guards for every new route + mutation (`backend/tests/test_health.py`).
- [x] Backfill + scheduled capture — `po_doc_capture.py` (repo-root core, no FastAPI), `run_doc_capture.py` + `.github/workflows/doc_capture.yml` (nightly sweep after extract + qbo_sync), `POST /api/po/documents/backfill` (on-demand, capped at 1000/source), a "Backfill missing PDFs" card on Settings.
- [x] Supabase Storage offload — `doc_storage.py` (REST, no SDK); `store_document` uploads there + leaves `content` NULL when `SUPABASE_URL`+`SUPABASE_SECRET_KEY` are set (bucket `po-documents`), reads proxy through the API. Inert/inline when unset. SETUP §3.1.
- [x] Google Drive removed — `gdrive_client.py` deleted, the "Sync Drive links" button + the Edit-PO "Original PDF (Drive)" link removed, `google-auth` dep + `gdrive_*` secrets dropped, `qbo_matcher` SELECTs no longer read `drive_file_id`. Original-PDF archival is entirely `po_documents` on Supabase. Columns dropped by `supabase/migrations/0004_drop_gdrive.sql`.
- [x] Migrations renumbered — `supabase/migrations/0001_init.sql` (full base schema, from-scratch-safe) + `0002_admin_crud` / `0003_po_documents` / `0004_drop_gdrive` (deltas) + `0005_rls_lockdown` (RLS + grant revoke, applied to the live project). `schema.sql` reordered so `po_documents` follows `qbo_invoices`.
- [x] Schema into Supabase — migrations `0001`–`0005` run (SETUP §2.1). `drive_file_id`/`drive_synced_at` temporarily re-added for the data load (drop after).
- [x] Data into Supabase — 30,538 rows copied Neon → Supabase via `scripts/pg_data_copy.py` (psycopg2 COPY, column-intersection). `qbo_connection`/`gmail_connection` skipped. `verify_migration.py`: all data tables match. Temp Drive columns dropped.
- [ ] **(you)** Add `doc_capture.yml`'s secrets in GitHub Actions; optionally create the `po-documents` Storage bucket (§3.1).
- [ ] Optional: capture *inside* the extraction pipeline too (so a brand-new PO has its PDF before the nightly sweep) — currently the sweep covers it within a day.
- [x] Bulk lifecycle action from the review queue — `POST /api/bulk/po-status`
      (`po_admin.bulk_set_status`, commits per PO, returns per-id outcomes); the
      Queue tab gains a checkbox per card and a sticky bar to set
      cancelled / withdrawn / deleted / draft on the selection at once.
      (A `status` column on the aggregate analytics tables was dropped — those
      pages are active-only by design; the Archive page is where non-active POs
      are listed with their status.)

---

## Code-review fixes (2026-08-28)

Nine findings from `/code-review` on the branch, all resolved:
- [x] `cache.py` — `threading.Lock` + snapshot reads (no `in`/`[]` TOCTOU); FastAPI runs sync endpoints on a threadpool.
- [x] `FilterBar` dates — parse/format via `dayjs` (local), was UTC round-trip → off-by-one day.
- [x] `FilterBar` options were dead — new `GET /api/filters/options` + `useFilterOptions`, wired in `AnalyticsPage`.
- [x] `services/review_queue.py` — dedupe by `po_id` after the `OR`-join (fan-out doubled the attention counts).
- [x] `services/explore.py` — `by_prod.head(_TOP_N)` (was plotting every product).
- [x] `DataGrid` CSV — prefix `=+-@` cells with `'` (formula injection via email subject/from).
- [x] `EditPoPage` — stable `_rk` row keys (index keys misattached input state on mid-row delete).
- [x] `services/lifecycle.py` — null-safe date + numeric columns (`"NaT"` string / bare `NaN` in JSON).
- [x] `SettingsPage` — auto-dismiss effect deps `[callback]` only (`sp` object churned the timer).
- [x] extra: `services/_util.records()` — NaN/NaT → None on every `to_dict("records")` path.
