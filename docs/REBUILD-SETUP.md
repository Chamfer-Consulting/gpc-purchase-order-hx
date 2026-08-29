# PO Dashboard Rebuild — Setup & Requirements Guide

Everything the account owner needs to provision. Work top to bottom; the Todo Plan
(`docs/REBUILD-TODO.md`) references these section numbers.

Nothing here changes the running Streamlit app or the scheduled jobs until §3.

---

## 0. Local tooling

Install once:

| Tool | Why | Install |
|---|---|---|
| Python 3.12 | backend (matches the pipeline) | already have it (`.venv312`) |
| Node.js 20 LTS + npm | React frontend build | `brew install node@20` |
| `psql` / `pg_dump` (v16+) | database migration | `brew install postgresql@16` |
| Supabase CLI | project management, local dev | `brew install supabase/tap/supabase` |
| Railway CLI *(optional)* | backend deploy / logs (the dashboard works too) | `brew install railway` |
| GitHub CLI (`gh`) *(optional)* | trigger workflows | `brew install gh` |

Cloudflare Pages needs no CLI — it builds from the GitHub repo.

---

## 1. Supabase project

1. supabase.com → **New project**. Name `gpc-po-dashboard`. Region: closest to the
   team (US East if unsure). Set a strong database password and save it.
2. Choose the **Pro** plan ($25/mo) — the free tier pauses after 7 idle days and
   caps the database at 500 MB. Pro gives no pause, 8 GB, daily backups.
3. When it finishes provisioning, go to **Project Settings → Database** and copy:
   - **Connection string → Transaction pooler** (`...pooler.supabase.com:6543/postgres`) → this is `DATABASE_URL` for the **API**.
   - **Connection string → Session** (`...pooler.supabase.com:5432/postgres` or the direct `db.<ref>.supabase.co:5432`) → this is `DATABASE_URL` for the **pipeline scripts / GitHub Actions**.
   - Swap the password placeholder for the real password in both.
4. **Project Settings → API**, copy the **Project URL** (`https://<ref>.supabase.co`).
5. **Project Settings → API Keys** — Supabase's current key model (the legacy
   `anon` / `service_role` keys still work until **end of 2026**, so either set
   is fine for now):
   - **Publishable key** (`sb_publishable_...`) → the SPA (`VITE_SUPABASE_PUBLISHABLE_KEY`).
     Legacy equivalent: `anon` → `VITE_SUPABASE_ANON_KEY`.
   - **Secret key** (`sb_secret_...`) → the backend, for Storage-backed document
     capture only (`SUPABASE_SECRET_KEY`). Legacy equivalent: `service_role` →
     `SUPABASE_SERVICE_KEY`. Not needed to boot the API.
6. **Access tokens** — the API verifies the SPA's bearer token one of two ways:
   - **Preferred:** just set `SUPABASE_URL`. The API fetches the project's
     asymmetric JWT signing keys from `<url>/auth/v1/.well-known/jwks.json` and
     verifies ES256/RS256 tokens locally — key rotation then needs no redeploy.
   - **Legacy:** if the project still signs HS256, copy **Settings → API Keys →
     JWT Keys → "Legacy JWT Secret"** into `SUPABASE_JWT_SECRET`.
   Setting both is fine (each token's `alg` header picks the path).
7. **Database → Extensions**, enable `pg_cron` (needed in Phase 5).

> Keep a scratch note with these values — you'll paste them into Railway,
> GitHub Actions, and the Cloudflare Pages env in later steps.

---

## 2. Migrate the database (Neon → Supabase)

Run locally. `NEON_URL` = the current `database_url` from `.streamlit/secrets.toml`;
`SUPABASE_SESSION_URL` = the §1.3 session string.

```bash
# 1. dump (schema + data, no ownership/ACL noise)
pg_dump "$NEON_URL" \
  --no-owner --no-privileges --no-comments \
  --format=custom --file=neon_dump.pgcustom

# 2. restore into Supabase
pg_restore --no-owner --no-privileges --clean --if-exists \
  --dbname "$SUPABASE_SESSION_URL" neon_dump.pgcustom

# 3. verify (script added in the first build commit)
python scripts/verify_migration.py "$NEON_URL" "$SUPABASE_SESSION_URL"
```

`verify_migration.py` prints a table of `count(*)` per table for both databases and
exits non-zero on any mismatch. Do not proceed to §3 until it's clean.

Delete `neon_dump.pgcustom` afterward (it contains customer data).

### 2.1 Post-load migrations

Schema changes made on `po-dashboard-rebuild` after the dump live in
`supabase/migrations/` (see its `README.md`). Apply them once the restore verifies:

```bash
# CLI (records each migration):
supabase link --project-ref <ref> && supabase db push
# or plain psql, one file:
psql "$SUPABASE_SESSION_URL" -f supabase/migrations/20260828120000_admin_crud.sql
```

Current migrations:
- `20260828120000_admin_crud.sql` — PO lifecycle `status` + soft delete, per-line
  `voided`, `audit_log`.
- `20260828130000_po_documents.sql` — `po_documents` (captured PO/invoice PDFs).

(The API also self-applies both on boot, so it's safe to defer, but run them so
the change is explicit.)

---

## 3. Cut the running app + jobs over to Supabase

Do this once §2 verifies clean. **This is the switch** — after it, Neon is idle.

1. `.streamlit/secrets.toml` → set `database_url` to the Supabase **transaction
   pooler** string. Restart the Streamlit app. Click through every page — numbers
   must be identical to before.
2. GitHub → repo **Settings → Secrets and variables → Actions** → edit
   `DATABASE_URL` to the Supabase **session** string.
3. Manually trigger each workflow once and confirm green:
   - `extract_pos.yml` (with `limit = 5`)
   - `qbo_sync.yml`
   - `eval_extraction.yml`
   - `doc_capture.yml` — captures the emailed PO PDF + the QuickBooks invoice PDF
     onto each PO. Reuses `DATABASE_URL`, `GMAIL_CLIENT_*`, `QBO_*`; optionally
     `SUPABASE_URL` + `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_KEY`),
     see §3.1.
