import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Group, Loader, Modal, TextInput } from "@mantine/core";
import type { ReactNode } from "react";
import { useApiRequest } from "./useApiRequest";

interface Directory {
  directory: string;
  parent: string;
  entries: { name: string; path: string; directory: boolean }[];
  truncated: boolean;
}

interface Props {
  kind: "mzml" | "idxml" | "json" | "directory";
  opened: boolean;
  multiple?: boolean;
  initialDirectory?: string;
  children?: ReactNode;
  onClose: () => void;
  onChoose: (paths: string[]) => void;
}

/**
 * Browse the server machine's filesystem and return paths without uploading
 * files.
 */
export function FilePicker({
  kind,
  opened,
  multiple = true,
  initialDirectory = "",
  children,
  onClose,
  onChoose
}: Props) {
  // Editing the text field does not navigate until Go or Enter commits the
  // request.
  const [path, setPath] = useState("");
  const [requested, setRequested] = useState(initialDirectory);
  const [directory, setDirectory] = useState<Directory>();
  const [selected, setSelected] = useState<string[]>([]);
  const {
    run: loadDirectory,
    cancel: cancelDirectory,
    loading: busy,
    error
  } = useApiRequest();

  // A changed directory or closed picker cancels the previous listing.
  useEffect(() => {
    if (!opened) return;
    const query = new URLSearchParams({ kind });
    if (requested) query.set("path", requested);
    loadDirectory<Directory>({
      url: "/api/files?" + query,
      onSuccess: (value) => {
        setDirectory(value);
        setPath(value.directory);
      }
    });
    return cancelDirectory;
  }, [opened, requested, kind, loadDirectory, cancelDirectory]);

  // Start a new selection on reopen, but retain chosen paths while browsing
  // subdirectories.
  useEffect(() => {
    if (opened) {
      setSelected([]);
    }
  }, [opened]);

  /**
   * Toggle a file while respecting the picker's single- or multiple-selection
   * mode.
   */
  function toggle(value: string) {
    setSelected((current) =>
      current.includes(value)
        ? current.filter((path) => path !== value)
        : multiple
          ? [...current, value]
          : [value]
    );
  }

  const choosingDirectory = kind === "directory";
  const canChoose = choosingDirectory
    ? !!directory && !busy && !error && path === directory.directory
    : selected.length > 0;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={kind === "directory" ? "Select directory" : "Select " + kind + " files"}
      size="xl"
    >
      {/* Callers can supply sample/layer controls for a batch of selected files. */}
      {children}
      <Group
        align="end"
        className="directory-path"
      >
        <TextInput
          label="Directory"
          value={path}
          onChange={(event) => setPath(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              setRequested(path);
            }
          }}
          style={{ flex: 1 }}
        />
        <Button
          variant="light"
          onClick={() => setRequested(path)}
        >
          Go
        </Button>
        <Button
          variant="subtle"
          onClick={() => setRequested(directory?.parent || "")}
        >
          Parent
        </Button>
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {busy ? (
        <Loader size="sm" />
      ) : (
        <div className="file-list">
          {directory?.entries.map((entry) =>
            entry.directory ? (
              <button
                type="button"
                className="directory"
                key={entry.path}
                onClick={() => setRequested(entry.path)}
              >
                ▸ {entry.name}/
              </button>
            ) : (
              <Checkbox
                key={entry.path}
                label={entry.name}
                checked={selected.includes(entry.path)}
                onChange={() => toggle(entry.path)}
              />
            )
          )}
          {!directory?.entries.length && (
            <p className="caption">No matching files or subdirectories.</p>
          )}
        </div>
      )}
      {directory?.truncated && (
        <p className="caption">
          Showing the first 1,000 entries. Enter a narrower directory.
        </p>
      )}
      <Group
        justify="space-between"
        mt="md"
      >
        <span>
          {kind === "directory" ? directory?.directory : selected.length + " selected"}
        </span>
        <Button
          disabled={!canChoose}
          onClick={() => {
            onChoose(
              kind === "directory" && directory ? [directory.directory] : selected
            );
            onClose();
          }}
        >
          {kind === "directory" ? "Use this directory" : "Use selected files"}
        </Button>
      </Group>
    </Modal>
  );
}
