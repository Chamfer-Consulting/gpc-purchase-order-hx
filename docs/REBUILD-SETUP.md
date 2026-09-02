# PO Dashboard Rebuild — Setup & Requirements Guide

Everything the account owner needs to provision. Work top to bottom; the Todo Plan
(`docs/REBUILD-TODO.md`) references these section numbers.

Nothing here changes the live scheduled jobs until §3. (There is no Streamlit app
in this build — it was removed; the pipeline scripts and the FastAPI backend are
all that read the database.)

**Final URLs** (DNS at DreamHost — see §5.1):

| | Host | URL |
|---|---|---|
| Frontend (React SPA) | Cloudflare Pages | `https://dashboard.garfieldproduce.com` |
| Backend (FastAPI API) | Railway | `https://api.garfieldproduce.com` |

Both are subdomains of `garfieldproduce.com`, so the SPA→API calls are still
cross-origin — `ALLOWED_ORIGINS` on the backend must name the frontend host.

---

## 0. Local tooling

Install once:

| Tool | Why | Install |
|---|---|---|
| Python 3.12 | backend (matches the pipeline) | already have it (`.venv312`) |
| Node.js 20 LTS + npm | React frontend build | `brew install node@20` |
| `psql` / `pg_dump` / `pg_restore` (**v17**, ≥ the server major) | database migration (§2) | `brew install postgresql@17` |
| Supabase CLI | project management, local dev | `brew install supabase/tap/supabase` |
| Railway CLI *(optional)* | backend deploy / logs (the dashboard works too) | `brew install railway` |
| GitHub CLI (`gh`) *(optional)* | trigger workflows | `brew install gh` |

Cloudflare needs no local CLI — it builds the frontend from the GitHub repo.

---

## 1. Supabase project

1. supabase.com → **New project**. Name `gpc-po-dashboard`. Region: closest to the
   team (US East if unsure). Set a strong database password and save it.
2. Choose the **Pro** plan ($25/mo) — the free tier pauses after 7 idle days and
   caps the database at 500 MB. Pro gives no pause, 8 GB, daily backups.
3. When it finishes provisioning, go to **Project Settings → Database** and copy
   the **pooler** strings (both are on `aws-0-<region>.pooler.supabase.com`, user
   `postgres.<ref>`). **Do not use the `db.<ref>.supabase.co` direct host** — it's
   IPv6-only, so Railway / most PaaS can't reach it (symptom: a bare
   `OperationalError` on every request).
   - **Session pooler** (`…pooler.supabase.com:5432`) → `DATABASE_URL` for **both**
     the API and the pipeline scripts / GitHub Actions. Simplest; supports
     everything.
   - **Transaction pooler** (`…pooler.supabase.com:6543`) also works for the API
     (the pool sets `prepare_threshold=None` for it) — use it only if you later
     need more concurrent connections.
   - Swap the password placeholder for the real password.
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
> GitHub Actions, and the Cloudflare build variables in later steps.

---

## 2. Get the schema + data into Supabase

Run everything from the repo root, on a machine with **Postgres 17 client tools**
(`pg_dump` / `pg_restore` / `psql` ≥ the server's major — Supabase is PG 17;
`brew install postgresql@17`).

Set the two connection strings first:

```bash
# Supabase → Settings → Database → Connection string → Session mode  (port 5432)
export SUPABASE_SESSION_URL='postgresql://postgres.<ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres'
# the pipeline's current database — the DATABASE_URL GitHub Actions secret / your backend/.env
export NEON_URL='postgresql://<user>:<pw>@<host>/<db>?sslmode=require'
```

### 2.1 Schema — run the migrations

```bash
for f in supabase/migrations/[0-9]*.sql; do
  echo ">>> $f"; psql "$SUPABASE_SESSION_URL" -v ON_ERROR_STOP=1 -f "$f" || break
done
```

`0001_init.sql` builds every table; `0002`–`0003` add two CHECK constraints;
`0004` drops the retired Drive columns; `0005` enables RLS on every table and
revokes the `anon`/`authenticated` grants (see §6.2). All idempotent. `supabase db
push` does the same and records versions — the `psql` loop is the reliable path.
See `supabase/migrations/README.md`.

### 2.2 Data — data-only dump from Neon

