import { useEffect, useReducer, useRef } from "react";
import type { PlotRelayoutEvent } from "plotly.js";
import { apiClient } from "./api";
import type {
  Annotation,
  MapCell,
  MapData,
  MapTarget,
  ProjectStatus,
  ProjectSummary,
  Psm,
  Spectrum
} from "./api";
import { ProjectLocation } from "./ProjectLocation";
import { ExplorerModel } from "./ExplorerState";
import { useApiRequest } from "./useApiRequest";

/** Coordinate independent request lanes around the explorer's pure state transitions. */
export function useExplorer(
  status: ProjectStatus,
  fragmentPpm: number | string,
  visible: boolean
) {
  const [state, dispatch] = useReducer(
    ExplorerModel.reduce,
    undefined,
    ExplorerModel.initial
  );
  const projectRequest = useApiRequest();
  const mapRequest = useApiRequest();
  const selectionRequest = useApiRequest();
  const annotationRequest = useApiRequest();
  const { run: loadProject, cancel: cancelProject } = projectRequest;
  const { run: loadMap, cancel: cancelMap } = mapRequest;
  const { run: loadSelection, cancel: cancelSelection } = selectionRequest;
  const { run: loadAnnotations, cancel: cancelAnnotations } = annotationRequest;
  const restored = useRef("");
  const base = apiClient.projectUrl(state.token);
  const ready = status.state === "ready" && state.token === status.token;

  // A project change invalidates the entire linked selection in one transition.
  useEffect(() => {
    const token = status.token || "";
    dispatch({ type: "projectOpened", token });
  }, [status.token]);

  // Refresh layer-specific overview counts without resetting an active spectrum.
  useEffect(() => {
    if (!ready || !state.token) return;
    const token = state.token;
    const layer = state.layer;
    loadProject<ProjectSummary>({
      url: base + "?layer=" + encodeURIComponent(layer),
      onSuccess: (project) =>
        dispatch({
          type: "projectLoaded",
          token,
          layer,
          project,
          preferredSource: new URLSearchParams(location.search).get("source")
        })
    });
    return cancelProject;
  }, [ready, state.token, state.layer, base, loadProject, cancelProject]);

  // Source changes clear old evidence in the reducer before this request starts.
  useEffect(() => {
    if (!ready || !state.source) return;
    const token = state.token;
    const source = state.source;
    loadMap<MapData>({
      url: base + "/sources/" + encodeURIComponent(source) + "/map",
      onSuccess: (map) => dispatch({ type: "mapLoaded", token, source, map })
    });
    return cancelMap;
  }, [ready, state.token, state.source, base, loadMap, cancelMap]);

  // Spectrum and map-target requests share a lane: either selection replaces the other.
  useEffect(() => {
    const selection = state.selection;
    if (!ready || !selection) return;
    const token = state.token;
    const revision = selection.revision;
    if (selection.kind === "spectrum") {
      loadSelection<Spectrum>({
        url:
          base +
          "/sources/" +
          encodeURIComponent(selection.source) +
          "/spectra/" +
          selection.ordinal,
        onSuccess: (value) => {
          dispatch({ type: "spectrumLoaded", token, revision, spectrum: value });
        }
      });
    } else {
      loadSelection<MapTarget>({
        url: base + "/map-target",
        options: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selection.cell)
        },
        onSuccess: (value) =>
          dispatch({ type: "mapTargetLoaded", token, revision, target: value })
      });
    }
    return cancelSelection;
  }, [ready, state.token, state.selection, base, loadSelection, cancelSelection]);

  // Persist accepted state so an obsolete response cannot change the address bar.
  useEffect(() => {
    const selection = state.selection;
    if (!ready || !selection || !visible) return;
    const identifier = status.active_project_id || status.project_id;
    if (selection.kind === "mapTarget") {
      ProjectLocation.selection(identifier, { source: selection.cell.source });
    } else if (state.spectrum) {
      const parameters: Record<string, string> = {
        source: state.spectrum.source,
        scan: String(state.spectrum.ordinal)
      };
      if (selection.psmId) parameters.psm = String(selection.psmId);
      ProjectLocation.selection(identifier, parameters);
    }
  }, [
    ready,
    state.selection,
    state.spectrum,
    visible,
    status.active_project_id,
    status.project_id
  ]);

  // Annotation changes leave measured peaks and the time viewport untouched.
  useEffect(() => {
    dispatch({ type: "annotationsCleared" });
    if (!ready || !state.candidate) return;
    const token = state.token;
    const candidateId = state.candidate.id;
    loadAnnotations<Annotation[]>({
      url: base + "/psms/" + candidateId + "/annotations?ppm=" + Number(fragmentPpm),
      onSuccess: (annotations) =>
        dispatch({ type: "annotationsLoaded", token, candidateId, annotations })
    });
    return cancelAnnotations;
  }, [
    ready,
    state.token,
    state.candidate?.id,
    fragmentPpm,
    base,
    loadAnnotations,
    cancelAnnotations
  ]);

  // Restore a linked scan once; an explicit selection takes precedence over the link.
  useEffect(() => {
    if (!ready || !state.source || restored.current === state.token) return;
    restored.current = state.token;
    if (state.selection) return;
    const parameters = new URLSearchParams(location.search);
    const scan = parameters.get("scan");
    if (parameters.get("source") === state.source && scan !== null) {
      dispatch({
        type: "spectrumRequested",
        source: state.source,
        ordinal: Number(scan),
        psmId: Number(parameters.get("psm")) || undefined
      });
    }
  }, [ready, state.source, state.token, state.selection]);

  /** A selected PSM carries its acquisition and scan in one atomic action. */
  function choosePsm(psm: Psm) {
    if (!psm.resolved || psm.source === null || psm.ordinal === null) {
      dispatch({
        type: "errorRaised",
        message:
          psm.link_reason ||
          "This PSM has an unresolved source or native spectrum reference."
      });
      return;
    }
    dispatch({
      type: "spectrumRequested",
      source: psm.source,
      ordinal: psm.ordinal,
      psmId: psm.id
    });
  }

  /** Keep map and chromatogram viewports synchronized in minutes. */
  function changeTimeRange(event: PlotRelayoutEvent) {
    if (event["xaxis.autorange"]) {
      dispatch({ type: "viewportChanged" });
      return;
    }
    const start = Number(event["xaxis.range[0]"]);
    const stop = Number(event["xaxis.range[1]"]);
    if (Number.isFinite(start) && Number.isFinite(stop)) {
      dispatch({ type: "viewportChanged", range: [start, stop] });
    }
  }

  /** Clear the displayed domain or request error without changing the selection. */
  function clearError() {
    dispatch({ type: "errorCleared" });
    projectRequest.clearError();
    mapRequest.clearError();
    selectionRequest.clearError();
    annotationRequest.clearError();
  }

  return {
    state,
    base,
    ready,
    choosePsm,
    changeTimeRange,
    clearError,
    error:
      state.error ||
      projectRequest.error ||
      mapRequest.error ||
      selectionRequest.error ||
      annotationRequest.error,
    selectSample: (sample: string) => dispatch({ type: "sampleSelected", sample }),
    selectSource: (source: string) => dispatch({ type: "sourceSelected", source }),
    selectLayer: (layer: string) => dispatch({ type: "layerSelected", layer }),
    selectCandidate: (candidate: Psm) =>
      dispatch({ type: "candidateSelected", candidate }),
    openSpectrum: (source: string, ordinal: number) =>
      dispatch({ type: "spectrumRequested", source, ordinal }),
    chooseMapCell: (cell: MapCell) => dispatch({ type: "mapTargetRequested", cell })
  };
}
