import { Select, Stack } from "@mantine/core";
import type { DataTableColumn } from "mantine-datatable";
import type { Psm, PsmColumnFilters, PsmFacets } from "./api";
import { ProteinAccessions } from "./ProteinAccessions";
import {
  PsmChoiceColumnFilter,
  PsmRangeColumnFilter,
  PsmTextColumnFilter
} from "./PsmColumnFilters";

interface Props {
  filters: PsmColumnFilters;
  facets: PsmFacets;
  grouping: string;
  onChange: (changes: Partial<PsmColumnFilters>) => void;
}

/** Give each column a home for its cell rendering and domain-appropriate filter. */
export class PsmColumns {
  /** Pair each cell value with its filter UI and backend sort accessor. */
  static build({ filters, facets, grouping, onChange }: Props): DataTableColumn<Psm>[] {
    return [
      {
        accessor: "fraction",
        title: "Fraction",
        sortable: true,
        width: 115,
        render: (row) => row.fraction || "Unresolved",
        filtering: !!filters.fractions.length,
        filter: (
          <PsmChoiceColumnFilter
            label="Fractions"
            values={filters.fractions}
            choices={facets.fractions}
            onChange={(fractions) => onChange({ fractions })}
          />
        )
      },
      {
        accessor: "sequence",
        title: "Sequence",
        sortable: true,
        width: 235,
        ellipsis: true,
        render: (row) => <span title={row.sequence}>{row.sequence}</span>,
        filtering: !!filters.sequence.value,
        filter: (
          <PsmTextColumnFilter
            label="Peptide sequence"
            value={filters.sequence}
            onChange={(sequence) => onChange({ sequence })}
          />
        )
      },
      {
        accessor: "proteins",
        title: "Proteins",
        sortable: true,
        width: 180,
        cellsClassName: "protein-cell",
        render: (row) => (
          <ProteinAccessions
            accessions={row.protein_accessions}
            grouping={row.protein_groupings?.find((value) => value.name === grouping)}
          />
        ),
        filtering: !!filters.proteins.value,
        filter: (
          <PsmTextColumnFilter
            label="Protein accession"
            value={filters.proteins}
            onChange={(proteins) => onChange({ proteins })}
          />
        )
      },
      {
        accessor: "native",
        title: "Scan",
        sortable: true,
        width: 300,
        ellipsis: true,
        render: (row) => <span title={row.native}>{row.native}</span>,
        filtering: !!filters.native.value,
        filter: (
          <PsmTextColumnFilter
            label="Native scan ID"
            value={filters.native}
            onChange={(native) => onChange({ native })}
          />
        )
      },
      {
        accessor: "precursor_mz",
        title: "Precursor m/z",
        sortable: true,
        width: 170,
        render: (row) => (
          <span
            title={
              row.precursor_mz == null
                ? "No precursor m/z available"
                : `${row.precursor_mz} m/z · ${row.precursor_mz_origin || "origin unavailable"}`
            }
          >
            {row.precursor_mz == null ? "—" : row.precursor_mz.toFixed(5)}
          </span>
        ),
        filtering: filters.precursor_mz_min != null || filters.precursor_mz_max != null,
        filter: (
          <PsmRangeColumnFilter
            label="precursor m/z"
            lower={filters.precursor_mz_min}
            upper={filters.precursor_mz_max}
            nonnegative
            onChange={(precursor_mz_min, precursor_mz_max) =>
              onChange({ precursor_mz_min, precursor_mz_max })
            }
          />
        )
      },
      {
        accessor: "rt",
        title: "RT (min)",
        sortable: true,
        width: 130,
        render: (row) => (row.rt == null ? "—" : (row.rt / 60).toFixed(2)),
        filtering: filters.rt_min != null || filters.rt_max != null,
        filter: (
          <PsmRangeColumnFilter
            label="RT (min)"
            lower={filters.rt_min}
            upper={filters.rt_max}
            nonnegative
            onChange={(rt_min, rt_max) => onChange({ rt_min, rt_max })}
          />
        )
      },
      {
        accessor: "layer",
        title: "Layer",
        sortable: true,
        width: 145,
        filtering: !!filters.layers.length,
        filter: (
          <PsmChoiceColumnFilter
            label="Identification layers"
            values={filters.layers}
            choices={facets.layers.map((value) => ({ value, label: value }))}
            onChange={(layers) => onChange({ layers })}
          />
        )
      },
      {
        accessor: "score",
        title: "Score",
        sortable: true,
        width: 125,
        render: (row) => <span title={row.score_type}>{row.score.toPrecision(3)}</span>,
        filtering:
          filters.score_min != null || filters.score_max != null || !!filters.score_type,
        filter: (
          <Stack gap="sm">
            <Select
              label="Score type"
              value={filters.score_type}
              comboboxProps={{ withinPortal: false }}
              data={[
                { value: "", label: "All score types" },
                ...facets.score_types.map((value) => ({ value, label: value }))
              ]}
              onChange={(value) => onChange({ score_type: value || "" })}
            />
            <PsmRangeColumnFilter
              label="score"
              lower={filters.score_min}
              upper={filters.score_max}
              onChange={(score_min, score_max) => onChange({ score_min, score_max })}
              onClear={() =>
                onChange({ score_min: null, score_max: null, score_type: "" })
              }
            />
          </Stack>
        )
      },
      {
        accessor: "resolved",
        title: "Link",
        sortable: true,
        width: 125,
        render: (row) => (
          <span title={row.link_reason || ""}>
            {row.resolved ? "Resolved" : "Unresolved"}
          </span>
        ),
        filtering: !!filters.link,
        filter: (
          <Select
            label="Link status"
            value={filters.link}
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
            data={[
              { value: "", label: "All" },
              { value: "resolved", label: "Resolved" },
              { value: "unresolved", label: "Unresolved" }
            ]}
            onChange={(value) =>
              onChange({
                link: value === "resolved" || value === "unresolved" ? value : ""
              })
            }
          />
        )
      }
    ];
  }
}