The schema already exists from 2.1, so this is a **`--data-only`** load. Do **not**
do a full `pg_restore --clean` of a schema+data dump — it would drop the migrated
schema, RLS lockdown included.

**Step 1 — open the schema for the load.** Neon (pre-cutover) still has
`purchase_orders.drive_file_id` / `drive_synced_at`; `0004` removed them from
Supabase, so a data-only `COPY` of those columns would fail. Re-add them
temporarily:

```bash
psql "$SUPABASE_SESSION_URL" -c "
  ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_file_id  TEXT;
  ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS drive_synced_at TIMESTAMPTZ;"
```

**Step 2 — dump the rows from Neon.** Add
`--exclude-table-data='qbo_connection' --exclude-table-data='gmail_connection'`
here if you'd rather reconnect Gmail / QuickBooks from the app's Settings page
than carry the OAuth tokens over (see the note below).

```bash
pg_dump "$NEON_URL" --data-only --no-owner --no-privileges --no-comments \
  --format=custom --file=neon_data.pgcustom
```

**Step 3 — load into Supabase.** `--disable-triggers` turns off FK/constraint
checks for the load (the source data is already consistent) and needs table
ownership — the migrations ran as `postgres`, which owns them, so it's fine. If it
still errors on permissions, drop that flag; `pg_dump` orders the tables by FK
dependency so it loads anyway.

```bash
pg_restore --data-only --no-owner --no-privileges --disable-triggers \
  --single-transaction --dbname "$SUPABASE_SESSION_URL" neon_data.pgcustom
```

If it errors `column "X" does not exist` for some column other than the two Drive
ones, `ALTER TABLE … ADD COLUMN IF NOT EXISTS X …`, rerun, and drop it in step 5.

**Step 4 — verify.** Compares `count(*)` per table between the two databases;
tables that exist only on Supabase (`audit_log`, `po_documents`, …) are new and
expected to be empty.

```bash
python scripts/verify_migration.py "$NEON_URL" "$SUPABASE_SESSION_URL"
```

**Step 5 — close the schema back up** (re-applies `0004`):

```bash
psql "$SUPABASE_SESSION_URL" -c "
  ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_file_id;
  ALTER TABLE purchase_orders DROP COLUMN IF EXISTS drive_synced_at;"
```

**Step 6 — clean up.** `rm neon_data.pgcustom` — it holds customer data.

> **OAuth tokens:** unless excluded in step 2, `qbo_connection` / `gmail_connection`
> come across, so the Supabase app is immediately "connected" to QuickBooks +
> Gmail. From that point run the extraction / sync jobs **only** against Supabase —
> two databases sharing one refresh token means whichever refreshes first
> invalidates the other.

### 2.3 No pg17 client tools? (psycopg2 alternative)

`scripts/pg_data_copy.py` does the same data move over the COPY protocol with only
`psycopg2` — no `pg_dump`/`pg_restore`, and it copies only the columns present in
**both** databases, so the Drive-column drift in step 1 isn't needed:

```bash
.venv312/bin/python scripts/pg_data_copy.py "$NEON_URL" "$SUPABASE_SESSION_URL" \
  --exclude qbo_connection,gmail_connection   # drop --exclude to carry the OAuth tokens
```

It loads parents before children, skips any target table that already has rows
(safe to re-run), and resets the `id` sequences. Follow with step 4
(`verify_migration.py` — the two excluded tables will read as MISMATCH, that's the
exclusion, not data loss) and step 6 (nothing to `rm`).

### 2.4 No data to carry at all?

Skip 2.2 entirely. Load data later by pointing the extraction pipeline's
`DATABASE_URL` at Supabase and letting it publish.

Do not proceed to §3 until the data is in and `verify_migration.py` is clean
(bar any deliberately excluded tables).

---

## 3. Cut the running app + jobs over to Supabase

Do this once §2 verifies clean. **This is the switch** — after it, Neon is idle.

1. GitHub → repo **Settings → Secrets and variables → Actions** → edit
   `DATABASE_URL` to the Supabase **session** string (`:5432`). This is what the
   scheduled jobs use. (The API on Railway uses the SAME session pooler string —
   set that as its `DATABASE_URL` in §4 / your local `backend/.env`.)
