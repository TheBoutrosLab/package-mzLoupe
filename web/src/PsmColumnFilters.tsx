import { useEffect, useState } from "react";
import {
  Button,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  TextInput
} from "@mantine/core";
import type { PsmTextFilter } from "./api";

interface TextProps {
  label: string;
  value: PsmTextFilter;
  onChange: (value: PsmTextFilter) => void;
}

/** Match literal peptide, scan, or accession text with explicit contains/exact semantics. */
export function PsmTextColumnFilter({ label, value, onChange }: TextProps) {
  return (
    <Stack gap="sm">
      <TextInput
        label={label}
        value={value.value}
        onChange={(event) => onChange({ ...value, value: event.currentTarget.value })}
      />
      <Select
        label="Match"
        value={value.mode}
        allowDeselect={false}
        comboboxProps={{ withinPortal: false }}
        data={[
          { value: "contains", label: "Contains" },
          { value: "exact", label: "Exactly matches" }
        ]}
        onChange={(mode) =>
          onChange({ ...value, mode: mode === "exact" ? "exact" : "contains" })
        }
      />
      <Button
        variant="subtle"
        onClick={() => onChange({ ...value, value: "" })}
      >
        Clear column
      </Button>
    </Stack>
  );
}

interface ChoiceProps {
  label: string;
  values: string[];
  choices: { value: string; label: string }[];
  onChange: (values: string[]) => void;
}

/** Choose any number of values from the complete table scope, not its current page. */
export function PsmChoiceColumnFilter({ label, values, choices, onChange }: ChoiceProps) {
  return (
    <Stack gap="sm">
      <MultiSelect
        label={label}
        placeholder={values.length ? "Add another" : "All"}
        searchable
        clearable
        value={values}
        data={choices}
        comboboxProps={{ withinPortal: false }}
        onChange={onChange}
      />
      <Button
        variant="subtle"
        onClick={() => onChange([])}
      >
        Clear column
      </Button>
    </Stack>
  );
}

interface RangeProps {
  label: string;
  lower: number | null;
  upper: number | null;
  nonnegative?: boolean;
  onClear?: () => void;
  onChange: (lower: number | null, upper: number | null) => void;
}

/** Adapt editable number strings without dropping trailing zeros or incomplete input. */
export class PsmNumericFilter {
  /** Empty or incomplete edits omit the bound; valid decimal strings retain its value. */
  static value(input: number | string): number | null {
    if (input === "") return null;
    const value = Number(input);
    return Number.isFinite(value) ? value : null;
  }
}

/** Inclusive numeric bounds retain zero values and allow either end to be omitted. */
export function PsmRangeColumnFilter({
  label,
  lower,
  upper,
  nonnegative,
  onClear,
  onChange
}: RangeProps) {
  const [minimum, setMinimum] = useState<number | string>(lower ?? "");
  const [maximum, setMaximum] = useState<number | string>(upper ?? "");
  const error = lower != null && upper != null && lower > upper;

  // Parent resets update the inputs, while equivalent edits such as 400.70
  // retain the user's text rather than jumping to 400.7 mid-entry.
  useEffect(() => {
    setMinimum((current) =>
      PsmNumericFilter.value(current) === lower ? current : (lower ?? "")
    );
  }, [lower]);
  useEffect(() => {
    setMaximum((current) =>
      PsmNumericFilter.value(current) === upper ? current : (upper ?? "")
    );
  }, [upper]);

  /** Reset editable text along with the numeric query conditions. */
  function clear() {
    setMinimum("");
    setMaximum("");
    if (onClear) onClear();
    else onChange(null, null);
  }

  return (
    <Stack gap="sm">
      <Group
        grow
        align="start"
      >
        <NumberInput
          label={`Minimum ${label}`}
          value={minimum}
          allowNegative={!nonnegative}
          hideControls
          error={error ? "Minimum exceeds maximum" : undefined}
          onChange={(value) => {
            setMinimum(value);
            onChange(PsmNumericFilter.value(value), upper);
          }}
        />
        <NumberInput
          label={`Maximum ${label}`}
          value={maximum}
          allowNegative={!nonnegative}
          hideControls
          onChange={(value) => {
            setMaximum(value);
            onChange(lower, PsmNumericFilter.value(value));
          }}
        />
      </Group>
      <Button
        variant="subtle"
        onClick={clear}
      >
        Clear column
      </Button>
    </Stack>
  );
}
