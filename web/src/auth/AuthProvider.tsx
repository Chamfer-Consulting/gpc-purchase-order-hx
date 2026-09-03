import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  // the user id we've already counted as "signed in" — so a page reload or a
  // token refresh (both re-fire SIGNED_IN in supabase-js) doesn't log a login.
  const knownUser = useRef<string | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      knownUser.current = data.session?.user.id ?? null;
      setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      const uid = s?.user.id ?? null;
      if (event === "SIGNED_IN" && uid && uid !== knownUser.current) {
        void recordActivity("login");
      }
      if (event === "SIGNED_OUT") knownUser.current = null;
      else if (uid) knownUser.current = uid;
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const signOut = async () => {
    // fire while the token is still valid, then actually sign out
    knownUser.current = null;
    await recordActivity("logout");
    await supabase.auth.signOut();
  };

  return (
    <AuthContext.Provider value={{ session, loading, signOut }}>{children}</AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
