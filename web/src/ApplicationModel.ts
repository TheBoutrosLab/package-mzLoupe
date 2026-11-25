import type { LibraryProject, ProjectConfiguration, ProjectStatus } from "./api";
import { ProjectDraft } from "./ProjectDraft";

export type ApplicationView = "library" | "setup" | "explore";

export interface ApplicationState {
  view: ApplicationView;
  draft: ProjectDraft;
  registered: boolean;
  baseline: string;
  selected: boolean;
  status: ProjectStatus;
  projects: LibraryProject[];
  includeArchived: boolean;
  libraryRevision: number;
  importRequest: number;
  saving: boolean;
  error: string;
  notice: string;
  exportConfiguration?: ProjectConfiguration;
}

export type ApplicationAction =
  | { type: "status"; status: ProjectStatus }
  | { type: "library"; projects: LibraryProject[] }
  | { type: "navigate"; view: ApplicationView }
  | { type: "new"; importJson?: boolean }
  | { type: "edit"; configuration: ProjectConfiguration; view?: ApplicationView }
  | { type: "draft"; draft: ProjectDraft }
  | { type: "saved"; project: LibraryProject }
  | { type: "refresh" }
  | { type: "close" }
  | { type: "archivedVisibility"; value: boolean }
  | { type: "saving"; value: boolean }
  | { type: "error"; message: string }
  | { type: "notice"; message: string }
  | { type: "export"; configuration?: ProjectConfiguration };

/** Own application navigation and saved-project transitions independently of scientific views. */
export class ApplicationModel {
  /** Start at the library without creating or preparing an implicit project. */
  static initial(): ApplicationState {
    return {
      view: "library",
      draft: new ProjectDraft(),
      registered: false,
      baseline: "",
      selected: false,
      status: { state: "empty", message: "", progress: 0, token: null },
      projects: [],
      includeArchived: false,
      libraryRevision: 0,
      importRequest: 0,
      saving: false,
      error: "",
      notice: ""
    };
  }

  /** Detect meaningful edits while keeping navigation between the library and draft lossless. */
  static hasUnsavedChanges(state: ApplicationState): boolean {
    return (
      state.selected && JSON.stringify(state.draft.toConfiguration()) !== state.baseline
    );
  }

  /** Keep draft edits, library mutations, and explorer navigation explicit. */
  static reduce(state: ApplicationState, action: ApplicationAction): ApplicationState {
    switch (action.type) {
      case "status":
        return { ...state, status: action.status };
      case "library":
        return { ...state, projects: action.projects };
      case "navigate":
        return { ...state, view: action.view, error: "" };
      case "new": {
        const draft = new ProjectDraft();
        return {
          ...state,
          view: "setup",
          draft,
          baseline: JSON.stringify(draft.toConfiguration()),
          registered: false,
          selected: true,
          error: "",
          notice: "",
          importRequest: state.importRequest + (action.importJson ? 1 : 0)
        };
      }
      case "edit": {
        const draft = ProjectDraft.fromConfiguration(action.configuration);
        return {
          ...state,
          view: action.view || "setup",
          draft,
          baseline: JSON.stringify(draft.toConfiguration()),
          registered: true,
          selected: true,
          error: "",
          notice: ""
        };
      }
      case "draft":
        return {
          ...state,
          draft: action.draft,
          notice: "",
          registered: state.registered && state.draft.id === action.draft.id
        };
      case "saved": {
        const draft = ProjectDraft.fromConfiguration(action.project.configuration);
        return {
          ...state,
          draft,
          baseline: JSON.stringify(draft.toConfiguration()),
          registered: true,
          libraryRevision: state.libraryRevision + 1,
          notice: "Project saved.",
          error: ""
        };
      }
      case "close":
        return {
          ...state,
          selected: false,
          registered: false,
          view: "library",
          error: "",
          notice: ""
        };
      case "refresh":
        return { ...state, libraryRevision: state.libraryRevision + 1 };
      case "archivedVisibility":
        return { ...state, includeArchived: action.value };
      case "saving":
        return { ...state, saving: action.value };
      case "error":
        return { ...state, error: action.message };
      case "notice":
        return { ...state, notice: action.message };
      case "export":
        return { ...state, exportConfiguration: action.configuration };
    }
  }
}