4. Leave Neon running (read-only fallback) until Phase 4, then delete it.

### 3.1 Document storage (optional)

`po_documents` stores captured PDF bytes **inline in Postgres** by default — no
setup needed, it just works. To offload them to Supabase Storage instead:

1. Supabase → **Storage** → create a **private** bucket named `po-documents`.
2. Set `SUPABASE_URL` + `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_KEY`)
   on Railway **and** as GitHub Actions secrets (so `doc_capture.yml` uploads
   there too).

New captures then go to Storage (`content` NULL, `storage_path` set); reads are
proxied by the API. Existing inline rows stay inline until re-captured.

---

## 4. Backend host — Railway

1. railway.app → **New Project → Deploy from GitHub repo** → this repo.
2. In the service's **Settings**: leave *Root Directory* at `/`. `railway.toml`
   (committed at the repo root) points the build at `backend/Dockerfile` with the
   repo root as context, so the reused Python modules are included.
3. **Variables** tab — add these (full annotated list: `backend/.env.example`):

   | Variable | Value | |
   |---|---|---|
   | `DATABASE_URL` | Supabase **transaction pooler** URL (`:6543`) | required |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` | required — token verification (JWKS) + Storage |
   | `SUPABASE_JWT_SECRET` | Supabase → API Keys → JWT Keys → Legacy JWT Secret | only if the project still signs HS256 (§1.6) |
   | `ALLOWED_ORIGINS` | `https://<pages-project>.pages.dev` | required in prod |
   | `FRONTEND_BASE` | `https://<pages-project>.pages.dev` | required in prod |
   | `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | from `.streamlit/secrets.toml` | Gmail connect |
   | `GMAIL_REDIRECT_URI` | `https://<railway-domain>/auth/gmail/callback` | Gmail connect |
   | `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | from `.streamlit/secrets.toml` | QBO connect |
   | `QBO_REDIRECT_URI` | `https://<railway-domain>/auth/qbo/callback` | QBO connect |
   | `QBO_ENVIRONMENT` | `production` | QBO connect |
   | `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_KEY`) | from §1.5 | optional — only for Storage-backed document capture (§3.1) |

   The API never calls Claude — `ANTHROPIC_API_KEY` stays on the pipeline (GitHub
   Actions), not here.

4. **Settings → Networking → Generate Domain** to get the public URL. Railway
   injects `$PORT`; the Dockerfile CMD and `railway.toml` both honour it.
5. Deploy, then `curl https://<railway-domain>/health`.

Railway's paid usage plan keeps the service always running (no scale-to-zero).
A 512 MB–1 GB instance for an internal tool is ~$5–10/mo of usage.

*(Fly.io alternative: `backend/fly.toml` is still committed — `fly deploy --config
backend/fly.toml --dockerfile backend/Dockerfile` from the repo root, secrets via
`fly secrets set`.)*

---

## 5. Frontend host — Cloudflare Pages

1. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git** →
   pick this repo, branch `po-dashboard-rebuild` (switch to `main` after Phase 4).
2. Build settings:
   - Framework preset: **Vite**
   - Build command: `npm run build`
   - Build output directory: `web/dist`
   - Root directory: `web`
