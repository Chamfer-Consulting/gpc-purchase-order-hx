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
4. **Project Settings → API**, copy:
   - Project URL (`https://<ref>.supabase.co`)
   - `anon` public key
   - `service_role` secret key
5. **Project Settings → API → JWT Settings**, copy the **JWT Secret**.
6. **Database → Extensions**, enable `pg_cron` (needed in Phase 5).

> Keep a scratch note with all seven values — you'll paste them into Railway,
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

Current migrations: `20260828120000_admin_crud.sql` — PO lifecycle `status` +
soft delete, per-line `voided`, `audit_log`. (The API also self-applies this on
boot, so it's safe to defer, but run it so the change is explicit.)

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
4. Leave Neon running (read-only fallback) until Phase 4, then delete it.

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
   | `SUPABASE_JWT_SECRET` | Supabase → API → JWT Settings | required |
   | `ALLOWED_ORIGINS` | `https://<pages-project>.pages.dev` | required in prod |
   | `FRONTEND_BASE` | `https://<pages-project>.pages.dev` | required in prod |
   | `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | from `.streamlit/secrets.toml` | Gmail connect |
   | `GMAIL_REDIRECT_URI` | `https://<railway-domain>/auth/gmail/callback` | Gmail connect |
   | `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | from `.streamlit/secrets.toml` | QBO connect |
   | `QBO_REDIRECT_URI` | `https://<railway-domain>/auth/qbo/callback` | QBO connect |
   | `QBO_ENVIRONMENT` | `production` | QBO connect |
   | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | from §1.4 | optional (unused today) |

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
   - `VITE_SUPABASE_ANON_KEY` = `<anon key>`
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
| Supabase project URL | | | ✅ **SUPABASE_URL** (optional) | ✅ **VITE_SUPABASE_URL** |
| Supabase `anon` key | | | | ✅ **VITE_SUPABASE_ANON_KEY** |
| Supabase `service_role` key | | | ✅ **SUPABASE_SERVICE_KEY** (optional) | |
| Supabase JWT secret | | | ✅ **SUPABASE_JWT_SECRET** *(required)* | |
| Backend public URL | | | | ✅ **VITE_API_BASE** = `https://<railway-domain>` |
| Frontend public URL | | | ✅ **ALLOWED_ORIGINS** + **FRONTEND_BASE** = `https://<pages>.pages.dev` | |
| `ANTHROPIC_API_KEY` | ✅ | ✅ | — (API doesn't call Claude) | |
| `GMAIL_CLIENT_ID` / `_SECRET` | ✅ | ✅ | ✅ (connect flow) | |
| `GMAIL_REDIRECT_URI` | ✅ | | ✅ = `https://<railway-domain>/auth/gmail/callback` | |
| `QBO_CLIENT_ID` / `_SECRET` | ✅ | ✅ | ✅ (connect flow) | |
| `QBO_REDIRECT_URI` | ✅ | | ✅ = `https://<railway-domain>/auth/qbo/callback` | |
| `QBO_ENVIRONMENT` | ✅ | ✅ | ✅ (`production`) | |

Minimum to boot the API: **DATABASE_URL** + **SUPABASE_JWT_SECRET**. The frontend
only ever holds public-safe values (Supabase URL + `anon` key + the API base);
everything sensitive stays server-side. Full local template: `backend/.env.example`,
`web/.env.example`.
