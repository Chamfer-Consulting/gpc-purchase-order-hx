import { createClient } from "@supabase/supabase-js";

// Supabase's 2025 key model: the publishable key (sb_publishable_...) replaces
// the legacy anon key for browser/public use. Both work until end of 2026 —
// prefer the publishable key, fall back to anon.
const url = import.meta.env.VITE_SUPABASE_URL;
const key =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !key) {
  // Fail loud in dev; a missing key otherwise looks like an auth bug later.
  console.error(
    "VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY (or VITE_SUPABASE_ANON_KEY) are not set — see web/.env.example",
  );
}

export const supabase = createClient(url ?? "", key ?? "", {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
