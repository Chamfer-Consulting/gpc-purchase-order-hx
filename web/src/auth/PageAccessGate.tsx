import type { ReactNode } from "react";
import { Alert } from "@mantine/core";
import { useMe } from "@/api/me";
import { PageLayout } from "@/components/PageLayout";
import { pageMeta } from "@/nav";

/** Wraps a route that's in nav.tsx's externalViewable set. Every other role
 *  (viewer and up, plus 'field' — though 'field' never reaches this route
 *  tree at all) renders `children` unchanged. An external_viewer only
 *  renders them if the admin granted this exact page (Settings -> Team);
 *  otherwise a friendly "restricted" message, matching this app's existing
 *  adminOnly-page pattern, rather than letting the page's own API calls
 *  fail with a raw 403. Sits inside AccountGate, so useMe() is already
 *  resolved here — no separate loading guard needed. */
export function PageAccessGate({ pageKey, children }: { pageKey: string; children: ReactNode }) {
  const { role, externalPages } = useMe();

  if (role !== "external_viewer" || externalPages.includes(pageKey)) {
    return <>{children}</>;
  }

  const meta = pageMeta(pageKey);
  return (
    <PageLayout title={meta?.title ?? "Restricted"} breadcrumbs={meta?.breadcrumbs}>
      <Alert color="gray" variant="light" title="Access restricted">
        You don't have access to this page. Ask an admin to grant it if you need it.
      </Alert>
    </PageLayout>
  );
}
