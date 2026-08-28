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
| Fly.io CLI (`flyctl`) | backend deploy | `brew install flyctl` |
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

> Keep a scratch note with all seven values — you'll paste them into Fly, GitHub,
> and `web/.env` in later steps.

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
3. **Variables** tab — add all of these (values from §1 + the pipeline secrets):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | Supabase **transaction pooler** URL (`:6543`) |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | `service_role` key |
   | `SUPABASE_JWT_SECRET` | JWT secret |
   | `ANTHROPIC_API_KEY` | same as the pipeline |
   | `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | from `.streamlit/secrets.toml` |
   | `GMAIL_REDIRECT_URI` | `https://<railway-domain>/auth/gmail/callback` |
   | `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | from `.streamlit/secrets.toml` |
   | `QBO_REDIRECT_URI` | `https://<railway-domain>/auth/qbo/callback` |
   | `QBO_ENVIRONMENT` | `production` |
   | `ALLOWED_ORIGINS` | `https://<pages-project>.pages.dev` |
   | `FRONTEND_BASE` | `https://<pages-project>.pages.dev` |

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
   - `VITE_API_BASE` = `https://<fly-app>.fly.dev`
4. Save & Deploy. Note the `*.pages.dev` URL and put it in the backend's
   `ALLOWED_ORIGINS` (§4), then `fly deploy` again.

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
  add `https://<fly-app>.fly.dev/auth/gmail/callback` to *Authorized redirect URIs*.
- **Intuit developer dashboard → your app → Keys & OAuth**:
  add `https://<fly-app>.fly.dev/auth/qbo/callback` to *Redirect URIs*.

---

## 8. Phase 5 extras (later)

- **Sentry**: create two projects (`po-dashboard-api`, `po-dashboard-web`); set
  `SENTRY_DSN` as a Fly secret and `VITE_SENTRY_DSN` in Pages.
- **Uptime**: a Cloudflare Health Check or an UptimeRobot monitor on
  `https://<fly-app>.fly.dev/health`.
- **`pg_cron`**: SQL to schedule the materialized-view refresh (added with the
  views in Phase 5).

---

## Secret inventory (where each value lives)

| Value | `.streamlit/secrets.toml` | GitHub Actions | Fly secrets | Cloudflare Pages |
|---|:---:|:---:|:---:|:---:|
| Supabase transaction pooler URL | ✅ (`database_url`) | | ✅ (`DATABASE_URL`) | |
| Supabase session URL | | ✅ (`DATABASE_URL`) | | |
| Supabase project URL | | | ✅ | ✅ (`VITE_SUPABASE_URL`) |
| Supabase `anon` key | | | | ✅ (`VITE_SUPABASE_ANON_KEY`) |
| Supabase `service_role` key | | | ✅ | |
| Supabase JWT secret | | | ✅ | |
| `VITE_API_BASE` (Fly URL) | | | | ✅ |
| `ALLOWED_ORIGINS` (Pages URL) | | | ✅ | |
| `ANTHROPIC_API_KEY` | ✅ | ✅ | ✅ | |
| `GMAIL_*`, `QBO_*` | ✅ | ✅ | ✅ | |

The frontend only ever holds public-safe values (Supabase URL + `anon` key + the
API base). Everything sensitive stays server-side.
