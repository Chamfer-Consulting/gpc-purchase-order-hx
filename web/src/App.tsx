import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuthProvider } from "@/auth/AuthProvider";
import { LoginPage } from "@/auth/LoginPage";
import { AuthCallback } from "@/auth/AuthCallback";
import { RequireAuth } from "@/auth/RequireAuth";
import { AccountGate } from "@/auth/AccountGate";
import { PageAccessGate } from "@/auth/PageAccessGate";
import { useMe } from "@/api/me";
import { KioskShell } from "@/kiosk/KioskShell";
import { HarvestEntryPage } from "@/pages/yields/HarvestEntryPage";
import { MyRecentEntriesPage } from "@/pages/yields/MyRecentEntriesPage";
import { YieldsAdminPage } from "@/pages/yields/YieldsAdminPage";
import { YieldsEntriesPage } from "@/pages/yields/YieldsEntriesPage";
import { YieldsImportPage } from "@/pages/yields/YieldsImportPage";
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
        <Route path="/" element={<PageAccessGate pageKey="/"><OverviewPage /></PageAccessGate>} />
        <Route
          path="/customers"
          element={<PageAccessGate pageKey="/customers"><AnalyticsPage name="customers" title="Customers" /></PageAccessGate>}
        />
        <Route
          path="/customers/:name"
          element={<PageAccessGate pageKey="/customers"><CustomerDetailPage /></PageAccessGate>}
        />
        <Route
          path="/products"
          element={<PageAccessGate pageKey="/products"><AnalyticsPage name="products" title="Products & Sizes" /></PageAccessGate>}
        />
        <Route path="/explore" element={<PageAccessGate pageKey="/explore"><ExplorePage /></PageAccessGate>} />
        <Route
          path="/lifecycle"
          element={<PageAccessGate pageKey="/lifecycle"><AnalyticsPage name="lifecycle" title="Order Lifecycle" /></PageAccessGate>}
        />
        <Route path="/data-quality" element={<DataQualityPage />} />
        <Route path="/pricing" element={<PageAccessGate pageKey="/pricing"><PricingPage /></PageAccessGate>} />
        <Route path="/reconcile" element={<ReconcilePage />} />
        <Route path="/reconcile/:poId" element={<ReconcilePage />} />
        <Route path="/match" element={<Navigate to="/reconcile" replace />} />
        <Route path="/review" element={<Navigate to="/reconcile" replace />} />
        <Route path="/po/new" element={<NewPoPage />} />
        <Route path="/po/:id" element={<EditPoPage />} />
        <Route path="/archive" element={<ArchivePage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/yields" element={<PageAccessGate pageKey="/yields"><YieldsTrendsPage /></PageAccessGate>} />
        {/* Log Harvest and Notes moved into the Entries page (a button and a
         *  tab, respectively) — redirect any bookmarked/old links there. */}
        <Route path="/yields/log" element={<Navigate to="/yields/entries" replace />} />
        <Route path="/yields/notes" element={<Navigate to="/yields/entries" replace />} />
        <Route
          path="/yields/entries"
          element={<PageAccessGate pageKey="/yields/entries"><YieldsEntriesPage /></PageAccessGate>}
        />
        <Route path="/yields/admin" element={<YieldsAdminPage />} />
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
