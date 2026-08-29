import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import { LoginPage } from "@/auth/LoginPage";
import { RequireAuth } from "@/auth/RequireAuth";
import { OverviewPage } from "@/pages/OverviewPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { ExplorePage } from "@/pages/ExplorePage";
import { DataQualityPage } from "@/pages/DataQualityPage";
import { MatchPage } from "@/pages/MatchPage";
import { ReviewPage } from "@/pages/ReviewPage";
import { EditPoPage } from "@/pages/EditPoPage";
import { NewPoPage } from "@/pages/NewPoPage";
import { ArchivePage } from "@/pages/ArchivePage";
import { PricingPage } from "@/pages/PricingPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { KitchenSink } from "@/pages/KitchenSink";

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
                    <Route path="/explore" element={<ExplorePage />} />
                    <Route path="/lifecycle" element={<AnalyticsPage name="lifecycle" title="Order Lifecycle" />} />
                    <Route path="/data-quality" element={<DataQualityPage />} />
                    <Route path="/pricing" element={<PricingPage />} />
                    <Route path="/match" element={<MatchPage />} />
                    <Route path="/review" element={<ReviewPage />} />
                    <Route path="/po/new" element={<NewPoPage />} />
                    <Route path="/po/:id" element={<EditPoPage />} />
                    <Route path="/archive" element={<ArchivePage />} />
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