2. Sanity-check the deployed app: open `https://dashboard.garfieldproduce.com`,
   sign in, and confirm the analytics pages load numbers that match §2.2's
   `verify_migration.py` output (re-run it any time with the two URLs).
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
3. Move the PDFs already stored inline in Postgres into the bucket (optional but
   recommended, so the DB stops carrying them): run `doc_capture.yml` from the
   Actions tab with **migrate_storage** checked — resumable, re-run until it
   reports `0 still inline` (`--limit` caps docs per pass). Locally:
   `python run_doc_capture.py --migrate-storage`.

New captures then go to Storage (`content` NULL, `storage_path` set); reads
prefer inline `content` and fall back to Storage, so a half-finished migration
serves both. Reads are proxied by the API.

### 3.2 Run notifications (optional)

Each scheduled workflow (`extract_pos.yml`, `qbo_sync.yml`, `doc_capture.yml`) ends
with a `Notify run outcome` step (`notify_run.py`) that posts the run's result —
success, partial, "reconnect QuickBooks", or crash, with stats — to:

- **the in-app audit timeline** (`/audit`, filter *Entity = pipeline*) — always, via
  `DATABASE_URL`; no setup.
- **Slack** — only if `SLACK_WEBHOOK_URL` is set. Create a Slack **Incoming Webhook**
  (Slack → Apps → Incoming Webhooks → add to a channel) and paste the URL into
  GitHub → **Settings → Secrets and variables → Actions** as `SLACK_WEBHOOK_URL`.

The step never fails a run, and with the secret unset it simply skips the Slack half.

---

## 4. Backend host — Railway

> Railway deprecated **Config as Code** (`railway.toml` / `railway.json`) on
> 2026-08-28: a service that never used one can no longer opt in, and existing
> files stop working on 2026-12-01. So there is **no `railway.toml` in this repo** —
> configure the service in the dashboard (steps below). If you want the config
> version-controlled, use Railway's Infrastructure-as-Code / Terraform provider
> against the same settings.

1. railway.app → **New Project → Deploy from GitHub repo** → this repo.
2. Service **Settings → Source**: *Root Directory* = `/` (the Dockerfile copies the
   reused modules from the repo root).
3. Service **Settings → Build**: *Builder* = **Dockerfile**, *Dockerfile Path* =
   `backend/Dockerfile`.
4. Service **Settings → Deploy**:
   - *Start Command* — leave blank; the image's `CMD` already runs
     `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   - *Health Check Path* = `/health`, *Health Check Timeout* = `10`.
   - *Restart Policy* = **On Failure**, max **3** retries.
5. **Variables** tab — add these (full annotated list: `backend/.env.example`):

   | Variable | Value | |
   |---|---|---|
   | `DATABASE_URL` | Supabase **session pooler** URL (`aws-0-<region>.pooler.supabase.com:5432`, user `postgres.<ref>`) — NOT the `db.<ref>.supabase.co` direct host | required |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` | required — token verification (JWKS) + Storage |
   | `SUPABASE_JWT_SECRET` | Supabase → API Keys → JWT Keys → Legacy JWT Secret | only if the project still signs HS256 (§1.6) |
   | `ALLOWED_ORIGINS` | `https://dashboard.garfieldproduce.com` | required in prod |
   | `ALLOWED_EMAIL_DOMAINS` | `garfieldproduce.com,adelantecenter.org` | **who may sign in** — a verified token whose email is off-domain, not in `ALLOWED_EMAILS`, and has no `app_users` row is rejected 403 at the API. Leave unset only in dev. |
   | `ALLOWED_EMAILS` | `jcaternolo@gmail.com` | explicit off-domain exceptions, comma-separated |
   | `FRONTEND_BASE` | `https://dashboard.garfieldproduce.com` | required in prod |
   | `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | from the GitHub Actions secrets (same values the pipeline uses) | Gmail connect |
   | `GMAIL_REDIRECT_URI` | `https://api.garfieldproduce.com/auth/gmail/callback` | Gmail connect |
   | `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | from the GitHub Actions secrets | QBO connect |
   | `QBO_REDIRECT_URI` | `https://api.garfieldproduce.com/auth/qbo/callback` | QBO connect |
   | `QBO_ENVIRONMENT` | `production` | QBO connect |
   | `SUPABASE_SECRET_KEY` (or legacy `SUPABASE_SERVICE_KEY`) | from §1.5 | optional — only for Storage-backed document capture (§3.1) |

   The API never calls Claude — `ANTHROPIC_API_KEY` stays on the pipeline (GitHub
   Actions), not here. The `*.garfieldproduce.com` URLs above only resolve once
   §5.1 (DNS) is done; the API still boots without them — just don't run the Gmail
   / QuickBooks connect flows until the custom domain is live.

