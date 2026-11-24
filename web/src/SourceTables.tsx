import { Autocomplete, Button, Table, TextInput } from "@mantine/core";
import { ProjectDraft, RowIssue } from "./ProjectDraft";

interface Props {
  draft: ProjectDraft;
  sample: string;
  issues: RowIssue[];
  onChange: (draft: ProjectDraft) => void;
  onBrowse: (id: string) => void;
}

/**
 * Edit sample/fraction assignments in the draft; filtering never removes hidden
 * rows.
 */
export function AcquisitionTable({ draft, sample, issues, onChange, onBrowse }: Props) {
  // Stable row IDs connect field errors, file browsing, and immutable draft
  // updates.
  const rows = draft.acquisitions.filter((row) => !sample || row.sample === sample);
  return (
    <div className="source-table">
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Sample</Table.Th>
            <Table.Th>Fraction</Table.Th>
            <Table.Th>mzML file</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Autocomplete
                  aria-label={"Sample for " + row.id}
                  data={draft.sampleNames()}
                  value={row.sample}
                  error={
                    issues.find(
                      (issue) => issue.id === row.id && issue.field === "sample"
                    )?.message
                  }
                  onChange={(value) =>
                    onChange(draft.withAcquisition(row.id, "sample", value))
                  }
                />
              </Table.Td>
              <Table.Td>
                <TextInput
                  aria-label={"Fraction for " + row.id}
                  value={row.fraction}
                  error={
                    issues.find(
                      (issue) => issue.id === row.id && issue.field === "fraction"
                    )?.message
                  }
                  onChange={(event) =>
                    onChange(
                      draft.withAcquisition(row.id, "fraction", event.currentTarget.value)
                    )
                  }
                />
              </Table.Td>
              <Table.Td>
                <div className="source-path">
                  <TextInput
                    aria-label={"mzML path for " + row.id}
                    value={row.mzml}
                    error={
                      issues.find(
                        (issue) => issue.id === row.id && issue.field === "mzml"
                      )?.message
                    }
                    onChange={(event) =>
                      onChange(
                        draft.withAcquisition(row.id, "mzml", event.currentTarget.value)
                      )
                    }
                  />
                  <Button
                    variant="subtle"
                    onClick={() => onBrowse(row.id)}
                  >
                    Browse
                  </Button>
                </div>
              </Table.Td>
              <Table.Td>
                <Button
                  variant="subtle"
                  color="red"
                  aria-label={"Remove acquisition " + row.fraction}
                  onClick={() => onChange(draft.removeAcquisition(row.id))}
                >
                  Remove
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!rows.length && (
        <p className="table-empty">
          Add mzML files or a row to begin defining acquisitions.
        </p>
      )}
    </div>
  );
}

/** Associate each sample-level idXML with a named result layer in the draft. */
export function IdentificationTable({
  draft,
  sample,
  issues,
  onChange,
  onBrowse
}: Props) {
  const rows = draft.identifications.filter((row) => !sample || row.sample === sample);
  return (
    <div className="source-table">
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Sample</Table.Th>
            <Table.Th>Layer</Table.Th>
            <Table.Th>idXML file</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Autocomplete
                  aria-label={"Identification sample for " + row.id}
                  data={draft.sampleNames()}
                  value={row.sample}
                  error={
                    issues.find(
                      (issue) => issue.id === row.id && issue.field === "sample"
                    )?.message
                  }
                  onChange={(value) =>
                    onChange(draft.withIdentification(row.id, "sample", value))
                  }
                />
              </Table.Td>
              <Table.Td>
                <TextInput
                  aria-label={"Layer for " + row.id}
                  value={row.name}
                  error={
                    issues.find((issue) => issue.id === row.id && issue.field === "name")
                      ?.message
                  }
                  onChange={(event) =>
                    onChange(
                      draft.withIdentification(row.id, "name", event.currentTarget.value)
                    )
                  }
                />
              </Table.Td>
              <Table.Td>
                <div className="source-path">
                  <TextInput
                    aria-label={"idXML path for " + row.id}
                    value={row.path}
                    error={
                      issues.find(
                        (issue) => issue.id === row.id && issue.field === "path"
                      )?.message
                    }
                    onChange={(event) =>
                      onChange(
                        draft.withIdentification(
                          row.id,
                          "path",
                          event.currentTarget.value
                        )
                      )
                    }
                  />
                  <Button
                    variant="subtle"
                    onClick={() => onBrowse(row.id)}
                  >
                    Browse
                  </Button>
                </div>
              </Table.Td>
              <Table.Td>
                <Button
                  variant="subtle"
                  color="red"
                  aria-label={"Remove identification " + row.name}
                  onClick={() => onChange(draft.removeIdentification(row.id))}
                >
                  Remove
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!rows.length && (
        <p className="table-empty">
          Optionally associate a sample-level idXML with an identification layer.
        </p>
      )}
    </div>
  );
}
