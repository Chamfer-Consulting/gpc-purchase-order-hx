import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anon) {
  // Fail loud in dev; a missing anon key otherwise looks like an auth bug later.
  console.error("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set — see web/.env.example");
}

export const supabase = createClient(url, anon, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
