import { useEffect, useRef, useState } from "react";
import { Alert, Button, Progress, Tooltip } from "@mantine/core";
import { IconBrandGithub, IconBug } from "@tabler/icons-react";
import { apiClient, ProjectConfiguration, ProjectStatus } from "./api";
import { Dashboard } from "./Dashboard";
import { useApiRequest } from "./useApiRequest";
import { ProjectDraft } from "./ProjectDraft";
import { ProjectSetup } from "./ProjectSetup";
import logo from "./assets/mzloupe-logo-on-navy.svg";

const repositoryUrl = "https://github.com/TheBoutrosLab/package-mzLoupe";

/** Coordinate project setup, server preparation, and the inspection view. */
export function Application() {
  const [status, setStatus] = useState<ProjectStatus>({
    state: "empty",
    message: "",
    progress: 0,
    token: null
  });
  const [view, setView] = useState<"setup" | "explore">("setup");
  // Edits stay in this draft until Apply submits them to the server.
  const [draft, setDraft] = useState(new ProjectDraft());
  const [error, setError] = useState("");

  // Remember explicit navigation so a ready project cannot pull the user away from setup.
  const navigated = useRef(false);
  // Load each prepared project once; status polling must not overwrite draft edits.
  const loaded = useRef<string | null>(null);

  const { run: loadStatus, cancel: cancelStatus } = useApiRequest();
  const { run: loadConfiguration, cancel: cancelConfiguration } = useApiRequest();

  const hasProject = status.state === "ready";

  // Poll once per second without overlapping slow requests.
  useEffect(() => {
    let pending = false;
    /** Skip a poll while the previous status request is still pending. */
    async function refresh() {
      if (pending) return;
      pending = true;
      await loadStatus<ProjectStatus>({
        url: "/api/status",
        onSuccess: setStatus,
        onError: (failure) => setError(failure.message)
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

  // Seed the editor once per project; status polling cannot overwrite staged edits.
  useEffect(() => {
    if (status.state !== "ready" || !status.token || loaded.current === status.token)
      return;
    loadConfiguration<ProjectConfiguration>({
      url: "/api/configuration",
      onSuccess: (configuration) => {
        loaded.current = status.token;
        setDraft(ProjectDraft.fromConfiguration(configuration));
        if (!navigated.current) setView("explore");
      },
      onError: (failure) => setError(failure.message)
    });
    return cancelConfiguration;
  }, [status.state, status.token, loadConfiguration, cancelConfiguration]);

  // Activation starts background preparation; polling above tracks its progress.
  /** Submit the staged configuration and show its preparation progress. */
  async function apply(configuration: ProjectConfiguration) {
    await apiClient.request("/api/open-configuration", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(configuration)
    });

    setStatus(await apiClient.request<ProjectStatus>("/api/status"));
    navigated.current = true;
    setView("explore");
  }

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
            variant={view === "setup" ? "filled" : "subtle"}
            onClick={() => {
              navigated.current = true;
              setView("setup");
            }}
          >
            Project setup
          </Button>
          <Button
            variant={view === "explore" ? "filled" : "subtle"}
            disabled={!hasProject}
            onClick={() => {
              navigated.current = true;
              setView("explore");
            }}
          >
            Explore
          </Button>
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
      {error && (
        <Alert
          color="red"
          withCloseButton
          onClose={() => setError("")}
        >
          {error}
        </Alert>
      )}
      {status.state === "preparing" && (
        <div className="preparing">
          <span>{status.message}</span>
          <Progress
            value={status.progress * 100}
            animated
          />
        </div>
      )}
      {status.state === "error" && (
        <Alert color="red">
          {status.message}
          <Button
            variant="subtle"
            onClick={() => setView("setup")}
          >
            Review project
          </Button>
        </Alert>
      )}
      {/* Keep both views mounted so tab changes preserve draft edits and inspection state. */}
      <>
        <div hidden={view !== "setup"}>
          <ProjectSetup
            draft={draft}
            onChange={setDraft}
            onApply={apply}
            hasProject={hasProject}
            preparing={status.state === "preparing"}
          />
        </div>
        <div hidden={view !== "explore"}>
          <Dashboard status={status} />
        </div>
      </>
    </div>
  );
}
