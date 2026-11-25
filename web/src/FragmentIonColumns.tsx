import { Checkbox, Group, Select, TextInput, UnstyledButton } from "@mantine/core";
import type { DataTableColumn } from "mantine-datatable";
import { FragmentIons } from "./FragmentIons";
import type { FragmentIon } from "./FragmentIons";
import type { FragmentSelection } from "./useFragmentSelection";

interface Context {
  dia: boolean;
  fragments: FragmentSelection;
  query: string;
  charge: string | null;
  setQuery: (value: string) => void;
  setCharge: (value: string | null) => void;
}

/** Keep spectrum measurements and DIA visibility controls in one column definition. */
export class FragmentIonColumns {
  /** Build columns without owning table state or changing fragment selections. */
  static build({
    dia,
    fragments,
    query,
    charge,
    setQuery,
    setCharge
  }: Context): DataTableColumn<FragmentIon>[] {
    const columns: DataTableColumn<FragmentIon>[] = [];
    if (dia) {
      columns.push({
        accessor: "show",
        title: "XIC",
        width: 48,
        render: (ion) => (
          <Checkbox
            aria-label={`Show ${ion.label} XIC`}
            checked={fragments.selected.has(ion.id)}
            color={FragmentIons.color(ion)}
            onChange={() => fragments.toggle(ion.id)}
          />
        )
      });
    }
    columns.push(
      {
        accessor: "label",
        title: "Ion",
        sortable: true,
        width: 90,
        filter: (
          <TextInput
            label="Find fragment ion"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        ),
        filtering: Boolean(query),
        render: (ion) => (
          <Group
            gap={5}
            wrap="nowrap"
          >
            <span
              className="fragment-color"
              style={{ backgroundColor: FragmentIons.color(ion) }}
            />
            <UnstyledButton
              className="fragment-label"
              aria-label={`Highlight ${ion.label}`}
              aria-pressed={fragments.focused === ion.id}
              onClick={() => fragments.focus(ion.id)}
            >
              {ion.label}
            </UnstyledButton>
            {ion.peakAssignments > 1 && (
              <span
                className="fragment-ambiguity"
                title={`This measured peak matches ${ion.peakAssignments} theoretical ions.`}
                aria-label="Ambiguous peak assignment"
              >
                †
              </span>
            )}
          </Group>
        )
      },
      {
        accessor: "charge",
        title: "Charge",
        sortable: true,
        width: 105,
        filter: (
          <Select
            label="Fragment charge"
            clearable
            data={[...new Set(fragments.rows.map((ion) => String(ion.charge)))]}
            value={charge}
            onChange={setCharge}
          />
        ),
        filtering: Boolean(charge)
      },
      {
        accessor: "mz",
        title: <span title="Theoretical fragment m/z used for extraction">m/z</span>,
        sortable: true,
        render: (ion) => <span title={String(ion.mz)}>{ion.mz.toFixed(5)}</span>
      },
      {
        accessor: "ppm",
        title: (
          <span title="Observed minus theoretical mass, from the selected spectrum">
            Error (ppm)
          </span>
        ),
        sortable: true,
        render: (ion) => `${ion.ppm >= 0 ? "+" : ""}${ion.ppm.toFixed(2)}`
      },
      {
        accessor: "intensity",
        title: (
          <span title="Measured intensity in the selected MS2 spectrum">Intensity</span>
        ),
        sortable: true,
        render: (ion) => (
          <span title={String(ion.intensity)}>{ion.intensity.toPrecision(3)}</span>
        )
      }
    );

    return columns;
  }
}
