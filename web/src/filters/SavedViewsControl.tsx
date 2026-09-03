import { Button, Group, Select } from "@mantine/core";
import { useDeleteView, useSaveView, useSavedViews } from "@/api/settings";
import { useFilters, type Filters } from "./useFilters";

/**
 * A compact saved-views control for the FilterBar: pick a saved view to apply it,
 * "Save view" to store the current scope under a name, "Delete" to drop one.
 * `kind` scopes the list to a page (e.g. "customers"). `stacked` (the mobile
 * drawer) restores the field label and lets the select go full-width.
 */
export function SavedViewsControl({ kind, stacked = false }: { kind: string; stacked?: boolean }) {
  const { filters, setFilters } = useFilters();
  const { data: views = [] } = useSavedViews<Filters>(kind);
  const saveView = useSaveView();
  const deleteView = useDeleteView(kind);

  function apply(name: string | null) {
    const v = views.find((x) => x.name === name);
    if (v) setFilters(v.config);
  }

  function save() {
    const name = window.prompt("Save this scope as:");
    if (!name?.trim()) return;
    saveView.mutate({ kind, name: name.trim(), config: filters as unknown as Record<string, unknown> });
  }

  return (
    <Group gap={4} align="center">
      <Select
        label={stacked ? "Saved views" : undefined}
        size="xs"
        w={stacked ? "100%" : 150}
        data={views.map((v) => v.name)}
        placeholder={views.length ? "Saved view" : "None saved"}
        onChange={apply}
        clearable
        searchable
      />
      <Button size="xs" variant="default" onClick={save} loading={saveView.isPending}>
        Save view
      </Button>
      {views.length > 0 && (
        <Button
          size="xs"
          variant="subtle"
          color="red"
          onClick={() => {
            const name = window.prompt("Delete which saved view? (exact name)");
            if (name?.trim()) deleteView.mutate(name.trim());
          }}
        >
          Delete
        </Button>
      )}
    </Group>
  );
}
