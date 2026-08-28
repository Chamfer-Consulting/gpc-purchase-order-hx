# PO Dashboard — web

React + TypeScript SPA (Vite, Mantine, TanStack Query, ECharts, Tremor). Talks to
the FastAPI backend; auth via Supabase.

## Local dev

```bash
cd web
npm install
cp .env.example .env.local     # fill in the three VITE_ values
npm run dev                    # http://localhost:5173
```

The backend must be running (`../backend`, port 8000) and its `ALLOWED_ORIGINS`
must include `http://localhost:5173`.

## Layout

```
src/
  main.tsx           providers: Mantine, TanStack Query
  App.tsx            router + route table (placeholders for un-ported pages)
  lib/
    supabase.ts      Supabase client
    api.ts           fetch wrapper — attaches the Supabase access token
    queryClient.ts   TanStack Query defaults
  auth/              AuthProvider, LoginPage, RequireAuth
  components/        AppShell (nav)
  pages/             OverviewPage (real), Placeholder (everything else)
  charts/            ECharts theme + <Chart> — added in Phase 2 §2.1
```

## Build & deploy

Cloudflare Pages, root directory `web`, build `npm run build`, output `web/dist`.
Env vars (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE`) set in the
Pages project. See `../docs/REBUILD-SETUP.md` §5.
