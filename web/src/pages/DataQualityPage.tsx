import { Alert, Loader, Stack, Title } from "@mantine/core";
import { useDataQuality } from "@/api/quality";
import { PageRenderer } from "@/components/PageRenderer";

export function DataQualityPage() {
  const { data, isLoading, error } = useDataQuality();
  return (
    <Stack gap="md">
      <Title order={2}>Data Quality</Title>
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