6. **Settings → Networking → Generate Domain** — Railway gives the service a
   `*.up.railway.app` URL. Use it for the smoke test now; the permanent
   `api.garfieldproduce.com` custom domain is added in §5.1.
7. Deploy, then `curl https://<service>.up.railway.app/health` → `{"status":"ok"}`.

Railway's paid usage plan keeps the service always running (no scale-to-zero).
A 512 MB–1 GB instance for an internal tool is ~$5–10/mo of usage.

*(Fly.io alternative: `backend/fly.toml` is still committed — `fly deploy --config
backend/fly.toml --dockerfile backend/Dockerfile` from the repo root, secrets via
`fly secrets set`.)*

---

## 5. Frontend host — Cloudflare

Two Cloudflare products can host the SPA; the choice hinges on **where DNS lives**:

| | Custom domain with DNS **staying at DreamHost** | Needs DNS **on Cloudflare** |
|---|:---:|:---:|
| **Pages** (classic) | ✅ CNAME from DreamHost works | — |
| **Workers** (static assets) | ✗ (custom domains require the Cloudflare zone) | ✅ |

DreamHost is the plan (§5.1), so use **Pages**. (The Worker path would need an
assets-only `web/wrangler.jsonc` with `not_found_handling:
"single-page-application"` — don't add it for Pages, it makes Pages log a
"Wrangler configuration file … does not appear to be valid" warning on every
build.)

### Pages (recommended)

1. Cloudflare → **Workers & Pages → Create → Pages → Connect to Git** → this repo,
   branch `po-dashboard-rebuild` (switch to `main` after Phase 4).
