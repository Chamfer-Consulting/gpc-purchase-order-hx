import { Button, Group, Select } from "@mantine/core";
import { useDeleteView, useSaveView, useSavedViews } from "@/api/settings";
import { useFilters, type Filters } from "./useFilters";

/**
 * A compact saved-views control for the FilterBar: pick a saved view to apply it,
 * "Save view" to store the current scope under a name, "×" to delete the applied
 * one. `kind` scopes the list to a page (e.g. "customers").
 */
export function SavedViewsControl({ kind }: { kind: string }) {
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
    <Group gap={4} align="flex-end">
      <Select
        label="Saved views"
        size="xs"
        w={170}
        data={views.map((v) => v.name)}
        placeholder={views.length ? "Apply a view" : "None saved"}
        onChange={apply}
        clearable
        searchable
      />
      <Button size="xs" variant="default" mb={1} onClick={save} loading={saveView.isPending}>
        Save view
      </Button>
      {views.length > 0 && (
        <Button
          size="xs"
          variant="subtle"
          color="red"
          mb={1}
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
