import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import { LoginPage } from "@/auth/LoginPage";
import { RequireAuth } from "@/auth/RequireAuth";
import { OverviewPage } from "@/pages/OverviewPage";
import { Placeholder } from "@/pages/Placeholder";
import { KitchenSink } from "@/pages/KitchenSink";

const P2 = "Phase 2 — read-only pages";
const P3 = "Phase 3 — interactive pages";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AppShell>
                  <Routes>
                    <Route path="/" element={<OverviewPage />} />
                    <Route path="/customers" element={<Placeholder name="Customer 360" phase={P2} />} />
                    <Route path="/products" element={<Placeholder name="Products & Sizes" phase={P2} />} />
                    <Route path="/explore" element={<Placeholder name="Explore" phase={P2} />} />
                    <Route path="/lifecycle" element={<Placeholder name="Order Lifecycle" phase={P2} />} />
                    <Route path="/data-quality" element={<Placeholder name="Data Quality" phase={P3} />} />
                    <Route path="/match" element={<Placeholder name="Match & Reconcile" phase={P3} />} />
                    <Route path="/review" element={<Placeholder name="Extraction Review" phase={P3} />} />
                    <Route path="/settings" element={<Placeholder name="Settings & Connections" phase={P3} />} />
                    <Route path="/_kitchen-sink" element={<KitchenSink />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </AppShell>
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
