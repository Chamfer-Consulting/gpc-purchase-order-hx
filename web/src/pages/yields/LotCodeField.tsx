import { Text, TextInput, type MantineSize } from "@mantine/core";

/** Lot code editor that locks the product's own short-code prefix (e.g.
 *  "TK") as a fixed, non-editable decoration — the identifier tying a lot
 *  code back to its product must never be hand-edited away, whether
 *  logging a new harvest or correcting one later. Only the part after the
 *  prefix (whatever the harvester writes to tell today's batch apart) is
 *  ever editable; typing there can never touch the prefix, since it isn't
 *  part of the editable value at all. Falls back to a fully free-text
 *  field when the product has no prefix configured — nothing to lock in
 *  that case. */
export function LotCodeField({
  prefix,
  value,
  onChange,
  size,
  description,
}: {
  prefix: string;
  value: string;
  onChange: (value: string) => void;
  size?: MantineSize;
  description?: string;
}) {
  // Falls back to a plain free-text field whenever locking the prefix
  // would risk corrupting the value, not just when there's no prefix to
  // lock: an existing entry's stored lot code might not actually start
  // with the product's *current* prefix (the prefix was changed after
  // this entry was logged, or the code predates this feature) — forcing
  // the split UI there would silently prepend the new prefix onto the old
  // text the moment anyone typed a single character.
  if (!prefix || (value !== "" && !value.startsWith(prefix))) {
    return (
      <TextInput
        label="Lot code"
        description={description}
        value={value}
        onChange={(e) => onChange(e.currentTarget.value)}
        size={size}
      />
    );
  }

  const suffix = value.slice(prefix.length);

  return (
    <TextInput
      label="Lot code"
      description={description}
      value={suffix}
      onChange={(e) => onChange(prefix + e.currentTarget.value)}
      leftSection={
        <Text size="sm" fw={700} c="dimmed" style={{ whiteSpace: "nowrap" }}>
          {prefix}
        </Text>
      }
      leftSectionWidth={Math.max(36, prefix.length * 9 + 20)}
      size={size}
      // The prefix is fixed and shown separately (never part of this
      // value), so the only thing ever typed here is the harvester's own
      // batch/date digits — the same reasoning Weight's numeric keypad
      // already uses.
      inputMode="numeric"
    />
  );
}
