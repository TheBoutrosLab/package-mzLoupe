import { useEffect, useRef, useState } from "react";
import { Button, MultiSelect, Select, Table, TextInput } from "@mantine/core";
import type { GroupCollection } from "./api";
import { useApiRequest } from "./useApiRequest";
import { ProjectDraft, ProteinGroupingRow, RowIssue } from "./ProjectDraft";
import { FilePicker } from "./FilePicker";

const labels = {
  protein_groups: "Protein groups",
  indistinguishable_proteins: "Indistinguishable proteins"
};
type Counts = Record<GroupCollection, number>;

interface Props {
  draft: ProjectDraft;
  issues: RowIssue[];
  onChange: (draft: ProjectDraft) => void;
}

/** Stage inference inputs independently of sample/fraction acquisition files. */
export function ProteinGroupingTable({ draft, issues, onChange }: Props) {
  return (
    <section className="panel protein-grouping-panel">
      <div className="panel-title">
        <h2>Protein grouping</h2>
        <Button onClick={() => onChange(draft.addGrouping())}>
          Add protein grouping
        </Button>
      </div>
      <div className="source-table grouping-table">
        <Table>
          <Table.Thead>
            <Table.Tr>
              {[
                "Name",
                "Grouping idXML",
                "Group collection",
                "Samples",
                "Identification layers",
                ""
              ].map((label) => (
                <Table.Th key={label}>{label}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {draft.groupings.map((row) => (
              <GroupingRowEditor
                key={row.id}
                row={row}
                draft={draft}
                issues={issues}
                onUpdate={(changes) => onChange(draft.withGrouping(row.id, changes))}
                onRemove={() => onChange(draft.removeGrouping(row.id))}
              />
            ))}
          </Table.Tbody>
        </Table>
        {!draft.groupings.length && (
          <p className="table-empty">Optionally load protein inference results.</p>
        )}
      </div>
    </section>
  );
}

interface RowProps extends Omit<Props, "onChange"> {
  row: ProteinGroupingRow;
  onUpdate: (changes: Partial<ProteinGroupingRow>) => void;
  onRemove: () => void;
}

/** Inspect a path once per edit and require a choice when both collections exist. */
function GroupingRowEditor({ row, draft, issues, onUpdate, onRemove }: RowProps) {
  const update = useRef(onUpdate);
  update.current = onUpdate;
  const [counts, setCounts] = useState<Counts>();
  const [error, setError] = useState("");
  const [browsing, setBrowsing] = useState(false);
  const { run: inspectFile, cancel: cancelInspection } = useApiRequest();

  useEffect(() => {
    setCounts(undefined);
    setError("");
    if (!row.path.trim()) return;
    const timer = setTimeout(() => {
      inspectFile<Counts>({
        url: "/api/protein-groupings/inspect",
        options: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: row.path.trim() })
        },
        onSuccess: (value) => {
          setCounts(value);
          const available = (Object.keys(labels) as GroupCollection[]).filter(
            (key) => value[key] > 0
          );
          if (available.length === 1) update.current({ collection: available[0] });
          if (!available.length) setError("This idXML contains no protein groups.");
        },
        onError: (failure) => setError(failure.message)
      });
    }, 350);
    return () => {
      clearTimeout(timer);
      cancelInspection();
    };
  }, [row.path, inspectFile, cancelInspection]);

  /** Resolve field validation while keeping file parsing errors beside the path. */
  function issue(field: string) {
    return issues.find((value) => value.id === row.id && value.field === field)?.message;
  }

  return (
    <Table.Tr>
      <Table.Td>
        <TextInput
          aria-label={`Grouping name for ${row.id}`}
          value={row.name}
          error={issue("name")}
          onChange={(event) => onUpdate({ name: event.currentTarget.value })}
        />
      </Table.Td>
      <Table.Td>
        <div className="source-path">
          <TextInput
            aria-label={`Grouping idXML path for ${row.id}`}
            value={row.path}
            error={error || issue("path")}
            onChange={(event) => onUpdate({ path: event.currentTarget.value })}
          />
          <Button
            variant="subtle"
            onClick={() => setBrowsing(true)}
          >
            Browse
          </Button>
        </div>
        <FilePicker
          kind="idxml"
          opened={browsing}
          multiple={false}
          onClose={() => setBrowsing(false)}
          onChoose={(paths) => onUpdate({ path: paths[0] })}
        />
      </Table.Td>
      <Table.Td>
        <Select
          aria-label={`Group collection for ${row.id}`}
          placeholder={
            row.path && !counts && !error ? "Inspecting file…" : "Choose collection"
          }
          value={row.collection || null}
          allowDeselect={false}
          error={issue("collection")}
          data={(Object.keys(labels) as GroupCollection[]).map((key) => ({
            value: key,
            label: counts ? `${labels[key]} (${counts[key]})` : labels[key],
            disabled: !counts || !counts[key]
          }))}
          onChange={(value) => onUpdate({ collection: value as GroupCollection })}
        />
      </Table.Td>
      <Table.Td>
        <MultiSelect
          aria-label={`Grouping samples for ${row.id}`}
          placeholder={row.samples.length ? "Add sample" : "All samples"}
          data={draft.sampleNames()}
          value={row.samples}
          error={issue("samples")}
          onChange={(samples) => onUpdate({ samples })}
          clearable
        />
      </Table.Td>
      <Table.Td>
        <MultiSelect
          aria-label={`Grouping layers for ${row.id}`}
          placeholder={row.layers.length ? "Add layer" : "All layers"}
          data={draft.groupingLayers(row.samples)}
          value={row.layers}
          error={issue("layers")}
          onChange={(layers) => onUpdate({ layers })}
          clearable
        />
      </Table.Td>
      <Table.Td>
        <Button
          variant="subtle"
          color="red"
          onClick={onRemove}
        >
          Remove
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}
