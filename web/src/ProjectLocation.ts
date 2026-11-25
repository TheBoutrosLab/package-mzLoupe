/** Keep project identity in browser navigation without carrying selections across projects. */
export class ProjectLocation {
  /** Return to the project library without retaining a hidden explorer's URL state. */
  static library() {
    history.replaceState(null, "", location.pathname);
  }

  /** Open a project view, retaining scan selection only within the same project. */
  static project(identifier: string, view: "setup" | "explore") {
    let parameters = new URLSearchParams(location.search);
    if (parameters.get("project") !== identifier) parameters = new URLSearchParams();
    parameters.set("project", identifier);
    if (view === "setup") parameters.set("view", "setup");
    else parameters.delete("view");
    history.replaceState(null, "", location.pathname + "?" + parameters);
  }

  /** An unsaved draft has no registered identity to restore after a reload. */
  static draft() {
    history.replaceState(null, "", location.pathname + "?view=setup");
  }

  /** Persist accepted scientific selections together with the project they belong to. */
  static selection(
    identifier: string | null | undefined,
    selection: Record<string, string>
  ) {
    const parameters = new URLSearchParams(selection);
    if (identifier) parameters.set("project", identifier);
    history.replaceState(null, "", location.pathname + "?" + parameters);
  }
}
