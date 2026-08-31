import { useDataQuality } from "@/api/quality";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { pageMeta } from "@/nav";

export function DataQualityPage() {
  const { data, isLoading, error, refetch } = useDataQuality();
  const meta = pageMeta("/data-quality")!;

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
