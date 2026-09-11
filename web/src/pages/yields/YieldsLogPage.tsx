import { Alert } from "@mantine/core";
import { useMe } from "@/api/me";
import { PageLayout } from "@/components/PageLayout";
import { pageMeta } from "@/nav";
import { HarvestEntryForm } from "./HarvestEntryForm";

/** Office-side harvest logging — the same form the field kiosk uses, just in
 *  the normal app shell. Admin-only for now (see routers/yields.py's notes
 *  section for the matching backend note; entry creation itself stays open
 *  to any role at the API since the kiosk's 'field' role needs it too — this
 *  page's visibility is a frontend-only restriction while both role sides
 *  are being tested). */
export function YieldsLogPage() {
  const meta = pageMeta("/yields/log");
  const { canAdmin, roleKnown } = useMe();

  if (roleKnown && !canAdmin) {
    return (
      <PageLayout title={meta?.title ?? "Log harvest"} description={meta?.description} breadcrumbs={meta?.breadcrumbs}>
        <Alert color="gray" variant="light" title="Admin access required">
          Logging a harvest from the office is only available to admins for now — use the field kiosk otherwise.
        </Alert>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      title={meta?.title ?? "Log harvest"}
      description={meta?.description ?? "The same form the field kiosk uses."}
      breadcrumbs={meta?.breadcrumbs}
      width="form"
    >
      <HarvestEntryForm />
    </PageLayout>
  );
}
