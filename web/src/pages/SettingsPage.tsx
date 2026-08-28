import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import {
  useConnect,
  useConnections,
  useDisconnect,
  useQboSyncNow,
  type ConnectionsStatus,
} from "@/api/connections";

const CALLBACK_MESSAGES: Record<string, { color: string; text: string }> = {
  qbo_ok: { color: "green", text: "QuickBooks connected." },
  gmail_ok: { color: "green", text: "Gmail connected." },
  qbo_error: { color: "red", text: "QuickBooks connection failed — try again." },
  gmail_error: { color: "red", text: "Gmail connection failed — try again." },
  qbo_state_mismatch: { color: "red", text: "QuickBooks: security check failed — start the connection again." },
  gmail_state_mismatch: { color: "red", text: "Gmail: security check failed — start the connection again." },
};

export function SettingsPage() {
  const { data, isLoading, error } = useConnections();
  const [sp, setSp] = useSearchParams();
  const callback = sp.get("connect");

  useEffect(() => {
    if (callback) {
      const t = setTimeout(() => {
        sp.delete("connect");
        setSp(sp, { replace: true });
      }, 6000);
      return () => clearTimeout(t);
    }
  }, [callback, sp, setSp]);

  return (
    <Stack gap="lg" maw={720}>
      <Title order={2}>Settings &amp; Connections</Title>

      {callback && CALLBACK_MESSAGES[callback] && (
        <Alert color={CALLBACK_MESSAGES[callback].color} variant="light">
          {CALLBACK_MESSAGES[callback].text}
        </Alert>
      )}

      {error && (
        <Alert color="red" title="Couldn't load connections">
          {(error as Error).message}
        </Alert>
      )}
      {isLoading && <Loader />}

      {data && (
        <>
          <QboCard qbo={data.qbo} />
          <GmailCard gmail={data.gmail} />
        </>
      )}
    </Stack>
  );
}

function QboCard({ qbo }: { qbo: ConnectionsStatus["qbo"] }) {
  const connect = useConnect("qbo");
  const disconnect = useDisconnect("qbo");
  const syncNow = useQboSyncNow();

  return (
    <Card withBorder radius="md" p="lg">
      <Group justify="space-between" mb="xs">
        <Title order={4}>QuickBooks</Title>
        {qbo ? (
          <Badge color="green" variant="light">
            Connected · {qbo.environment}
          </Badge>
        ) : (
          <Badge color="gray" variant="light">
            Not connected
          </Badge>
        )}
      </Group>

      {qbo ? (
        <Stack gap={6}>
          <Text size="sm" c="dimmed">
            Realm <code>{qbo.realm_id}</code>
            {qbo.last_synced_at ? ` · last sync ${qbo.last_synced_at.slice(0, 16).replace("T", " ")}` : " · never synced"}
          </Text>
          {qbo.auto_sync_error && (
            <Alert color="red" variant="light">
              Daily auto-sync is failing: {qbo.auto_sync_error}
            </Alert>
          )}
          {qbo.auto_synced_at && !qbo.auto_sync_error && (
            <Text size="xs" c="dimmed">
              Auto-sync last ran {qbo.auto_synced_at.slice(0, 16).replace("T", " ")} UTC
            </Text>
          )}
          <Group mt="xs">
            <Button size="xs" onClick={() => syncNow.mutate(false)} loading={syncNow.isPending}>
              Sync now
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={() => syncNow.mutate(true)}
              loading={syncNow.isPending}
            >
              Full resync
            </Button>
            <Button size="xs" color="red" variant="subtle" onClick={() => disconnect.mutate()}>
              Disconnect
            </Button>
          </Group>
          {syncNow.data && (
            <Text size="xs" c="dimmed">
              Synced {syncNow.data.items} catalog items, {syncNow.data.synced} invoices
              {syncNow.data.deleted ? `, removed ${syncNow.data.deleted}` : ""}.
            </Text>
          )}
          {syncNow.error && (
            <Text size="xs" c="red">
              {(syncNow.error as Error).message}
            </Text>
          )}
        </Stack>
      ) : (
        <Button size="xs" onClick={() => connect.mutate()} loading={connect.isPending}>
          Connect to QuickBooks
        </Button>
      )}
    </Card>
  );
}

function GmailCard({ gmail }: { gmail: ConnectionsStatus["gmail"] }) {
  const connect = useConnect("gmail");
  const disconnect = useDisconnect("gmail");

  return (
    <Card withBorder radius="md" p="lg">
      <Group justify="space-between" mb="xs">
        <Title order={4}>Gmail ingestion</Title>
        {gmail ? (
          <Badge color="green" variant="light">
            Connected
          </Badge>
        ) : (
          <Badge color="gray" variant="light">
            Not connected
          </Badge>
        )}
      </Group>

      {gmail ? (
        <Stack gap={6}>
          <Text size="sm" c="dimmed">
            {gmail.email_address}
            {gmail.last_synced_at
              ? ` · last scan ${gmail.last_synced_at.slice(0, 16).replace("T", " ")}`
              : " · never scanned"}
          </Text>
          <Text size="xs" c="dimmed">
            Extraction runs on a schedule (GitHub Actions). This just holds the mailbox token.
          </Text>
          <Group mt="xs">
            <Button size="xs" color="red" variant="subtle" onClick={() => disconnect.mutate()}>
              Disconnect
            </Button>
          </Group>
        </Stack>
      ) : (
        <Button size="xs" onClick={() => connect.mutate()} loading={connect.isPending}>
          Connect Gmail
        </Button>
      )}
    </Card>
  );
}
