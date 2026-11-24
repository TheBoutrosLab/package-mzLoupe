import { useEffect, useState } from "react";
import { Alert, Button, Group, Select, Text } from "@mantine/core";
import { DataTable } from "mantine-datatable";
import type {
  Acquisition,
  Psm,
  PsmColumnFilters,
  PsmPage,
  ProteinGroupingSummary,
  PsmSortColumn
} from "./api";
import { apiClient } from "./api";
import { useApiRequest } from "./useApiRequest";
import { PsmColumns } from "./PsmColumns";
import { PsmTableQuery } from "./PsmTableQuery";
import type { PsmTableRequest } from "./PsmTableQuery";

interface Props {
  token: string;
  sample: string;
  source: string;
  layer: string;
  acquisitions: Acquisition[];
  groupings: ProteinGroupingSummary[];
  selectedId?: number;
  onSelect: (psm: Psm) => void;
}

/** Own table queries independently of spectrum selection and linked plot state. */
export function PsmTable({
  token,
  sample,
  source,
  layer,
  acquisitions,
  groupings,
  selectedId,
  onSelect
}: Props) {
  const [query, setQuery] = useState(() => PsmTableQuery.initial(layer));
  const [grouping, setGrouping] = useState<string>();
  const [results, setResults] = useState<PsmPage>({
    rows: [],
    total: 0,
    peptides: 0,
    page: 0,
    page_size: 50,
    facets: { fractions: [], layers: [], score_types: [] }
  });
  const { run: loadPage, cancel: cancelPage, loading: busy, error } = useApiRequest();
  const validation = PsmTableQuery.error(query.filters);
  const filteredColumns = PsmTableQuery.activeCount(query.filters);
  const availableGroupings = groupings.filter(
    (row) =>
      (!row.samples.length || row.samples.includes(sample)) &&
      (!row.layers.length ||
        !query.filters.layers.length ||
        row.layers.some((value) => query.filters.layers.includes(value)))
  );
  const activeGrouping =
    grouping === ""
      ? ""
      : availableGroupings.find((row) => row.name === grouping)?.name ||
        availableGroupings[0]?.name ||
        "";
  const fraction = acquisitions.find((row) => row.id === source)?.fraction;

  // Following a PSM into another fraction retains filters but starts at page one.
  useEffect(() => {
    setQuery((current) => ({ ...current, page: 1 }));
  }, [source]);

  // The global layer seeds the column filter; users can add layers or clear it.
  useEffect(() => {
    setQuery((current) => ({
      ...current,
      page: 1,
      filters: { ...current.filters, layers: layer ? [layer] : [] }
    }));
  }, [layer]);

  // Debounce edits and cancel obsolete responses. Filtering/sorting never selects
  // a row or asks the raw-data service to refresh a spectrum or chromatogram.
  useEffect(() => {
    if (!token || !sample || (query.scope === "fraction" && !source) || validation)
      return;
    const timer = setTimeout(() => {
      const parameters = PsmTableQuery.parameters(query, sample, source, activeGrouping);
      loadPage<PsmPage>({
        url: apiClient.projectUrl(token) + "/psms?" + parameters,
        onSuccess: (value) => {
          setResults(value);
          if (value.page + 1 !== query.page) {
            setQuery((current) => ({ ...current, page: value.page + 1 }));
          }
        }
      });
    }, 180);
    return () => {
      clearTimeout(timer);
      cancelPage();
    };
  }, [token, sample, source, query, activeGrouping, validation, loadPage, cancelPage]);

  /** Every changed condition restarts pagination before the next request. */
  function change(changes: Partial<PsmTableRequest>) {
    setQuery((current) => ({ ...current, page: 1, ...changes }));
  }

  /** Combine independent columns without replacing the rest of the filter state. */
  function changeFilters(changes: Partial<PsmColumnFilters>) {
    setQuery((current) => ({
      ...current,
      page: 1,
      filters: { ...current.filters, ...changes }
    }));
  }

  return (
    <section className="panel results">
      <div className="panel-title">
        <div>
          <h2>Peptide-spectrum matches</h2>
          <span>
            {results.total} candidates · {results.peptides} distinct peptide sequences ·{" "}
            {query.scope === "fraction" ? fraction : "All sample fractions"}
          </span>
        </div>
        <Group>
          <Select
            aria-label="PSM scope"
            value={query.scope}
            allowDeselect={false}
            data={[
              { value: "fraction", label: "Active fraction" },
              { value: "sample", label: "All sample fractions" }
            ]}
            onChange={(value) =>
              change({ scope: value === "sample" ? "sample" : "fraction" })
            }
          />
          {!!availableGroupings.length && (
            <Select
              aria-label="Protein grouping view"
              value={activeGrouping}
              allowDeselect={false}
              data={[
                { value: "", label: "Original peptide mappings" },
                ...availableGroupings.map((row) => ({ value: row.name, label: row.name }))
              ]}
              onChange={(value) => {
                setGrouping(value ?? "");
                change({});
              }}
            />
          )}
        </Group>
      </div>
      <Group
        className="psm-filter-summary"
        justify="space-between"
      >
        <Text size="xs">
          {filteredColumns} filtered {filteredColumns === 1 ? "column" : "columns"}
        </Text>
        <Button
          size="xs"
          variant="subtle"
          disabled={!filteredColumns}
          onClick={() => change({ filters: PsmTableQuery.filters() })}
        >
          Clear filters
        </Button>
      </Group>
      {(error || validation) && <Alert color="red">{validation || error}</Alert>}
      <DataTable<Psm>
        className="psm-datatable"
        height={480}
        minHeight={180}
        highlightOnHover
        fetching={busy && !validation}
        records={results.rows}
        idAccessor="id"
        columns={PsmColumns.build({
          filters: query.filters,
          facets: results.facets,
          grouping: activeGrouping,
          onChange: changeFilters
        })}
        defaultColumnProps={{
          filterPopoverProps: { width: 320, withinPortal: true, returnFocus: true }
        }}
        rowClassName={(row) => (row.id === selectedId ? "selected" : undefined)}
        onRowClick={({ record }) => onSelect(record)}
        sortStatus={query.sort}
        onSortStatusChange={(sort) =>
          change({
            sort: {
              columnAccessor: sort.columnAccessor as PsmSortColumn,
              direction: sort.direction
            }
          })
        }
        page={query.page}
        onPageChange={(page) => setQuery((current) => ({ ...current, page }))}
        totalRecords={results.total}
        recordsPerPage={query.pageSize}
        recordsPerPageOptions={[25, 50, 100, 200]}
        onRecordsPerPageChange={(pageSize) => change({ pageSize })}
        recordsPerPageLabel="Rows per page"
        noRecordsText="No matching PSMs."
        loadingText="Updating PSMs…"
        getPaginationControlProps={(control) => ({ "aria-label": `${control} page` })}
      />
    </section>
  );
}
