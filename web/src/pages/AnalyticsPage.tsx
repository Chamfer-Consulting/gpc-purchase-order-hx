import { Alert, Loader, Stack, Title } from "@mantine/core";
import { usePage, type PageName } from "@/api/pages";
import { PageRenderer } from "@/components/PageRenderer";
import { FilterBar } from "@/filters/FilterBar";

/** Generic analytics page: title + FilterBar + whatever the endpoint returns. */
export function AnalyticsPage({ name, title }: { name: PageName; title: string }) {
  const { data, isLoading, error } = usePage(name);

  return (
    <Stack gap="md">
      <Title order={2}>{title}</Title>
      <FilterBar />

      {error && (
        <Alert color="red" title="Couldn't load">
          {(error as Error).message}
        </Alert>
      )}
      {isLoading && <Loader />}
      {data && <PageRenderer data={data} />}
    </Stack>
  );
}
