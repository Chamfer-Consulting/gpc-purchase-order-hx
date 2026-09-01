import { useDataQuality } from "@/api/quality";
import { useFilterOptions } from "@/api/filterOptions";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";
import { pageMeta } from "@/nav";

export function DataQualityPage() {
  const { data, isLoading, error, refetch } = useDataQuality();
  const { data: opts } = useFilterOptions();
  const meta = pageMeta("/data-quality")!;

  return (
    <PageLayout
      title={meta.title}
      description={meta.description}
      breadcrumbs={meta.breadcrumbs}
      filterBar={
        <FilterBar
          customerOptions={opts?.customers ?? []}
          productOptions={opts?.products ?? []}
          sizeOptions={opts?.sizes ?? []}
        />
      }
      loading={isLoading && !data}
      error={error && !data ? error : undefined}
      onRetry={() => void refetch()}
    >
      {data && <PageRenderer data={data} />}
    </PageLayout>
  );
}
