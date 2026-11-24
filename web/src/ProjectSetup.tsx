import { useEffect, useState } from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Group,
  Modal,
  Select,
  TextInput
} from "@mantine/core";
import { apiClient, ProjectConfiguration } from "./api";
import { useApiRequest } from "./useApiRequest";
import { ProjectDraft, RowIssue } from "./ProjectDraft";
import { AcquisitionTable, IdentificationTable } from "./SourceTables";
import { FilePicker } from "./FilePicker";
import { ProjectSaveDialog } from "./ProjectSaveDialog";
import { ProteinGroupingTable } from "./ProteinGroupingTable";

/**
 * The server identifies acquisition issues by ID and identification issues by
 * sample/layer.
 */
interface ServerIssue {
  kind: string;
  id?: string;
  sample?: string;
  layer?: string;
  grouping?: string;
  field: string;
  message: string;
}

interface Props {
  draft: ProjectDraft;
  onChange: (draft: ProjectDraft) => void;
  onApply: (configuration: ProjectConfiguration) => Promise<void>;
  hasProject: boolean;
  preparing: boolean;
}

/**
 * A row selects one existing path; an absent row adds a batch or imports JSON.
 */
interface Picker {
  kind: "mzml" | "idxml" | "json";
  row?: string;
}

/**
 * Stage and validate file associations before explicitly activating a project.
 */
