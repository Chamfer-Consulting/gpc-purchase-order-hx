import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import { recordActivity } from "@/lib/api";

interface AuthState {
  session: Session | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  session: null,
  loading: true,
  signOut: async () => {},
});

/**
 * Record a "login" in the audit trail at most once per browser tab (the flag is
 * cleared on sign-out, so signing in again in the same tab counts). The backend
 * also dedupes per Supabase session, so a stray extra call is a harmless no-op —
 * this just keeps the network quiet on reloads.
 */
export function pingLoginOnce() {
  try {
    if (sessionStorage.getItem("gp.loginPinged") === "1") return;
    sessionStorage.setItem("gp.loginPinged", "1");
  } catch {
    /* Safari private mode / storage disabled — fall through and just ping */
  }
  void recordActivity("login");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    // SIGNED_IN fires on a real sign-in (password or the OAuth code exchange);
    // INITIAL_SESSION / TOKEN_REFRESHED do not, so a plain reload never pings.
    const { data: sub } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      if (event === "SIGNED_IN" && s) pingLoginOnce();
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const signOut = async () => {
    await recordActivity("logout"); // while the token is still valid
    try {
      sessionStorage.removeItem("gp.loginPinged");
    } catch {
      /* ignore */
    }
    await supabase.auth.signOut();
  };

  return (
    <AuthContext.Provider value={{ session, loading, signOut }}>{children}</AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