3. Environment variables (Production **and** Preview):
   - `VITE_SUPABASE_URL` = `https://<ref>.supabase.co`
   - `VITE_SUPABASE_PUBLISHABLE_KEY` = `sb_publishable_...` (or legacy `VITE_SUPABASE_ANON_KEY` = `<anon key>`)
   - `VITE_API_BASE` = `https://<railway-domain>`
4. Save & Deploy. Note the `*.pages.dev` URL, set it as the backend's
   `ALLOWED_ORIGINS` **and** `FRONTEND_BASE` in Railway (§4) — Railway redeploys
   on the variable change.

Cost: free.

---

## 6. Supabase Auth

1. **Authentication → Providers → Email**: enable. For an internal tool, turn
   **Confirm email** off and **Allow new users to sign up** off.
2. **Authentication → Users → Add user** for each teammate (email + temp password),
   or use **Send magic link**.
3. **Authentication → URL Configuration**: set the Site URL to the Pages URL and
   add it to the redirect allowlist.
4. **Realtime** (for the live review queue): Database → Publications →
   `supabase_realtime` → add `purchase_orders` and `extraction_reviews`. Without
   this the queue just doesn't auto-refresh; nothing breaks.

---

## 7. OAuth redirect URIs (Phase 1.5)

Add the new callback URLs **alongside** the existing Streamlit ones — don't remove
the old ones until Phase 4.

- **Google Cloud Console → APIs & Services → Credentials → the OAuth client**:
  add `https://<railway-domain>/auth/gmail/callback` to *Authorized redirect URIs*.
- **Intuit developer dashboard → your app → Keys & OAuth**:
  add `https://<railway-domain>/auth/qbo/callback` to *Redirect URIs*.

---

## 8. Phase 5 extras (later)

- **Sentry**: create two projects (`po-dashboard-api`, `po-dashboard-web`); set
  `SENTRY_DSN` as a Railway variable and `VITE_SENTRY_DSN` in Pages.
- **Uptime**: a Cloudflare Health Check or an UptimeRobot monitor on
  `https://<railway-domain>/health`.
- **`pg_cron`**: SQL to schedule the materialized-view refresh (added with the
  views in Phase 5).

---

## Secret inventory (where each value lives)

Env-var name in **bold**. "Railway" = the API service's Variables tab.

| Value | `.streamlit/secrets.toml` (Streamlit, until Phase 4) | GitHub Actions | Railway (API) | Cloudflare Pages (SPA) |
|---|:---:|:---:|:---:|:---:|
| Supabase **transaction pooler** URL (`:6543`) | ✅ `database_url` | | ✅ **DATABASE_URL** | |
| Supabase **session** URL (`:5432`) | | ✅ **DATABASE_URL** | | |
| Supabase project URL | | ✅ (doc_capture) | ✅ **SUPABASE_URL** *(token verification + Storage)* | ✅ **VITE_SUPABASE_URL** |
| Supabase publishable / `anon` key | | | | ✅ **VITE_SUPABASE_PUBLISHABLE_KEY** (or **_ANON_KEY**) |
| Supabase secret / `service_role` key | | ✅ (doc_capture) | ✅ **SUPABASE_SECRET_KEY** (or **_SERVICE_KEY**) — optional, Storage only | |
| Supabase legacy JWT secret | | | ✅ **SUPABASE_JWT_SECRET** — only if the project still signs HS256 | |
| Backend public URL | | | | ✅ **VITE_API_BASE** = `https://<railway-domain>` |
| Frontend public URL | | | ✅ **ALLOWED_ORIGINS** + **FRONTEND_BASE** = `https://<pages>.pages.dev` | |
| `ANTHROPIC_API_KEY` | ✅ | ✅ | — (API doesn't call Claude) | |
| `GMAIL_CLIENT_ID` / `_SECRET` | ✅ | ✅ | ✅ (connect flow) | |
| `GMAIL_REDIRECT_URI` | ✅ | | ✅ = `https://<railway-domain>/auth/gmail/callback` | |
| `QBO_CLIENT_ID` / `_SECRET` | ✅ | ✅ | ✅ (connect flow) | |
| `QBO_REDIRECT_URI` | ✅ | | ✅ = `https://<railway-domain>/auth/qbo/callback` | |
| `QBO_ENVIRONMENT` | ✅ | ✅ | ✅ (`production`) | |

Minimum to boot the API: **DATABASE_URL** + a token-verification path — either
**SUPABASE_URL** (asymmetric JWT signing keys, verified via JWKS; the current
model) or **SUPABASE_JWT_SECRET** (legacy HS256). The frontend only ever holds
public-safe values (Supabase URL + publishable/`anon` key + the API base);
everything sensitive stays server-side. Legacy `anon` / `service_role` keys and
the shared JWT secret remain valid until **end of 2026**. Full local template:
`backend/.env.example`, `web/.env.example`.
