import type {
  Annotation,
  MapCell,
  MapData,
  MapTarget,
  ProjectSummary,
  Psm,
  Spectrum
} from "./api";

/** A selection intent stays stable while its requests complete. */
export type ExplorerSelection =
  | {
      kind: "spectrum";
      revision: number;
      source: string;
      ordinal: number;
      psmId?: number;
    }
  | { kind: "mapTarget"; revision: number; cell: MapCell };

/** Linked evidence changes together; independent display controls stay in the view. */
export interface ExplorerState {
  token: string;
  project: ProjectSummary;
  sample: string;
  source: string;
  layer: string;
  revision: number;
  selection?: ExplorerSelection;
  map?: MapData;
  spectrum?: Spectrum;
  candidate?: Psm;
  mapTarget?: MapTarget;
  annotations: Annotation[];
  rtRange?: [number, number];
  error: string;
}

/** Explicit transitions keep cross-fraction selection and stale responses predictable. */
export type ExplorerAction =
  | { type: "projectOpened"; token: string }
  | {
      type: "projectLoaded";
      token: string;
      layer: string;
      project: ProjectSummary;
      preferredSource: string | null;
    }
  | { type: "sampleSelected"; sample: string }
  | { type: "sourceSelected"; source: string }
  | { type: "layerSelected"; layer: string }
  | { type: "spectrumRequested"; source: string; ordinal: number; psmId?: number }
  | { type: "spectrumLoaded"; token: string; revision: number; spectrum: Spectrum }
  | { type: "mapTargetRequested"; cell: MapCell }
  | { type: "mapTargetLoaded"; token: string; revision: number; target: MapTarget }
  | { type: "mapLoaded"; token: string; source: string; map: MapData }
  | { type: "candidateSelected"; candidate: Psm }
  | { type: "annotationsCleared" }
  | {
      type: "annotationsLoaded";
      token: string;
      candidateId: number;
      annotations: Annotation[];
    }
  | { type: "viewportChanged"; range?: [number, number] }
  | { type: "errorRaised"; message: string }
  | { type: "errorCleared" };

/** Pure explorer transitions; requests and browser history belong to useExplorer. */
export class ExplorerModel {
  /** Return fresh state for a project that has not been loaded yet. */
  static initial(): ExplorerState {
    return {
      token: "",
      project: { name: "", acquisitions: [], protein_groupings: [] },
      sample: "",
      source: "",
      layer: "Validated",
      revision: 0,
      annotations: [],
      error: ""
    };
  }

  /** Invalidate pending evidence without changing the map or time viewport. */
  static clearEvidence(state: ExplorerState): ExplorerState {
    return {
      ...state,
      revision: state.revision + 1,
      selection: undefined,
      spectrum: undefined,
      candidate: undefined,
      mapTarget: undefined,
      annotations: [],
      error: ""
    };
  }

  /** Switch acquisition and clear all evidence belonging to the previous source. */
  static selectSource(state: ExplorerState, source: string): ExplorerState {
    if (source === state.source) return state;
    const acquisition = state.project.acquisitions.find((row) => row.id === source);
    return {
      ...ExplorerModel.clearEvidence(state),
      source,
      sample: acquisition?.sample || state.sample,
      map: undefined,
      rtRange: undefined
    };
  }

  /** Apply one domain action without network calls, mutation, or browser effects. */
  static reduce(state: ExplorerState, action: ExplorerAction): ExplorerState {
    switch (action.type) {
      case "projectOpened":
        return {
          ...ExplorerModel.initial(),
          token: action.token,
          layer: state.layer,
          revision: state.revision + 1
        };
      case "projectLoaded": {
        if (action.token !== state.token || action.layer !== state.layer) return state;
        const acquisitions = action.project.acquisitions;
        const preferred = acquisitions.find((row) => row.id === action.preferredSource);
        const sample = acquisitions.some((row) => row.sample === state.sample)
          ? state.sample
          : preferred?.sample || acquisitions[0]?.sample || "";
        const fractions = acquisitions.filter((row) => row.sample === sample);
        const source = fractions.some((row) => row.id === state.source)
          ? state.source
          : fractions.find((row) => row.id === action.preferredSource)?.id ||
            fractions[0]?.id ||
            "";
        const layers = [...new Set(acquisitions.flatMap((row) => row.layers))];
        return ExplorerModel.selectSource(
          {
            ...state,
            project: action.project,
            sample,
            layer: layers.includes(state.layer) ? state.layer : layers[0] || ""
          },
          source
        );
      }
      case "sampleSelected": {
        if (action.sample === state.sample) return state;
        const source =
          state.project.acquisitions.find((row) => row.sample === action.sample)?.id ||
          "";
        return ExplorerModel.selectSource({ ...state, sample: action.sample }, source);
      }
      case "sourceSelected":
        return ExplorerModel.selectSource(state, action.source);
      case "layerSelected":
        return { ...state, layer: action.layer, error: "" };
      case "spectrumRequested": {
        const next = ExplorerModel.clearEvidence(
          ExplorerModel.selectSource(state, action.source)
        );
        return {
          ...next,
          selection: {
            kind: "spectrum",
            revision: next.revision,
            source: action.source,
            ordinal: action.ordinal,
            psmId: action.psmId
          }
        };
      }
      case "spectrumLoaded": {
        if (
          action.token !== state.token ||
          action.revision !== state.revision ||
          state.selection?.kind !== "spectrum" ||
          action.spectrum.source !== state.source ||
          action.spectrum.ordinal !== state.selection.ordinal
        )
          return state;
        const spectrum = action.spectrum;
        const selectedId = state.selection.psmId;
        const candidate =
          spectrum.candidates.find((row) => row.id === selectedId) ||
          spectrum.candidates.find((row) => row.layer === state.layer);
        const rt = spectrum.rt / 60;
        const rtRange =
          state.rtRange && (rt < state.rtRange[0] || rt > state.rtRange[1])
            ? undefined
            : state.rtRange;
        return { ...state, spectrum, candidate, annotations: [], rtRange };
      }
      case "mapTargetRequested": {
        const next = ExplorerModel.clearEvidence(
          ExplorerModel.selectSource(state, action.cell.source)
        );
        return {
          ...next,
          selection: { kind: "mapTarget", revision: next.revision, cell: action.cell }
        };
      }
      case "mapTargetLoaded":
        if (
          action.token !== state.token ||
          action.revision !== state.revision ||
          state.selection?.kind !== "mapTarget" ||
          action.target.source !== state.source
        )
          return state;
        return { ...state, mapTarget: action.target };
      case "mapLoaded":
        return action.token === state.token && action.source === state.source
          ? { ...state, map: action.map }
          : state;
      case "candidateSelected":
        return state.spectrum?.candidates.some((row) => row.id === action.candidate.id)
          ? { ...state, candidate: action.candidate, annotations: [] }
          : state;
      case "annotationsCleared":
        return { ...state, annotations: [] };
      case "annotationsLoaded":
        return action.token === state.token && action.candidateId === state.candidate?.id
          ? { ...state, annotations: action.annotations }
          : state;
      case "viewportChanged":
        if (
          state.rtRange?.[0] === action.range?.[0] &&
          state.rtRange?.[1] === action.range?.[1]
        )
          return state;
        return { ...state, rtRange: action.range };
      case "errorRaised":
        return { ...state, error: action.message };
      case "errorCleared":
        return { ...state, error: "" };
    }
  }
}
