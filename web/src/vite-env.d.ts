/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  /** 2025+ key model — preferred */
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  /** legacy anon key — fallback, valid until end of 2026 */
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_API_BASE: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
