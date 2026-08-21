# Gmail API setup — for the cloud extraction pipeline

One-time setup so the app can read your labeled PO emails (attachments and body
text) on your behalf — via OAuth, the same "click Connect, approve access" flow
already used for QuickBooks, not a stored password. This only covers getting
Google Cloud + the OAuth client ready; the in-app "Connect Gmail" button and the
extraction pipeline itself are separate work.

## 0. Before you start

- You need access to the **same Google Cloud project** already used for the Drive
  service account (`gdrive_service_account` in your secrets) — or a new one, if
  you'd rather keep this separate. Either works; reusing the existing project means
  one less thing to track.
- Decide whether your Gmail account is a **Google Workspace** account (business
  domain, e.g. `you@yourcompany.com` managed by an admin) or a **personal**
  `@gmail.com` account — it changes one choice in step 2 below.
- Have your dashboard's URL(s) handy — the same one(s) already set as
  `qbo_redirect_uri` in `.streamlit/secrets.toml` (typically
  `http://localhost:8501/` for local dev, plus your `*.streamlit.app` URL once
  deployed).

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
- **Authorized redirect URIs**: add the *exact* same URL(s) you're already using
  for `qbo_redirect_uri` — e.g. `http://localhost:8501/` for local dev, and your
  production Streamlit Cloud URL (e.g. `https://your-app.streamlit.app/`). Google
  matches this exactly (trailing slash and all), so copy it rather than retyping.
- **Create**. Google shows a **Client ID** and **Client secret** — copy both now;
  the secret isn't shown again (you can always generate a new one from this same
  Credentials page if you lose it).

## 4. Save the credentials

Add to `.streamlit/secrets.toml` (and the same keys in Streamlit Community Cloud's
App Settings → Secrets, once deployed):

```toml
gmail_client_id = "...apps.googleusercontent.com"
gmail_client_secret = "..."
gmail_redirect_uri = "http://localhost:8501/"  # same value as qbo_redirect_uri
```

(`.streamlit/secrets.toml` is gitignored — never commit real values. These three
keys will also need to go into GitHub Actions repo secrets later, alongside
`ANTHROPIC_API_KEY` and `DATABASE_URL`, for the scheduled/manual extraction job —
that wiring comes in a later step, not part of this guide.)

## 5. Configured labels (GMAIL_LABELS)

Pulled directly via the Gmail API (through the dashboard's ✉️ Email Ingestion page,
after connecting) rather than hand-typed, so nested names with apostrophes/parens
are byte-exact. This is the current `GMAIL_LABELS` value — a comma-separated list
of exact label names, one per customer:

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
plain environment variables, not Streamlit secrets, so these need to be added as
**repo secrets** (Settings → Secrets and variables → Actions → New repository
secret) separately from everything in `.streamlit/secrets.toml`:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key — **only** needed here, the dashboard never calls Claude |
| `DATABASE_URL` | Same Neon connection string as the `database_url` Streamlit secret |
| `GMAIL_CLIENT_ID` | Same value as the `gmail_client_id` Streamlit secret |
| `GMAIL_CLIENT_SECRET` | Same value as the `gmail_client_secret` Streamlit secret |
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
