import { useParams } from "react-router-dom";
import { useCustomerDetail } from "@/api/customers";
import { useFilterOptions } from "@/api/filterOptions";
import { PageLayout } from "@/components/PageLayout";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";

export function CustomerDetailPage() {
  const { name: raw } = useParams();
  const name = raw ? decodeURIComponent(raw) : undefined;
  const { data, isLoading, error, refetch } = useCustomerDetail(name);
  const { data: opts } = useFilterOptions();

  return (
    <PageLayout
      title={name ?? "Customer"}
      description="Revenue, ordering cadence, and product & size mix for one account."
      breadcrumbs={[{ label: "Customers", to: "/customers" }, { label: name ?? "" }]}
      filterBar={
        <FilterBar
          hideCustomers
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
