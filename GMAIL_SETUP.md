# Gmail API setup — for the cloud extraction pipeline

One-time setup so the app can read your labeled PO emails (attachments and body
text) on your behalf — via OAuth, the same "click Connect, approve access" flow
already used for QuickBooks, not a stored password. This only covers getting
Google Cloud + the OAuth client ready; the in-app "Connect Gmail" button and the
extraction pipeline itself are separate work.

## 0. Before you start

- You need a **Google Cloud project** for the OAuth client. Any project works; a
  dedicated one keeps this app's credentials easy to find.
- Decide whether your Gmail account is a **Google Workspace** account (business
  domain, e.g. `you@yourcompany.com` managed by an admin) or a **personal**
  `@gmail.com` account — it changes one choice in step 2 below.
- Have the backend's OAuth callback URL(s) handy — `http://localhost:8000/auth/gmail/callback`
  for local dev, plus `https://<railway-domain>/auth/gmail/callback` once deployed
  (the `GMAIL_REDIRECT_URI` value; see `docs/REBUILD-SETUP.md` §4).

## 1. Enable the Gmail API

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and select
   the project (top-left project switcher).
2. Left menu → **APIs & Services** → **Library**.
3. Search "**Gmail API**" → open it → **Enable**.

## 2. Configure the OAuth consent screen

Left menu → **APIs & Services** → **OAuth consent screen**.

- **User type**:
  - **Internal** — if this is a Google Workspace account and you're an admin (or
    the domain allows it). Simplest option: no verification needed, no test-user
    cap, tokens don't expire for being "unverified." Only people on your Workspace
    domain can ever connect, which is fine since it's just you.
  - **External** — if it's a personal `@gmail.com` account. Set **Publishing
    status** to **Testing** (not "In production") and add your own email under
    **Test users** — this avoids Google's app-verification process entirely for a
    single-user internal tool like this.
- **App name / support email / developer contact**: anything reasonable — this
  screen is only ever shown to you.
- **Scopes**: add `https://www.googleapis.com/auth/gmail.readonly` (search
  "Gmail API" in the scope picker, or paste the scope directly under "Manually add
  scopes"). Read-only is all this needs — nothing sends, modifies, or deletes mail.
- Save through to the end of the wizard.

> **If you chose External + Testing**: Google's testing mode is meant for active
> development, not a background job that runs unattended for months. Watch for
> the refresh token being invalidated after a period of inactivity or after ~7
> days if the consent screen sits in Testing status — if the scheduled GitHub
> Action starts failing with an auth error after it's been running fine for a
> while, re-clicking "Connect Gmail" in the dashboard is the fix. If that gets
> annoying, moving the app to **In production** (still fine, still unverified,
> Google just shows an "unverified app" warning screen you click through once)
> generally makes refresh tokens longer-lived. Full verification (removing that
> warning) needs a public privacy policy URL and a home page — usually not worth
> it for a single-user internal tool.

## 3. Create the OAuth client

Left menu → **APIs & Services** → **Credentials** → **Create Credentials** →
**OAuth client ID**.

- **Application type**: **Web application**.
- **Name**: anything, e.g. "GPC PO Dashboard — Gmail".
- **Authorized redirect URIs**: add the backend's Gmail callback URL exactly —
  `http://localhost:8000/auth/gmail/callback` for local dev, and
  `https://<railway-domain>/auth/gmail/callback` once deployed. Google matches this
  exactly, so copy it rather than retyping.
- **Create**. Google shows a **Client ID** and **Client secret** — copy both now;
  the secret isn't shown again (you can always generate a new one from this same
  Credentials page if you lose it).

## 4. Save the credentials

The backend reads these from its environment (`backend/.env` locally, Railway
Variables in prod — see `backend/.env.example`):

```bash
GMAIL_CLIENT_ID=...apps.googleusercontent.com
GMAIL_CLIENT_SECRET=...
GMAIL_REDIRECT_URI=http://localhost:8000/auth/gmail/callback
```

Never commit real values (`.env` files are gitignored). `GMAIL_CLIENT_ID` /
`GMAIL_CLIENT_SECRET` also go into GitHub Actions repo secrets for the scheduled
extraction job (§6).

## 5. Configured labels (GMAIL_LABELS)

Pulled directly via the Gmail API rather than hand-typed, so nested names with
apostrophes/parens are byte-exact. This is the current `GMAIL_LABELS` value — a
comma-separated list of exact label names, one per customer:

```
1. Customers/Anthony Marano's (AMC),1. Customers/Get Fresh Produce,1. Customers/Hillside Food Pantry,1. Customers/Inspiration Corporation,1. Customers/Local Foods,1. Customers/Marillac House (Tramaine & Holly),1. Customers/Midwest Foods,1. Customers/Post Marketplace,1. Customers/Restaurants,1. Customers/Skoufis Foodservice,1. Customers/Testa Produce,1. Customers/The Original Pancake House,1. Customers/The Urban Canopy,1. Customers/UChicago,1. Customers/Village Farm Stand,1. Customers/West Suburban Community Pantry
```

`1. Customers/Restaurants` is a catch-all for small one-off/few-time sales (pre-2023) —
not a single customer. Its messages are still included, but `run_cloud_extraction.py`
never treats *that particular* label's name as a customer-identity hint the way it
implicitly could for the others (relevant only to its delta-revision context lookup —
see the `_process_message` docstring).

Adding a new customer later: add their label to this list, update the
`GMAIL_LABELS` GitHub Actions secret (see below), and run a manual
`workflow_dispatch` with **Full backlog scan** checked to pull their history —
otherwise the incremental cursor would only pick up messages from that point
forward.

## 6. GitHub Actions secrets (automatic + manual runs)

The extraction script itself (`run_cloud_extraction.py`) runs via
`.github/workflows/extract_pos.yml` — a scheduled job (daily, edit the `cron:` line
to change cadence) plus a manual `workflow_dispatch` trigger (repo's **Actions**
tab → the workflow → **Run workflow**, with a **Full backlog scan** checkbox; or
`gh workflow run extract_pos.yml -f full_backlog=true` from a terminal). It reads
plain environment variables, so these need to be added as **repo secrets**
(Settings → Secrets and variables → Actions → New repository secret):

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key — **only** needed here; the API never calls Claude |
| `DATABASE_URL` | The Supabase **session** connection string (`:5432`) |
| `GMAIL_CLIENT_ID` | From the Google Cloud OAuth client (§3) |
| `GMAIL_CLIENT_SECRET` | From the Google Cloud OAuth client (§3) |
| `GMAIL_LABELS` | The comma-separated value from step 5 above |

Note there's no `GMAIL_REDIRECT_URI` here — the Action only refreshes an
already-issued token (via `gmail_client.get_valid_access_token`), it never does the
interactive authorize-redirect step, which only the dashboard's Connect flow needs.

## Troubleshooting

- **"Access blocked: this app's request is invalid"** — usually a redirect URI
  that doesn't exactly match what's registered in step 3. Check for a missing/extra
  trailing slash or `http` vs `https`.
- **"Google hasn't verified this app"** warning on the consent screen — expected
  for an External/Testing or unverified Production app. Click **Advanced** → **Go
  to \[app name\] (unsafe)** to proceed; this is safe since it's your own app.
- **`invalid_grant` / `Token has been expired or revoked`** during a later
  automated run — the refresh token was invalidated (see the Testing-mode note in
  step 2, or the user revoked access under
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)).
  Fix: reconnect via the dashboard's "Connect Gmail" button.
- **Can't find "Gmail API" in the Library search** — double check you're in the
  right Cloud project (top-left switcher); API enablement is per-project.
