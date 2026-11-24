import { useEffect, useState } from "react";
import { Alert, Button, Group, Modal, Stack, TextInput } from "@mantine/core";
import { apiClient, ApiError } from "./api";
import type { ProjectConfiguration } from "./api";
import { FilePicker } from "./FilePicker";

interface Props {
  opened: boolean;
  configuration: ProjectConfiguration;
  onClose: () => void;
  onSaved: (path: string) => void;
}

/** Save a configuration to the server filesystem without opening a browser download. */
export function ProjectSaveDialog({ opened, configuration, onClose, onSaved }: Props) {
  const [directory, setDirectory] = useState("~");
  const [filename, setFilename] = useState("project.json");
  const [browsing, setBrowsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exists, setExists] = useState(false);
  const [error, setError] = useState("");

  // Keep the last destination between saves, but require fresh confirmation if
  // an existing file is encountered again.
  useEffect(() => {
    if (opened) {
      setError("");
      setExists(false);
      setBrowsing(false);
    }
  }, [opened]);

  const filenameError =
    filename &&
    (!filename.toLowerCase().endsWith(".json") ||
      filename.includes("/") ||
      filename.includes("\\"))
      ? "Use a .json filename without directory separators."
      : undefined;

  /** Changing the destination clears any previous overwrite confirmation. */
  function changeDirectory(value: string) {
    setDirectory(value);
    setExists(false);
    setError("");
  }

  /** Publish the current draft, replacing an existing file only after a conflict prompt. */
  async function save(overwrite: boolean) {
    setSaving(true);
    setError("");
    try {
      const result = await apiClient.request<{ path: string }>("/api/save-project", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directory, filename, project: configuration, overwrite })
      });
      onSaved(result.path);
      onClose();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        setExists(true);
      } else {
        setError((failure as Error).message);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Modal
        opened={opened && !browsing}
        onClose={() => {
          if (!saving) {
            onClose();
          }
        }}
        title="Save project JSON"
        size="lg"
        withCloseButton={!saving}
        closeOnClickOutside={!saving}
        closeOnEscape={!saving}
      >
        <Stack gap="md">
          <Group align="end">
            <TextInput
              label="Directory"
              value={directory}
              onChange={(event) => changeDirectory(event.currentTarget.value)}
              disabled={saving}
              style={{ flex: 1 }}
            />
            <Button
              variant="default"
              disabled={saving}
              onClick={() => setBrowsing(true)}
            >
              Browse directory
            </Button>
          </Group>
          <TextInput
            label="File name"
            value={filename}
            error={filenameError}
            disabled={saving}
            onChange={(event) => {
              setFilename(event.currentTarget.value);
              setExists(false);
              setError("");
            }}
          />
          {error && <Alert color="red">{error}</Alert>}
          {exists && (
            <Alert color="yellow">
              A file with this name already exists. Choose another name or select Replace
              file to overwrite it.
            </Alert>
          )}
          <Group justify="end">
            <Button
              variant="default"
              disabled={saving}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              loading={saving}
              disabled={!directory.trim() || !filename || !!filenameError}
              onClick={() => save(exists)}
            >
              {exists ? "Replace file" : "Save"}
            </Button>
          </Group>
        </Stack>
      </Modal>
      {opened && browsing && (
        <FilePicker
          kind="directory"
          opened
          initialDirectory={directory}
          onClose={() => setBrowsing(false)}
          onChoose={(paths) => {
            changeDirectory(paths[0]);
            setBrowsing(false);
          }}
        />
      )}
    </>
  );
}
