import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useDebouncedValue } from "@mantine/hooks";
import { IconChevronDown, IconChevronRight, IconSearch } from "@tabler/icons-react";
import dayjs from "dayjs";
import { useAuditLog, useAuditOptions, type AuditFilters, type AuditRow } from "@/api/audit";
import { useMe } from "@/api/me";
import { PageLayout } from "@/components/PageLayout";
import { QueryBoundary } from "@/components/ErrorState";
import { SectionCard } from "@/components/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { pageMeta } from "@/nav";

const iso = (d: Date | null) => (d ? dayjs(d).format("YYYY-MM-DD") : undefined);

const SOURCE_LABEL: Record<string, string> = {
  admin: "admin",
  auth: "auth",
  pipeline: "pipeline",
  review: "review",
};
const SOURCE_COLOR: Record<string, string> = {
  admin: "gpGreen",
  auth: "blue",
  pipeline: "cyan",
  review: "grape",
};

function titleCase(s: string) {
  return s.replace(/[_-]+/g, " ");
}

/** "Where" — entity + id, linked when we have a page for it. */
function EntityCell({ row }: { row: AuditRow }) {
  const { entity, entity_id } = row;
  const label = titleCase(entity);
  if (entity === "purchase_order" && entity_id) {
    return (
      <Group gap={4} wrap="nowrap">
        <Text size="xs" c="dimmed">
          PO
        </Text>
        <Anchor component={Link} to={`/po/${entity_id}`} size="xs">
          {entity_id}
        </Anchor>
      </Group>
    );
  }
  return (
    <Text size="xs">
      {label}
      {entity_id ? (
        <Text span c="dimmed">
          {" "}
          · <span title={entity_id}>{entity_id.length > 28 ? `${entity_id.slice(0, 27)}…` : entity_id}</span>
        </Text>
      ) : null}
    </Text>
  );
}

function DetailRow({ row }: { row: AuditRow }) {
  const dump = (v: unknown) =>
    v == null ? "—" : JSON.stringify(v, null, 2);
  return (
    <Table.Tr>
      <Table.Td colSpan={6} style={{ background: "var(--gp-surface-sunken)" }}>
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" p="xs">
          <div>
            <Text size="xs" fw={600} c="dimmed" mb={4}>
              Before
            </Text>
            <Code block fz="xs">
              {dump(row.before)}
            </Code>
          </div>
          <div>
            <Text size="xs" fw={600} c="dimmed" mb={4}>
              After
            </Text>
            <Code block fz="xs">
              {dump(row.after)}
            </Code>
          </div>
        </SimpleGrid>
      </Table.Td>
    </Table.Tr>
  );
}

function AuditTable({ rows }: { rows: AuditRow[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  if (rows.length === 0) return <EmptyState label="No matching activity" compact />;

  return (
    <Table.ScrollContainer minWidth={820} type="native">
      <Table fz="xs" highlightOnHover verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={140}>When</Table.Th>
            <Table.Th w={200}>Who</Table.Th>
            <Table.Th w={190}>What</Table.Th>
            <Table.Th>Where</Table.Th>
            <Table.Th>Why</Table.Th>
            <Table.Th w={32} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r) => {
            const isOpen = open.has(r.id);
            return (
              <Fragment key={r.id}>
                <Table.Tr style={{ cursor: "pointer" }} onClick={() => toggle(r.id)}>
                  <Table.Td>{r.at?.slice(0, 16).replace("T", " ") ?? "—"}</Table.Td>
                  <Table.Td>
                    <Text size="xs" truncate maw={190} title={r.actor ?? undefined}>
                      {r.actor ?? "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <Badge size="xs" variant="light">
                        {titleCase(r.action)}
                      </Badge>
                      <Badge size="xs" variant="dot" color={SOURCE_COLOR[r.source] ?? "gray"}>
                        {SOURCE_LABEL[r.source] ?? r.source}
                      </Badge>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <EntityCell row={r} />
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" truncate maw={280} title={r.reason ?? undefined}>
                      {r.reason ?? "—"}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      variant="subtle"
                      size="sm"
                      aria-label={isOpen ? "Hide details" : "Show details"}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle(r.id);
                      }}
                    >
                      {isOpen ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
                {isOpen && <DetailRow row={r} />}
              </Fragment>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function AuditPage() {
  const meta = pageMeta("/audit")!;
  const { canAdmin, roleKnown } = useMe();

  const [source, setSource] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [entity, setEntity] = useState<string | null>(null);
  const [qInput, setQInput] = useState("");
  const [q] = useDebouncedValue(qInput, 300);
  const [range, setRange] = useState<[Date | null, Date | null]>([null, null]);

  const filters: AuditFilters = useMemo(
    () => ({
      source: source ?? undefined,
      action: action ?? undefined,
      entity: entity ?? undefined,
      q: q.trim() || undefined,
      since: iso(range[0]),
      until: iso(range[1]),
    }),
    [source, action, entity, q, range],
  );

  const { data, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage, error, refetch } =
    useAuditLog(filters);
  const options = useAuditOptions();
  const rows = data?.pages.flatMap((p) => p.rows) ?? [];

  if (roleKnown && !canAdmin) {
    return (
      <PageLayout title={meta.title} description={meta.description} breadcrumbs={meta.breadcrumbs}>
        <Alert color="gray" variant="light" title="Admin access required">
          The audit history is only available to admins.
        </Alert>
      </PageLayout>
    );
  }

  return (
    <PageLayout title={meta.title} description={meta.description} breadcrumbs={meta.breadcrumbs}>
      <SectionCard
        title="Activity"
        subtitle={
          isLoading
            ? undefined
            : `${rows.length} event${rows.length === 1 ? "" : "s"}${hasNextPage ? "+ (load more below)" : ""}`
        }
      >
        <Stack gap="md">
          <Group gap="sm" align="flex-end" wrap="wrap">
            <TextInput
              label="Search"
              placeholder="person, entity, reason…"
              leftSection={<IconSearch size={14} />}
              size="xs"
              w={240}
              value={qInput}
              onChange={(e) => setQInput(e.currentTarget.value)}
            />
            <Select
              label="Source"
              size="xs"
              w={140}
              clearable
              data={options.data?.sources ?? []}
              value={source}
              onChange={setSource}
            />
            <Select
              label="Action"
              size="xs"
              w={160}
              clearable
              searchable
              data={options.data?.actions ?? []}
              value={action}
              onChange={setAction}
            />
            <Select
              label="Entity"
              size="xs"
              w={170}
              clearable
              searchable
              data={options.data?.entities ?? []}
              value={entity}
              onChange={setEntity}
            />
            <DatePickerInput
              type="range"
              label="Date range"
              size="xs"
              w={230}
              clearable
              value={range}
              onChange={setRange}
            />
          </Group>

          <QueryBoundary loading={isLoading} error={error} onRetry={() => void refetch()}>
            <AuditTable rows={rows} />
            {hasNextPage && (
              <Group justify="center">
                <Button
                  size="xs"
                  variant="default"
                  loading={isFetchingNextPage}
                  onClick={() => void fetchNextPage()}
                >
                  Load more
                </Button>
              </Group>
            )}
          </QueryBoundary>
        </Stack>
      </SectionCard>
    </PageLayout>
  );
}