2. **Build configuration** — the React app is in `web/`, and the repo root has a
   Python `requirements.txt` (the pipeline's) that Cloudflare will otherwise try to
   `pip install` before failing on a missing root `package.json`:
   - **Root directory**: `web`  ← the setting that matters
   - Framework preset: **Vite**
   - Build command: `npm run build`
   - Build output directory: `dist`  ← relative to the root directory. Setting it
     to `web/dist` with root directory `web` makes Pages look for `web/web/dist`
     and fail with *Output directory "web/web/dist" not found*.
3. Environment variables (Production **and** Preview):
   - `VITE_SUPABASE_URL` = `https://<ref>.supabase.co`
   - `VITE_SUPABASE_PUBLISHABLE_KEY` = `sb_publishable_...` (or legacy `VITE_SUPABASE_ANON_KEY` = `<anon key>`)
   - `VITE_API_BASE` = `https://api.garfieldproduce.com`
4. Save & deploy → a `*.pages.dev` URL. Check the app loads; the permanent
   `dashboard.garfieldproduce.com` domain is added in §5.1. `web/public/_redirects`
   gives React Router its SPA fallback so deep links and refreshes work.

Cost: free.

> **Made a *Worker* instead?** (Deploy command `npx wrangler versions upload`, a
> "Build token".) A Worker custom domain needs the zone on Cloudflare DNS, which
> conflicts with the DreamHost plan — delete it and create a **Pages** project.
> Only keep the Worker if you'll move `garfieldproduce.com` DNS to Cloudflare;
> then add `web/wrangler.jsonc` (`name` matching the Worker, `assets.directory`
> `./dist`, `assets.not_found_handling` `single-page-application`), Root directory
> `web`, deploy command `npx wrangler deploy`.

**Build ran `pip install -r requirements.txt` then failed with `npm error … Could
not read package.json … /opt/buildhome/repo/package.json`:** Root directory is
still `/`. Set it to `web` and retry.

---

## 5.1 Custom domains (DNS at DreamHost)

DreamHost is only the DNS authority for `garfieldproduce.com` — it hosts nothing
here. Each host issues its own TLS cert **only after** the custom domain is
registered in its dashboard *and* the CNAME resolves — a CNAME on its own gets a
TLS or 404 error because the host doesn't yet route that Host header.

1. **Cloudflare Pages** → the project → **Custom domains → Set up a domain** →
   `dashboard.garfieldproduce.com` → **Continue**. Pages sees the zone isn't on
   its DNS and shows the **CNAME target** — the project's own `*.pages.dev`
   hostname (the "production" URL on the project overview, e.g.
   `gpc-purchase-order-hx.pages.dev`). Do this step *before* / alongside the DNS
   record, not after.
2. **Railway** → the service → **Settings → Networking → Custom Domain** →
   `api.garfieldproduce.com`. Railway shows a **CNAME target** (e.g.
   `<hash>.up.railway.app`).
3. **DreamHost** → **Panel → Domains → Manage Domains →** the `DNS` link for
   `garfieldproduce.com` → **Add a custom record** (twice):

   | Name | Type | Value |
   |---|---|---|
   | `dashboard` | `CNAME` | the target from step 1 |
   | `api` | `CNAME` | the target from step 2 |

   Leave TTL at the default. The CNAME must be the **only** record at that
   hostname — do **not** also "add hosting" for the subdomain (that adds a
   conflicting A record to DreamHost's web servers). `garfieldproduce.com`'s
   delegation lists both DreamHost and Cloudflare nameservers with **DreamHost as
   primary** (SOA `ns1.dreamhost.com`) — manage every record in the DreamHost
   panel; the Cloudflare nameservers are a read-only secondary and records added
   in a Cloudflare zone dashboard won't be served.
4. Wait for each host's Custom-Domains panel to go **Active** (cert issued —
   minutes, occasionally hours). Verify:

   ```bash
   dig +short dashboard.garfieldproduce.com     # -> gpc-purchase-order-hx.pages.dev (then CF IPs)
   curl -sI https://dashboard.garfieldproduce.com | head -1   # -> HTTP/2 200
   curl -s  https://api.garfieldproduce.com/health            # -> {"status":"ok",...}
   ```

   `api.garfieldproduce.com` returning `{"code":404,"message":"Application not
   found",...}` (or a response with `x-railway-fallback: true`) = the CNAME
   resolves to Railway's edge but the Custom Domain isn't **verified** on the
   service yet. Both records must match what Railway's Custom Domain panel shows
   **right now**: the `<hash>.up.railway.app` CNAME target *and* the
   `_railway-verify.<sub>` TXT value. Railway mints a **new** verify token every
   time you remove and re-add the domain — if you've retried a few times, copy
   the token that's on the panel now and overwrite the DNS TXT with it. The raw
   `*.up.railway.app` `/health` keeps working throughout.
5. Confirm the env vars already point at the custom domains (they do, per §4/§5):
   `VITE_API_BASE`, `ALLOWED_ORIGINS`, `FRONTEND_BASE`, `GMAIL_REDIRECT_URI`,
   `QBO_REDIRECT_URI`. Redeploy the Pages project so the built bundle picks up
   `VITE_API_BASE`.

> Keeping the API on the raw `*.up.railway.app` URL instead is fine — just use
> that URL everywhere `api.garfieldproduce.com` appears above and skip step 2.

---

## 6. Supabase Auth

The login page offers **Continue with Google** (SSO) and email + password.

1. **Authentication → Providers → Email**: enable. For an internal tool, turn
   **Confirm email** off. Leave **Allow new users to sign up** *on* if you want
   Google SSO to create accounts on first sign-in (see §6.1 for restricting to
   your domain); turn it *off* and pre-create every user if you'd rather gate it
   that way.
2. **Authentication → Users → Add user** for anyone using email + password (or a
   Google user you pre-create — the email must equal their Google address).
3. **Authentication → URL Configuration**:
   - **Site URL** = `https://dashboard.garfieldproduce.com`
   - **Redirect URLs** — add `https://dashboard.garfieldproduce.com/auth/callback`
     (and `http://localhost:5173/auth/callback` for local dev, plus the
     `*.pages.dev` URL while testing). The SPA sends the browser back here after
     Google.
4. **Leaked password protection**: Auth → Providers → Email (or Auth settings) →
   enable "Prevent use of leaked passwords" (HaveIBeenPwned). Minor with SSO, but
   the security advisor flags it.
5. **Realtime** (optional — the live review-queue refresh): Database →
   Publications → `supabase_realtime` → add `purchase_orders` and
   `extraction_reviews`. With the RLS lockdown (§6.2) this **also needs** a
   `FOR SELECT TO authenticated USING (true)` policy on just those two tables, or
   no change events reach the browser. Skipping all of this is fine — the queue
   just doesn't auto-refresh.

### 6.1 Google SSO

1. **Google Cloud Console → APIs & Services → Credentials** — reuse the existing
   OAuth client (the one from `GMAIL_SETUP.md`) or **Create Credentials → OAuth
   client ID → Web application**. To its **Authorized redirect URIs** add exactly:
   `https://<ref>.supabase.co/auth/v1/callback` (shown on the Supabase Google
   provider page). No new scopes — SSO only needs `openid email profile`.
2. **OAuth consent screen**:
   - `garfieldproduce.com` is a **Google Workspace** domain → set it to
     **Internal**. Only org members can sign in, no Google verification needed,
     and you get automatic domain restriction for free.
   - Not Workspace → it must be **In production** (Google review may apply);
     restrict who gets in via §6.1 step 4.
3. **Supabase → Authentication → Providers → Google** → enable → paste the
   **Client ID** and **Client Secret** from step 1 → save.
4. **Restrict to your domain** (skip if the consent screen is Internal):
   - Supabase → **Authentication → Auth Hooks → Before User Created** → a Postgres
     function or Edge Function that rejects any `email` not ending in
     `@garfieldproduce.com`, **or**
   - turn **Allow new users to sign up** off (§6, step 1) and pre-create every
     user.
5. Test: open `https://dashboard.garfieldproduce.com`, click **Continue with
   Google**, approve — you land back on `/auth/callback`, then the Overview page.

### 6.2 Row-level security

Applied by `supabase/migrations/0005_rls_lockdown.sql` (part of §2). The model:

- **All DB access is server-side.** The API connects as `postgres` (`BYPASSRLS`);
  the browser only calls Supabase **Auth**, never PostgREST (`/rest/v1/`).
- `0005` therefore enables **RLS with no policies** on every `public` table (=
  deny-all for `anon` / `authenticated`) and **revokes every `anon` /
  `authenticated` table + sequence grant**. A leaked publishable key (it ships in
  the SPA bundle) or a signed-in user cannot read or write any row via PostgREST.
- An `ensure_rls` event trigger enables RLS on any table created later.
- The advisor's 17× **"RLS enabled, no policy" is INFO-level and expected** — do
  not add policies. (`get_advisors` should show nothing above INFO after §6, step 4.)
- If you ever want the SPA to query Supabase directly (`supabase-js` `.from(...)`),
  that's a real design change: it needs per-table policies and re-granting the
  `authenticated` role — reconsider before doing it.

### 6.3 Who can sign in + authorization tiers (`app_users`)

**Two gates.** Identity first (are you allowed in at all), then role (what you can do).

**Identity — the allow-list.** `current_user` rejects a valid token unless its email
(a) has an `ALLOWED_EMAIL_DOMAINS` domain, (b) is in `ALLOWED_EMAILS`, or (c) has an
`app_users` row. With both env lists unset, only `app_users` members get in — a safe
fail-closed default. A rejected user sees a "request access" screen (403
`account_not_allowed`), not a broken app.

A second layer stops outsiders before an `auth.users` row is even created: the
`before-user-created` Supabase hook `public.restrict_signup_domain` (migration
`0011`). **Enable it:** Dashboard → Authentication → Hooks → "Before user created"
→ Postgres → `public.restrict_signup_domain`. Keep its `ok_domains` / `ok_emails`
in sync with the env vars. Also recommended: Authentication → Providers → Email →
turn **"Enable signups" off** (accounts come via Google or an admin).

**Roles** (`app_users (email, role)`, migration `0006`), least to most:

| role | can | e.g. |
|---|---|---|
| `viewer` | read every page; no writes | **the default for an allowed user with no row** |
| `editor` | edit POs, void lines, link/unlink invoices, run matching, review-queue decisions, reference prices, doc capture | day-to-day ops |
| `admin` | everything an editor can, **plus** lifecycle status changes, soft-delete / restore, bulk status, connections, the team list | you |

- **A signed-in allowed user with no `app_users` row is `viewer`** (read-only). `editor`
  / `admin` must be granted. (This changed from `editor` — see the Team section.)
- The repo owner (`jcaternolo@gmail.com`) is seeded as `admin` by `0006`.
- Manage the team in-app: **Settings → Team** (admin only) — add by email, set role,
  remove. Or by SQL:
  ```sql
  INSERT INTO app_users (email, role) VALUES ('someone@garfieldproduce.com', 'editor')
    ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, updated_at = now();
  ```
- Adding someone to `app_users` also lets an **off-domain** address sign in (gate c).
- Role is cached ~60 s (a Team change busts it immediately). Enforcement is
  server-side (403 `forbidden` / `account_not_allowed`); the SPA also hides
  controls a role can't use.

---

## 7. OAuth redirect URIs (Phase 1.5)

Register these once the `api.` custom domain is live (§5.1). Add them **alongside**
any redirect URIs already registered — prune stale ones later. They must match the
`GMAIL_REDIRECT_URI` / `QBO_REDIRECT_URI` set on Railway (§4) exactly.

- **Google Cloud Console → APIs & Services → Credentials → the OAuth client**:
  add `https://api.garfieldproduce.com/auth/gmail/callback` to *Authorized redirect URIs*.
- **Intuit developer dashboard → your app → Keys & OAuth**:
  add `https://api.garfieldproduce.com/auth/qbo/callback` to *Redirect URIs*.

---

## 8. Phase 5 extras (later)

- **Sentry**: create two projects (`po-dashboard-api`, `po-dashboard-web`); set
  `SENTRY_DSN` as a Railway variable and `VITE_SENTRY_DSN` in Pages.
- **Uptime**: a Cloudflare Health Check or an UptimeRobot monitor on
  `https://api.garfieldproduce.com/health`.
- **`pg_cron`**: SQL to schedule the materialized-view refresh (added with the
  views in Phase 5).

---

## Secret inventory (where each value lives)

Env-var name in **bold**. "Railway" = the API service's Variables tab.

| Value | GitHub Actions (pipeline) | Railway (API) | Cloudflare Pages (SPA) |
|---|:---:|:---:|:---:|
| Supabase **session pooler** URL (`:5432`) | ✅ **DATABASE_URL** | ✅ **DATABASE_URL** | |
| Supabase project URL | ✅ (doc_capture) | ✅ **SUPABASE_URL** *(token verification + Storage)* | ✅ **VITE_SUPABASE_URL** |
| Supabase publishable / `anon` key | | | ✅ **VITE_SUPABASE_PUBLISHABLE_KEY** (or **_ANON_KEY**) |
| Supabase secret / `service_role` key | ✅ (doc_capture) | ✅ **SUPABASE_SECRET_KEY** (or **_SERVICE_KEY**) — optional, Storage only | |
| Supabase legacy JWT secret | | ✅ **SUPABASE_JWT_SECRET** — only if the project still signs HS256 | |
| Backend public URL | | | ✅ **VITE_API_BASE** = `https://api.garfieldproduce.com` |
| Frontend public URL | | ✅ **ALLOWED_ORIGINS** + **FRONTEND_BASE** = `https://dashboard.garfieldproduce.com` | |
| `ANTHROPIC_API_KEY` | ✅ | — (API doesn't call Claude) | |
| `GMAIL_CLIENT_ID` / `_SECRET` | ✅ | ✅ (connect flow) | |
| `GMAIL_REDIRECT_URI` | | ✅ = `https://api.garfieldproduce.com/auth/gmail/callback` | |
| `QBO_CLIENT_ID` / `_SECRET` | ✅ | ✅ (connect flow) | |
| `QBO_REDIRECT_URI` | | ✅ = `https://api.garfieldproduce.com/auth/qbo/callback` | |
| `QBO_ENVIRONMENT` | ✅ | ✅ (`production`) | |
| `SLACK_WEBHOOK_URL` | ✅ *(optional — run notifications, see §3.2)* | | |

Minimum to boot the API: **DATABASE_URL** + a token-verification path — either
**SUPABASE_URL** (asymmetric JWT signing keys, verified via JWKS; the current
model) or **SUPABASE_JWT_SECRET** (legacy HS256). The frontend only ever holds
public-safe values (Supabase URL + publishable/`anon` key + the API base);
everything sensitive stays server-side. Legacy `anon` / `service_role` keys and
the shared JWT secret remain valid until **end of 2026**. Full local template:
`backend/.env.example`, `web/.env.example`.
