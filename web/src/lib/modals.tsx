import { useState, type ReactNode } from "react";
import { Button, Group, Stack, Text, Textarea } from "@mantine/core";
import { modals } from "@mantine/modals";

/** Themed replacement for window.confirm on destructive actions. */
export function confirmAction(opts: {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmColor?: string;
  onConfirm: () => void;
}) {
  modals.openConfirmModal({
    title: opts.title,
    children: typeof opts.body === "string" ? <Text size="sm">{opts.body}</Text> : opts.body,
    labels: { confirm: opts.confirmLabel ?? "Confirm", cancel: opts.cancelLabel ?? "Cancel" },
    confirmProps: { color: opts.confirmColor ?? "red" },
    onConfirm: opts.onConfirm,
  });
}

/** Themed replacement for window.prompt — collects an optional/required reason. */
export function promptReason(opts: {
  title: string;
  description?: ReactNode;
  label?: string;
  placeholder?: string;
  confirmLabel?: string;
  confirmColor?: string;
  required?: boolean;
  onSubmit: (reason: string | null) => void;
}) {
  const id = "gp-reason-modal";

  function Body() {
    const [v, setV] = useState("");
    return (
      <Stack>
        {opts.description &&
          (typeof opts.description === "string" ? (
            <Text size="sm">{opts.description}</Text>
          ) : (
            opts.description
          ))}
        <Textarea
          label={opts.label ?? "Reason"}
          placeholder={opts.placeholder}
          value={v}
          onChange={(e) => setV(e.currentTarget.value)}
          autosize
          minRows={2}
          data-autofocus
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={() => modals.close(id)}>
            Cancel
          </Button>
          <Button
            color={opts.confirmColor}
            disabled={opts.required && !v.trim()}
            onClick={() => {
              opts.onSubmit(v.trim() || null);
              modals.close(id);
            }}
          >
            {opts.confirmLabel ?? "Save"}
          </Button>
        </Group>
      </Stack>
    );
  }

  modals.open({ modalId: id, title: opts.title, children: <Body /> });
}