export function ProjectSetup({ draft, onChange, onApply, hasProject, preparing }: Props) {
  const [sample, setSample] = useState("");
  const [assignSample, setAssignSample] = useState("Sample 1");
  const [assignLayer, setAssignLayer] = useState("Validated");
  const [picker, setPicker] = useState<Picker>();
  const [importOpen, setImportOpen] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [saveOpen, setSaveOpen] = useState(false);
  const [savedPath, setSavedPath] = useState("");
  const [error, setError] = useState("");
  const [serverIssues, setServerIssues] = useState<RowIssue[]>([]);
  const [validating, setValidating] = useState(true);
  const [applying, setApplying] = useState(false);
  const localIssues = draft.issues();
  const { run: validateDraft, cancel: cancelValidation } = useApiRequest();

  // Check local row rules first, then debounce filesystem validation on the
  // server.
  useEffect(() => {
    if (sample && !draft.sampleNames().includes(sample)) {
      setSample("");
    }
    setServerIssues([]);
    setSavedPath("");
    if (draft.issues().length) {
      setValidating(false);
      return;
    }
    setValidating(true);
    const timer = setTimeout(() => {
      validateDraft<{ issues: ServerIssue[] }>({
        url: "/api/validate-project",
        options: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft.toConfiguration())
        },
        onSuccess: (value) => {
          // Translate sample/layer references back to the editor's temporary
          // row IDs.
          const issues = value.issues.map((issue) => ({
            id:
              (issue.kind === "protein_grouping"
                ? draft.groupings.find((row) => row.name.trim() === issue.grouping)?.id
                : issue.id) ||
              draft.identifications.find(
                (row) =>
                  row.sample.trim() === issue.sample && row.name.trim() === issue.layer
              )?.id ||
              "project",
            field: issue.field,
            message: issue.message
          }));
          setServerIssues(issues);
          setError("");
          setValidating(false);
        },
        onError: (failure) => {
          setError(failure.message);
          setValidating(false);
        }
      });
    }, 350);
    return () => {
      clearTimeout(timer);
      cancelValidation();
    };
  }, [draft, validateDraft, cancelValidation]);

  /**
   * Import resolved file paths into the draft without starting project
   * preparation.
   */
  async function importProject(path: string) {
    try {
      const configuration = await apiClient.request<ProjectConfiguration>(
        "/api/import-project",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path })
        }
      );
      onChange(ProjectDraft.fromConfiguration(configuration));
      setSample("");
      setError("");
      setImportOpen(false);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }

  /**
   * Hand the validated configuration to the application's activation workflow.
   */
  async function apply() {
    setApplying(true);
    setError("");
    try {
      await onApply(draft.toConfiguration());
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setApplying(false);
    }
  }

  /**
   * Route picker results to JSON import, a single path edit, or a batch
   * assignment.
   */
  function chooseFiles(paths: string[]) {
    if (!picker) {
      return;
    }
    if (picker.kind === "json") {
      setImportPath(paths[0]);
      importProject(paths[0]);
      return;
    }
    if (picker.row) {
      onChange(
        picker.kind === "mzml"
          ? draft.withAcquisition(picker.row, "mzml", paths[0])
          : draft.withIdentification(picker.row, "path", paths[0])
      );
      return;
    }
    onChange(
      picker.kind === "mzml"
        ? draft.addAcquisitions(paths, assignSample)
        : draft.addIdentifications(paths, assignSample, assignLayer)
    );
  }

  /** Apply row edits and reveal rows that move outside the current sample filter. */
  function changeDraft(next: ProjectDraft) {
    if (sample) {
      const moved =
        draft.acquisitions.some(
          (row) =>
            row.sample === sample &&
            next.acquisitions.find((item) => item.id === row.id)?.sample !== sample
        ) ||
        draft.identifications.some(
          (row) =>
            row.sample === sample &&
            next.identifications.find((item) => item.id === row.id)?.sample !== sample
        );
      if (moved) {
        setSample("");
      }
    }
    onChange(next);
  }

  const issues = [...localIssues, ...serverIssues];

  /** Open the file picker with the current sample as the assignment default. */
  function addFiles(kind: "mzml" | "idxml") {
    setAssignSample(sample || draft.sampleNames()[0] || "Sample 1");
    setPicker({ kind });
  }

  return (
    <section className="project-setup">
      <div className="setup-heading">
        <div>
          <h1>Project setup</h1>
          <p>
            Associate acquisition files with fractions and identification files with
            samples.
          </p>
        </div>
        <Group>
          <Button
            variant="default"
            onClick={() => setImportOpen(true)}
          >
            Import JSON
          </Button>
          <Button
            variant="default"
            disabled={!!localIssues.length}
            onClick={() => setSaveOpen(true)}
          >
            Save JSON
          </Button>
        </Group>
      </div>
      {error && (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setError("")}
        >
          {error}
        </Alert>
      )}
      {savedPath && (
        <Alert
          color="green"
          withCloseButton
          onClose={() => setSavedPath("")}
        >
          Saved: {savedPath}
        </Alert>
      )}
      <div className="setup-controls">
        <TextInput
          label="Project name"
          value={draft.name}
          error={
            issues.find((issue) => issue.id === "project" && issue.field === "name")
              ?.message
          }
          onChange={(event) => onChange(draft.withName(event.currentTarget.value))}
        />
        <Select
          label="Show sample"
          value={sample}
          data={[
            {
              value: "",
              label: "All samples"
            },
            ...draft.sampleNames().map((name) => ({
              value: name,
              label: name
            }))
          ]}
          onChange={(value) => setSample(value || "")}
        />
      </div>
      <section className="panel">
        <div className="panel-title">
          <h2>Acquisitions</h2>
          <Group>
            <Button
              variant="subtle"
              onClick={() =>
                onChange(
                  draft.addAcquisitions(
                    [""],
                    sample || draft.sampleNames()[0] || "Sample 1"
                  )
                )
              }
            >
              Add acquisition row
            </Button>
            <Button onClick={() => addFiles("mzml")}>Add mzML files</Button>
          </Group>
        </div>
        <AcquisitionTable
          draft={draft}
          sample={sample}
          issues={issues}
          onChange={changeDraft}
          onBrowse={(row) =>
            setPicker({
              kind: "mzml",
              row
            })
          }
        />
      </section>
      <section className="panel">
        <div className="panel-title">
          <h2>Identifications</h2>
          <Group>
            <Button
              variant="subtle"
              onClick={() =>
                onChange(
                  draft.addIdentifications(
                    [""],
                    sample || draft.sampleNames()[0] || "Sample 1",
                    "Validated"
                  )
                )
              }
            >
              Add identification row
            </Button>
            <Button onClick={() => addFiles("idxml")}>Add idXML files</Button>
          </Group>
        </div>
        <IdentificationTable
          draft={draft}
          sample={sample}
          issues={issues}
          onChange={changeDraft}
          onBrowse={(row) =>
            setPicker({
              kind: "idxml",
              row
            })
          }
        />
      </section>
      <ProteinGroupingTable
        draft={draft}
        issues={issues}
        onChange={onChange}
      />
      <div className="setup-footer">
        <div>
          <strong>
            {draft.sampleNames().length}{" "}
            {draft.sampleNames().length === 1 ? "sample" : "samples"} ·{" "}
            {draft.acquisitions.length}{" "}
            {draft.acquisitions.length === 1 ? "acquisition" : "acquisitions"} ·{" "}
            {draft.identifications.length}{" "}
            {draft.identifications.length === 1
              ? "identification file"
              : "identification files"}
          </strong>
          <span>
            {validating
              ? "Checking files…"
              : issues.length
                ? "Review the highlighted fields before opening the project."
                : "Source paths checked. Ready to open."}
          </span>
        </div>
        <Button
          size="md"
          loading={applying || preparing}
          disabled={!!issues.length || validating || !!error}
          onClick={apply}
        >
          {hasProject ? "Apply changes" : "Open project"}
        </Button>
      </div>
      <Modal
        opened={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import project JSON"
        size="lg"
      >
        <TextInput
          label="Project JSON path"
          value={importPath}
          onChange={(event) => setImportPath(event.currentTarget.value)}
        />
        <Group
          justify="end"
          mt="md"
        >
          <Button
            variant="default"
            onClick={() => setPicker({ kind: "json" })}
          >
            Browse JSON
          </Button>
          <Button
            disabled={!importPath}
            onClick={() => importProject(importPath)}
          >
            Import into tables
          </Button>
        </Group>
      </Modal>
      <FilePicker
        kind={picker?.kind || "mzml"}
        opened={!!picker}
        multiple={!picker?.row && picker?.kind !== "json"}
        onClose={() => setPicker(undefined)}
        onChoose={chooseFiles}
      >
        {picker && !picker.row && picker.kind !== "json" && (
          <Group
            align="start"
            mb="md"
          >
            <Autocomplete
              label="Assign sample"
              data={draft.sampleNames()}
              value={assignSample}
              onChange={setAssignSample}
            />
            {picker.kind === "idxml" && (
              <TextInput
                label="Assign layer"
                value={assignLayer}
                onChange={(event) => setAssignLayer(event.currentTarget.value)}
              />
            )}
          </Group>
        )}
      </FilePicker>
      <ProjectSaveDialog
        opened={saveOpen}
        configuration={draft.toConfiguration()}
        onClose={() => setSaveOpen(false)}
        onSaved={setSavedPath}
      />
    </section>
  );
}
