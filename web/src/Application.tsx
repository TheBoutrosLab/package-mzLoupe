import { useEffect, useReducer, useRef, useState } from "react";
import { Alert, Button, Group, Modal, Progress, Select, Tooltip } from "@mantine/core";
import { IconBrandGithub, IconBug } from "@tabler/icons-react";
import { apiClient } from "./api";
import type { LibraryProject, ProjectConfiguration, ProjectStatus } from "./api";
import { ApplicationModel } from "./ApplicationModel";
import { Dashboard } from "./Dashboard";
import { useApiRequest } from "./useApiRequest";
import { ProjectSetup } from "./ProjectSetup";
import { ProjectLocation } from "./ProjectLocation";
import { ProjectLibrary } from "./ProjectLibrary";
import { ProjectSaveDialog } from "./ProjectSaveDialog";
import logo from "./assets/mzloupe-logo-on-navy.svg";

const repositoryUrl = "https://github.com/TheBoutrosLab/package-mzLoupe";

type ProjectNavigation =
  | { kind: "new"; importJson?: boolean }
  | { kind: "open" | "edit"; project: LibraryProject };

/** Coordinate the project library, saved configuration editor, and scientific workspace. */
export function Application() {
  const [state, dispatch] = useReducer(
    ApplicationModel.reduce,
    undefined,
    ApplicationModel.initial
  );
  const statusRequest = useApiRequest();
  const configurationRequest = useApiRequest();
  const libraryRequest = useApiRequest();
  const restoreRequest = useApiRequest();
  const { run: loadStatus, cancel: cancelStatus } = statusRequest;
  const { run: loadConfiguration, cancel: cancelConfiguration } = configurationRequest;
  const { run: loadLibrary, cancel: cancelLibrary } = libraryRequest;
  const { run: restoreProject, cancel: cancelRestore } = restoreRequest;
  const [pendingNavigation, setPendingNavigation] = useState<ProjectNavigation | null>(
    null
  );
  const navigated = useRef(false);
  const loaded = useRef<string | null>(null);
  const preparing = state.status.state === "preparing";

  // Poll preparation independently of navigation, without overlapping requests.
  useEffect(() => {
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      await loadStatus<ProjectStatus>({
        url: "/api/status",
        onSuccess: (status) => dispatch({ type: "status", status })
      });
      pending = false;
    }
    refresh();
    const timer = setInterval(refresh, 1000);
    return () => {
      clearInterval(timer);
      cancelStatus();
    };
  }, [loadStatus, cancelStatus]);

  // Library rows are cheap registry metadata; opening the page never parses mzML.
  useEffect(() => {
    loadLibrary<LibraryProject[]>({
      url: "/api/library?include_archived=" + state.includeArchived,
      onSuccess: (projects) => dispatch({ type: "library", projects })
    });
    return cancelLibrary;
  }, [
    state.includeArchived,
    state.libraryRevision,
    state.status.state,
    state.status.token,
    loadLibrary,
    cancelLibrary
  ]);

  // Restore the registered project before interpreting a source/scan URL.
  useEffect(() => {
    const parameters = new URLSearchParams(location.search);
    const identifier = parameters.get("project");
    if (!identifier) {
      if (parameters.get("view") === "setup") {
        navigated.current = true;
        dispatch({ type: "new" });
      }
      return;
    }
    navigated.current = true;
    restoreProject<LibraryProject>({
      url: "/api/library/" + encodeURIComponent(identifier),
      onSuccess: (project) =>
        parameters.get("view") === "setup" ? edit(project) : open(project),
      onError: (error) => {
        ProjectLocation.library();
        dispatch({ type: "error", message: error.message });
      }
    });
    return cancelRestore;
  }, [restoreProject, cancelRestore]);

  // A CLI startup project may open directly in Explore. Explicit navigation wins.
  useEffect(() => {
    if (
      state.status.state !== "ready" ||
      !state.status.token ||
      navigated.current ||
      loaded.current === state.status.token
    )
      return;
    loadConfiguration<ProjectConfiguration>({
      url: "/api/configuration",
      onSuccess: (configuration) => {
        loaded.current = state.status.token;
        if (configuration.id) ProjectLocation.project(configuration.id, "explore");
        dispatch({ type: "edit", configuration, view: "explore" });
      }
    });
    return cancelConfiguration;
  }, [state.status.state, state.status.token, loadConfiguration, cancelConfiguration]);

  /** Keep mutation refreshes and periodic polling in the same cancellable request lane. */
  async function refreshStatus() {
    await loadStatus<ProjectStatus>({
      url: "/api/status",
      onSuccess: (status) => dispatch({ type: "status", status })
    });
  }

  /** Persist a configuration without preparing it or disturbing the active explorer. */
  async function save(configuration: ProjectConfiguration) {
    dispatch({ type: "saving", value: true });
    try {
      const project = await apiClient.request<LibraryProject>("/api/library", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configuration)
      });
      dispatch({ type: "saved", project });
      ProjectLocation.project(project.id, "setup");
    } finally {
      dispatch({ type: "saving", value: false });
    }
  }

  /** Save and prepare only the changed inputs, keeping the same project identity. */
  async function apply(configuration: ProjectConfiguration) {
    dispatch({ type: "saving", value: true });
    try {
      await apiClient.request("/api/open-configuration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configuration)
      });
      if (configuration.id) ProjectLocation.project(configuration.id, "explore");
      dispatch({ type: "edit", configuration, view: "explore" });
      dispatch({ type: "refresh" });
      navigated.current = true;
      await refreshStatus();
    } finally {
      dispatch({ type: "saving", value: false });
    }
  }

  /** Open a saved definition or reveal its setup when sources cannot be prepared. */
  async function open(project: LibraryProject) {
    navigated.current = true;
    ProjectLocation.project(project.id, "explore");
    dispatch({ type: "edit", configuration: project.configuration, view: "explore" });
    dispatch({ type: "saving", value: true });
    try {
      await apiClient.request("/api/library/" + project.id + "/open", { method: "POST" });
      await refreshStatus();
    } catch (error) {
      ProjectLocation.project(project.id, "setup");
      dispatch({ type: "navigate", view: "setup" });
      dispatch({ type: "error", message: (error as Error).message });
      dispatch({ type: "refresh" });
    } finally {
      dispatch({ type: "saving", value: false });
    }
  }

  /** Apply a library action, leaving all original scientific files untouched. */
  async function act(
    project: LibraryProject,
    action: "duplicate" | "archive" | "restore" | "clear" | "delete" | "close"
  ) {
    dispatch({ type: "saving", value: true });
    try {
      const base = "/api/library/" + project.id;
      if (action === "duplicate") {
        const copy = await apiClient.request<LibraryProject>(base + "/duplicate", {
          method: "POST"
        });
        requestNavigation({ kind: "edit", project: copy });
      } else if (action === "archive" || action === "restore") {
        await apiClient.request(base, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ archived: action === "archive" })
        });
      } else if (action === "close") {
        await apiClient.request(base + "/close", { method: "POST" });
        await refreshStatus();
      } else {
        await apiClient.request(base + (action === "clear" ? "/cache" : ""), {
          method: "DELETE"
        });
      }
      if (action === "delete" && project.id === state.draft.id)
        dispatch({ type: "close" });
      dispatch({ type: "refresh" });
    } finally {
      dispatch({ type: "saving", value: false });
    }
  }

  /** Editing a project loads only its saved configuration. */
  function edit(project: LibraryProject) {
    navigated.current = true;
    ProjectLocation.project(project.id, "setup");
    dispatch({ type: "edit", configuration: project.configuration });
  }

  /** Ask before replacing a dirty draft with another project's configuration. */
  function requestNavigation(navigation: ProjectNavigation) {
    if (ApplicationModel.hasUnsavedChanges(state)) {
      setPendingNavigation(navigation);
      return;
    }
    completeNavigation(navigation);
  }

  /** Execute only the explicit project switch selected or confirmed by the user. */
  function completeNavigation(navigation: ProjectNavigation) {
    setPendingNavigation(null);
    navigated.current = true;
    if (navigation.kind === "new") {
      ProjectLocation.draft();
      dispatch({ type: "new", importJson: navigation.importJson });
    } else if (navigation.kind === "open") open(navigation.project);
    else edit(navigation.project);
  }

  const activeId = state.status.active_project_id || state.status.project_id;
  const canExplore =
    !!state.status.token && (activeId ? activeId === state.draft.id : state.selected);
  const selectedRecord = state.projects.find((project) => project.id === state.draft.id);
  const previous =
    canExplore &&
    (state.status.state !== "ready" ||
      (selectedRecord && selectedRecord.status !== "ready"));
  const explorerStatus: ProjectStatus = canExplore
    ? { ...state.status, state: "ready" }
    : { state: "empty", message: "", progress: 0, token: null };
  const choices = state.projects
    .filter((project) => !project.archived)
    .map((project) => ({ value: project.id, label: project.name }));
  if (state.selected && !choices.some((choice) => choice.value === state.draft.id))
    choices.push({ value: state.draft.id, label: state.draft.name });

  return (
    <div className="application">
      <header>
        <div className="brand">
          <img
            src={logo}
            alt="mzLoupe"
          />
        </div>
        <nav aria-label="Workspace">
          <Button
            variant={state.view === "library" ? "filled" : "subtle"}
            disabled={state.saving}
            onClick={() => {
              navigated.current = true;
              ProjectLocation.library();
              dispatch({ type: "navigate", view: "library" });
              dispatch({ type: "refresh" });
            }}
          >
            Projects
          </Button>
          {state.selected && (
            <>
              <Select
                aria-label="Selected project"
                value={state.draft.id}
                data={choices}
                disabled={preparing || state.saving}
                onChange={(id) => {
                  const project = state.projects.find((item) => item.id === id);
                  if (project) requestNavigation({ kind: "open", project });
                }}
              />
              <Button
                variant={state.view === "explore" ? "filled" : "subtle"}
                disabled={state.saving || (!canExplore && !preparing)}
                onClick={() => {
                  navigated.current = true;
                  if (state.draft.id) ProjectLocation.project(state.draft.id, "explore");
                  dispatch({ type: "navigate", view: "explore" });
                }}
              >
                Explore
              </Button>
              <Button
                variant={state.view === "setup" ? "filled" : "subtle"}
                disabled={state.saving}
                onClick={() => {
                  navigated.current = true;
                  if (state.registered) ProjectLocation.project(state.draft.id, "setup");
                  dispatch({ type: "navigate", view: "setup" });
                }}
              >
                Project setup
              </Button>
            </>
          )}
        </nav>
        <div className="header-actions">
          <Tooltip
            label="GitHub repository"
            withArrow
            events={{
              hover: true,
              focus: true,
              touch: false
            }}
          >
            <a
              href={repositoryUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub repository"
            >
              <IconBrandGithub
                size={24}
                aria-hidden="true"
              />
            </a>
          </Tooltip>
          <Tooltip
            label="Report an issue"
            withArrow
            events={{
              hover: true,
              focus: true,
              touch: false
            }}
          >
            <a
              href={repositoryUrl + "/issues/new"}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Report an issue"
            >
              <IconBug
                size={24}
                aria-hidden="true"
              />
            </a>
          </Tooltip>
        </div>
      </header>
      {state.error && (
        <Alert
          color="red"
          withCloseButton
          onClose={() => dispatch({ type: "error", message: "" })}
        >
          {state.error}
        </Alert>
      )}
      {state.notice && (
        <Alert
          color="green"
          withCloseButton
          onClose={() => dispatch({ type: "notice", message: "" })}
        >
          {state.notice}
        </Alert>
      )}
      {preparing && (
        <div className="preparing">
          <span>{state.status.message}</span>
          <Progress
            value={state.status.progress * 100}
            animated
          />
        </div>
      )}
      {state.status.state === "error" && state.view !== "library" && (
        <Alert color="red">
          {state.status.message}
          <Button
            variant="subtle"
            onClick={() => dispatch({ type: "navigate", view: "setup" })}
          >
            Edit project
          </Button>
        </Alert>
      )}
      {state.view === "library" && (
        <ProjectLibrary
          projects={state.projects}
          loading={libraryRequest.loading}
          error={libraryRequest.error}
          includeArchived={state.includeArchived}
          activeProject={activeId || null}
          busy={preparing || state.saving}
          onIncludeArchived={(value) => dispatch({ type: "archivedVisibility", value })}
          onNew={(importJson) => requestNavigation({ kind: "new", importJson })}
          onOpen={(project) => requestNavigation({ kind: "open", project })}
          onEdit={(project) => requestNavigation({ kind: "edit", project })}
          onExport={(project) =>
            dispatch({ type: "export", configuration: project.configuration })
          }
          onAction={act}
        />
      )}
      {/* Keep workspace views mounted so navigation preserves drafts and inspection state. */}
      <div hidden={state.view !== "setup"}>
        <ProjectSetup
          draft={state.draft}
          onChange={(draft) => dispatch({ type: "draft", draft })}
          onApply={apply}
          onSave={save}
          hasProject={state.registered}
          preparing={preparing}
          saving={state.saving}
          importRequest={state.importRequest}
          project={selectedRecord}
        />
      </div>
      <div hidden={state.view !== "explore"}>
        {previous && (
          <Alert color="yellow">
            Showing the previous prepared revision. Saved updates will appear after
            preparation succeeds.
          </Alert>
        )}
        <Dashboard
          status={explorerStatus}
          visible={state.view === "explore"}
        />
      </div>
      <Modal
        opened={!!pendingNavigation}
        onClose={() => setPendingNavigation(null)}
        title="Unsaved project changes"
      >
        <p>
          Save your changes before switching projects, or discard the edits to continue.
        </p>
        <Group justify="end">
          <Button
            variant="default"
            onClick={() => setPendingNavigation(null)}
          >
            Keep editing
          </Button>
          <Button
            color="red"
            onClick={() => pendingNavigation && completeNavigation(pendingNavigation)}
          >
            Discard changes
          </Button>
        </Group>
      </Modal>
      <ProjectSaveDialog
        opened={!!state.exportConfiguration}
        configuration={state.exportConfiguration || state.draft.toConfiguration()}
        onClose={() => dispatch({ type: "export" })}
        onSaved={(path) => dispatch({ type: "notice", message: "Exported: " + path })}
      />
    </div>
  );
}
