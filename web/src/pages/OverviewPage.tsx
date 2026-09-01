import { usePage } from "@/api/pages";
import { useFilterOptions } from "@/api/filterOptions";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";
import { pageMeta } from "@/nav";

export function OverviewPage() {
  const { data, isLoading, error, refetch } = usePage("overview");
  const { data: opts } = useFilterOptions();
  const meta = pageMeta("/")!;

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
