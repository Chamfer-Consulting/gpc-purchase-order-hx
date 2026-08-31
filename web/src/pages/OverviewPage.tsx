import { usePage } from "@/api/pages";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { pageMeta } from "@/nav";

export function OverviewPage() {
  const { data, isLoading, error, refetch } = usePage("overview");
  const meta = pageMeta("/")!;

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      loading={isLoading && !data}
      error={data ? undefined : error}
      onRetry={() => void refetch()}
    >
      {data && <PageRenderer data={data} />}
    </PageLayout>
  );
}
