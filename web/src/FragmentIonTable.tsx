import { useState } from "react";
import { Button, Group } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import type { DataTableSortStatus } from "mantine-datatable";
import type { AcquisitionMode } from "./api";
import { FragmentIons } from "./FragmentIons";
import { FragmentIonColumns } from "./FragmentIonColumns";
import type { FragmentIon, FragmentSortColumn } from "./FragmentIons";
import type { FragmentSelection } from "./useFragmentSelection";

interface Props {
  mode?: AcquisitionMode;
  fragments: FragmentSelection;
}

/** Inspect matched spectrum assignments and choose the DIA traces to display. */
export function FragmentIonTable({ mode, fragments }: Props) {
  const [query, setQuery] = useState("");
  const [charge, setCharge] = useState<string | null>(null);
  const [sort, setSort] = useState<DataTableSortStatus<FragmentIon>>({
    columnAccessor: "intensity",
    direction: "desc"
  });
  const dia = mode === "DIA";
  const matching = fragments.rows.filter(
    (ion) =>
      ion.label.toLowerCase().includes(query.trim().toLowerCase()) &&
      (!charge || ion.charge === Number(charge))
  );
  const records = FragmentIons.sort(
    matching,
    sort.columnAccessor as FragmentSortColumn,
    sort.direction
  );
  const columns = FragmentIonColumns.build({
    dia,
    fragments,
    query,
    charge,
    setQuery,
    setCharge
  });

  return (
    <section
      className="fragment-table"
      aria-label="Fragment ions"
    >
      <Group
        className="fragment-table-heading"
        justify="space-between"
      >
        <h3>Fragment ions</h3>
        {dia && (
          <Group gap={0}>
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={fragments.selectTop}
            >
              Top 6
            </Button>
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={fragments.selectAll}
            >
              All matched
            </Button>
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={fragments.clear}
            >
              Clear
            </Button>
          </Group>
        )}
      </Group>
      <p className="caption">
        {matching.length} of {fragments.rows.length} matched assignments
        {dia && ` · ${fragments.selected.size} selected for XIC`}. Measurements are from
        the selected spectrum.
      </p>
      <DataTable<FragmentIon>
        height={300}
        minHeight={120}
        records={records}
        columns={columns}
        idAccessor="id"
        highlightOnHover
        sortStatus={sort}
        onSortStatusChange={setSort}
        rowClassName={(ion) => (ion.id === fragments.focused ? "selected" : undefined)}
        noRecordsText="No matched fragment ions"
        defaultColumnProps={{ filterPopoverProps: { width: 240, withinPortal: true } }}
      />
    </section>
  );
}
