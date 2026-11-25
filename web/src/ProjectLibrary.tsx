import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Menu,
  Modal,
  Table,
  TextInput
} from "@mantine/core";
import { IconDots } from "@tabler/icons-react";
import type { LibraryProject } from "./api";

interface Props {
  projects: LibraryProject[];
  loading: boolean;
  error: string;
  includeArchived: boolean;
  activeProject: string | null;
  busy: boolean;
  onIncludeArchived: (value: boolean) => void;
  onNew: (importJson?: boolean) => void;
  onOpen: (project: LibraryProject) => void;
  onEdit: (project: LibraryProject) => void;
  onExport: (project: LibraryProject) => void;
  onAction: (
    project: LibraryProject,
    action: "duplicate" | "archive" | "restore" | "clear" | "delete" | "close"
  ) => Promise<void>;
}

/** Browse durable project definitions without loading any mass spectrometry data. */
export function ProjectLibrary(props: Props) {
  const [search, setSearch] = useState("");
  const [confirmation, setConfirmation] = useState<{
    project: LibraryProject;
    action: "clear" | "delete";
  }>();
  const [failure, setFailure] = useState("");
  const [working, setWorking] = useState(false);
  const visible = props.projects.filter((project) =>
    project.name.toLowerCase().includes(search.toLowerCase())
  );

  /** Keep mutations explicit and let the parent refresh the library after success. */
  async function act(project: LibraryProject, action: Parameters<Props["onAction"]>[1]) {
    if (working) return;
    setWorking(true);
    setFailure("");
    try {
      await props.onAction(project, action);
      setConfirmation(undefined);
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="project-library">
      <div className="setup-heading">
        <div>
          <h1>Projects</h1>
          <p>Open a saved project or create a new one.</p>
        </div>
        <Group>
          <Button
            variant="default"
            disabled={props.busy}
            onClick={() => props.onNew(true)}
          >
            Import JSON
          </Button>
          <Button
            disabled={props.busy}
            onClick={() => props.onNew()}
          >
            New project
          </Button>
        </Group>
      </div>
      {(props.error || failure) && <Alert color="red">{props.error || failure}</Alert>}
      <Group
        justify="space-between"
        mb="md"
      >
        <TextInput
          label="Find project"
          placeholder="Project name"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
        <Checkbox
          label="Include archived"
          checked={props.includeArchived}
          onChange={(event) => props.onIncludeArchived(event.currentTarget.checked)}
        />
      </Group>
      <div className="panel library-table">
        <Table
          verticalSpacing="md"
          highlightOnHover
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Project</Table.Th>
              <Table.Th>Samples</Table.Th>
              <Table.Th>Fractions</Table.Th>
              <Table.Th>Last opened</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((project) => (
              <Table.Tr key={project.id}>
                <Table.Td>
                  <strong>{project.name}</strong>
                  {project.archived && <span className="caption"> · Archived</span>}
                </Table.Td>
                <Table.Td>{project.samples}</Table.Td>
                <Table.Td>{project.fractions}</Table.Td>
                <Table.Td>
                  {project.opened_at
                    ? new Date(project.opened_at).toLocaleString()
                    : "Never opened"}
                </Table.Td>
                <Table.Td>
                  <Badge color={project.status === "ready" ? "teal" : "gray"}>
                    {project.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Group
                    gap="xs"
                    wrap="nowrap"
                  >
                    <Button
                      size="xs"
                      disabled={props.busy || project.status === "draft"}
                      onClick={() => props.onOpen(project)}
                    >
                      Open
                    </Button>
                    <Menu position="bottom-end">
                      <Menu.Target>
                        <Button
                          size="xs"
                          variant="subtle"
                          disabled={props.busy || working}
                          aria-label={"Actions for " + project.name}
                        >
                          <IconDots size={18} />
                        </Button>
                      </Menu.Target>
                      <Menu.Dropdown>
                        <Menu.Item onClick={() => props.onEdit(project)}>Edit</Menu.Item>
                        <Menu.Item onClick={() => act(project, "duplicate")}>
                          Duplicate
                        </Menu.Item>
                        <Menu.Item onClick={() => props.onExport(project)}>
                          Export JSON
                        </Menu.Item>
                        <Menu.Item
                          onClick={() =>
                            act(project, project.archived ? "restore" : "archive")
                          }
                        >
                          {project.archived ? "Restore" : "Archive"}
                        </Menu.Item>
                        {project.id === props.activeProject && (
                          <Menu.Item
                            disabled={props.busy}
                            onClick={() => act(project, "close")}
                          >
                            Close project
                          </Menu.Item>
                        )}
                        <Menu.Divider />
                        <Menu.Item
                          disabled={props.busy || project.id === props.activeProject}
                          onClick={() => setConfirmation({ project, action: "clear" })}
                        >
                          Clear cache
                        </Menu.Item>
                        <Menu.Item
                          color="red"
                          disabled={props.busy || project.id === props.activeProject}
                          onClick={() => setConfirmation({ project, action: "delete" })}
                        >
                          Delete project
                        </Menu.Item>
                      </Menu.Dropdown>
                    </Menu>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {!visible.length && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  {props.loading
                    ? "Loading projects…"
                    : search
                      ? "No matching projects."
                      : "No saved projects. Create a project or import JSON to get started."}
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </div>
      <Modal
        opened={!!confirmation}
        onClose={() => setConfirmation(undefined)}
        title={confirmation?.action === "delete" ? "Delete project" : "Clear cache"}
      >
        <p>
          {confirmation?.action === "delete"
            ? "Remove this project and its prepared cache from the library?"
            : "Remove this project's prepared cache? The project can be prepared again when opened."}{" "}
          Original input files are kept.
        </p>
        <Group justify="end">
          <Button
            variant="default"
            onClick={() => setConfirmation(undefined)}
          >
            Cancel
          </Button>
          <Button
            color="red"
            loading={working}
            onClick={() => confirmation && act(confirmation.project, confirmation.action)}
          >
            Confirm
          </Button>
        </Group>
      </Modal>
    </section>
  );
}
