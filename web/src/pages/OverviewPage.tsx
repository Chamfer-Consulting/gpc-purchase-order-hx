import { useQuery } from "@tanstack/react-query";
import { Alert, Group, SimpleGrid, Skeleton, Text, Title } from "@mantine/core";
import { apiGet } from "@/lib/api";

interface Kpi {
  label: string;
  value: number;
}
interface OverviewResponse {
  _stub?: boolean;
  kpis: Kpi[];
  series: unknown[];
}

export function OverviewPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["overview"],
    queryFn: () => apiGet<OverviewResponse>("/api/overview"),
  });

  return (
    <>
      <Title order={2} mb="md">
        Overview
      </Title>

      {error && (
        <Alert color="red" title="Couldn't load">
          {(error as Error).message}
        </Alert>
      )}

      {isLoading ? (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} h={90} radius="md" />
          ))}
        </SimpleGrid>
      ) : (
        <>
          {data?._stub && (
            <Text size="sm" c="dimmed" mb="sm">
              Stub response — real KPIs + charts land in Phase 1.
            </Text>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
            {data?.kpis.map((k) => (
              <div
                key={k.label}
                style={{
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: 10,
                  padding: 16,
                }}
              >
                <Text size="xs" c="dimmed" tt="uppercase">
                  {k.label}
                </Text>
                <Text fw={600} fz={26} style={{ fontVariantNumeric: "tabular-nums" }}>
                  {k.value.toLocaleString()}
                </Text>
              </div>
            ))}
          </SimpleGrid>
        </>
      )}

      <Group mt="xl">
        <Text size="sm" c="dimmed">
          Charts render here via the shared ECharts theme (Phase 2 §2.1).
        </Text>
      </Group>
    </>
  );
}
