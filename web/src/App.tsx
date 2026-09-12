import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import { LoginPage } from "@/auth/LoginPage";
import { AuthCallback } from "@/auth/AuthCallback";
import { RequireAuth } from "@/auth/RequireAuth";
import { AccountGate } from "@/auth/AccountGate";
import { useMe } from "@/api/me";
import { KioskShell } from "@/kiosk/KioskShell";
import { HarvestEntryPage } from "@/pages/yields/HarvestEntryPage";
import { MyRecentEntriesPage } from "@/pages/yields/MyRecentEntriesPage";
import { YieldsAdminPage } from "@/pages/yields/YieldsAdminPage";
import { YieldsEntriesPage } from "@/pages/yields/YieldsEntriesPage";
import { YieldsImportPage } from "@/pages/yields/YieldsImportPage";
import { YieldsLogPage } from "@/pages/yields/YieldsLogPage";
import { YieldsNotesPage } from "@/pages/yields/YieldsNotesPage";
import { YieldsTrendsPage } from "@/pages/yields/YieldsTrendsPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { ExplorePage } from "@/pages/ExplorePage";
import { CustomerDetailPage } from "@/pages/CustomerDetailPage";
import { DataQualityPage } from "@/pages/DataQualityPage";
import { ReconcilePage } from "@/pages/ReconcilePage";
import { EditPoPage } from "@/pages/EditPoPage";
import { NewPoPage } from "@/pages/NewPoPage";
import { ArchivePage } from "@/pages/ArchivePage";
import { AuditPage } from "@/pages/AuditPage";
import { PricingPage } from "@/pages/PricingPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { KitchenSink } from "@/pages/KitchenSink";

/**
 * Sits inside AccountGate, which already blocks rendering until useMe() has
 * resolved — so `role` here is never the pre-load fallback. A 'field' account
 * (the Product Yields harvest kiosk) gets a completely different, minimal
 * shell and route tree; everyone else gets the full app. This is a UX split
 * only — the real security boundary is the backend's router-level role floor
 * (see backend/app/auth.py's require_viewer), not this branch.
 */
function RoleRouter() {
  const { role } = useMe();

  if (role === "field") {
    return (
      <KioskShell>
        <Routes>
          <Route path="/yields" element={<HarvestEntryPage />} />
          <Route path="/yields/recent" element={<MyRecentEntriesPage />} />
          <Route path="*" element={<Navigate to="/yields" replace />} />
        </Routes>
      </KioskShell>
    );
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/customers" element={<AnalyticsPage name="customers" title="Customers" />} />
        <Route path="/customers/:name" element={<CustomerDetailPage />} />
        <Route path="/products" element={<AnalyticsPage name="products" title="Products & Sizes" />} />
        <Route path="/explore" element={<ExplorePage />} />
        <Route path="/lifecycle" element={<AnalyticsPage name="lifecycle" title="Order Lifecycle" />} />
        <Route path="/data-quality" element={<DataQualityPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/reconcile" element={<ReconcilePage />} />
        <Route path="/reconcile/:poId" element={<ReconcilePage />} />
        <Route path="/match" element={<Navigate to="/reconcile" replace />} />
        <Route path="/review" element={<Navigate to="/reconcile" replace />} />
        <Route path="/po/new" element={<NewPoPage />} />
        <Route path="/po/:id" element={<EditPoPage />} />
        <Route path="/archive" element={<ArchivePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/yields" element={<YieldsTrendsPage />} />
        <Route path="/yields/log" element={<YieldsLogPage />} />
        <Route path="/yields/entries" element={<YieldsEntriesPage />} />
        <Route path="/yields/admin" element={<YieldsAdminPage />} />
        <Route path="/yields/notes" element={<YieldsNotesPage />} />
        <Route path="/yields/import" element={<YieldsImportPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/_kitchen-sink" element={<KitchenSink />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallback />} />
          <Route
            path="/*"
            element={
              <RequireAuth>
                <AccountGate>
                  <RoleRouter />
                </AccountGate>
              </RequireAuth>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
