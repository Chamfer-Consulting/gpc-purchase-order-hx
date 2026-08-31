import { useLocation } from "react-router-dom";
import { usePage, type PageName } from "@/api/pages";
import { useFilterOptions } from "@/api/filterOptions";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";
import { pageMeta } from "@/nav";

/** Generic analytics page: PageLayout + FilterBar + whatever the endpoint returns. */
export function AnalyticsPage({ name, title }: { name: PageName; title: string }) {
  const { pathname } = useLocation();
  const { data, isLoading, error, refetch } = usePage(name);
  const { data: opts } = useFilterOptions();
  const meta = pageMeta(pathname);

  return (
    <PageLayout
      title={meta?.title ?? title}
      description={meta?.description}
      breadcrumbs={meta?.breadcrumbs}
      filterBar={
        <FilterBar
          customerOptions={opts?.customers ?? []}
          productOptions={opts?.products ?? []}
          sizeOptions={opts?.sizes ?? []}
          viewKind={name}
        />
      }
      loading={isLoading && !data}
      error={data ? undefined : error}
      onRetry={() => void refetch()}
    >
      {data && <PageRenderer data={data} />}
    </PageLayout>
  );
}
