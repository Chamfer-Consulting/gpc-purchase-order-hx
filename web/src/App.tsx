import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import { LoginPage } from "@/auth/LoginPage";
import { RequireAuth } from "@/auth/RequireAuth";
import { OverviewPage } from "@/pages/OverviewPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { Placeholder } from "@/pages/Placeholder";
import { KitchenSink } from "@/pages/KitchenSink";

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
                    <Route path="/customers" element={<AnalyticsPage name="customers" title="Customer 360" />} />
                    <Route path="/products" element={<AnalyticsPage name="products" title="Products & Sizes" />} />
                    <Route path="/explore" element={<AnalyticsPage name="explore" title="Explore" />} />
                    <Route path="/lifecycle" element={<AnalyticsPage name="lifecycle" title="Order Lifecycle" />} />
                    <Route path="/data-quality" element={<Placeholder name="Data Quality" phase={P3} />} />
                    <Route path="/match" element={<Placeholder name="Match & Reconcile" phase={P3} />} />
                    <Route path="/review" element={<Placeholder name="Extraction Review" phase={P3} />} />
                    <Route path="/settings" element={<SettingsPage />} />
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
