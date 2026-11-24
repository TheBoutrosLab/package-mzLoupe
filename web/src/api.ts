/** Summary counts and identification layers for one mzML acquisition. */
export interface Acquisition {
  id: string;
  sample: string;
  fraction: string;
  ms2: number;
  // Null means the selected identification layer is unavailable for this source.
  identified: number | null;
  layers: string[];
}

/** A peptide candidate and its resolved or unresolved spectrum reference. */
export interface Psm {
  id: number;
  // Unresolved candidates remain searchable without an assigned acquisition.
  source: string | null;
  layer: string;
  sequence: string;
  // Distinct, unmodified accessions from this hit's peptide evidences.
  protein_accessions: string[];
  protein_groupings?: ProteinGroupingAssignment[];
  // Peptide precursor m/z comes from idXML or a sequence/charge calculation.
  precursor_mz: number | null;
  precursor_mz_origin: string | null;
  score: number;
  score_type: string;
  higher_better: boolean;
  rank: number;
  resolved: number;
  ordinal: number | null;
  fraction: string | null;
  rt: number | null; // Retention time in seconds.
  link_reason: string;
  native: string;
  charge: number;
}

/** Measured peak arrays and candidate assignments for a source-scoped scan. */
export interface Spectrum {
  source: string;
  ordinal: number;
  native: string;
  rt: number; // Retention time in seconds.
  mz: number | null; // Isolation center from the scan's precursor metadata.
  charge: number | null;
  level: number;
  // Masses and intensities use the same peak index, also used by annotations.
  masses: number[];
  intensities: number[];
  candidates: Psm[];
}

/** Binned MS1 overview and selectable MS2 events for one acquisition. */
export interface MapData {
  // Rows are m/z bins; columns are RT bins. Values are log10(1 + summed intensity).
  intensity: number[][];
  // [RT start, RT stop, m/z start, m/z stop]; RT bounds are in seconds.
  bounds: number[];
  scale_max: number;
  events: {
    ordinal: number;
    rt: number;
    mz: number;
  }[];
}

/** An extracted MS1 chromatogram with the parameters used to produce it. */
export interface Trace {
  source: string;
  start: number; // Requested RT bounds are in seconds.
  stop: number;
  scan_count: number;
  matched_scan_count: number; // MS1 scans with positive signal in the m/z window.
  rt: number[]; // Retention times in seconds, paired with intensity values.
  intensity: number[];
  mz: number;
  ppm: number;
  // All resolved candidates within this extraction's fraction, RT, and m/z bounds.
  psms: Psm[];
}

/** The strongest measured MS1 peak resolved from a selected map cell. */
export interface MapTarget {
  source: string;
  rt: number; // Retention time in seconds.
  mz: number;
  intensity: number;
  ordinal: number;
}

/** Full bounds of a coarse heatmap cell, sent to resolve a precise MS1 target. */
export interface MapCell {
  source: string;
  start: number; // RT bounds in seconds.
  stop: number;
  mz_start: number;
  mz_stop: number;
}

/** A fragment-ion assignment to an index in the measured spectrum's arrays. */
export interface Annotation {
  index: number;
  label: string;
  ppm: number; // Signed mass error in parts per million.
}

/** Preserve the HTTP status when callers need to handle a recoverable conflict. */
export class ApiError extends Error {
  /** Attach the HTTP status to an error displayed or handled by the caller. */
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Shared JSON requests, server error handling, and project URL construction. */
export class ApiClient {
  /** Forward request options, including cancellation, and decode the JSON response. */
  async request<T>(url: string, options?: RequestInit): Promise<T> {
    const response = await fetch(url, options);

    if (!response.ok) {
      // API errors normally contain detail; non-JSON errors use the HTTP status text.
      const body = await response.json().catch(() => ({
        detail: response.statusText
      }));

      throw new ApiError(
        typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail),
        response.status
      );
    }

    return response.json();
  }

  /** Scope requests to the prepared project identified by the server's token. */
  projectUrl(token: string): string {
    return "/api/projects/" + encodeURIComponent(token);
  }
}

/** One shared client for same-origin dashboard API requests. */
export const apiClient = new ApiClient();

/** One identification result layer and its path on the server machine. */
export interface IdentificationInput {
  name: string;
  path: string;
}

/** The exact OpenMS collection selected when loading an inference idXML. */
export type GroupCollection = "protein_groups" | "indistinguishable_proteins";

/** A cohort grouping file with optional sample and identification-layer scopes. */
export interface ProteinGroupingInput {
  name: string;
  path: string;
  collection: GroupCollection;
  samples: string[];
  layers: string[];
}

/** One possible group assignment; original accession order defines its representative. */
export interface ProteinGroupingAssignment {
  name: string;
  collection: GroupCollection;
  basis: "spectrum" | "peptide" | "accession_overlap";
  status: "assigned" | "ambiguous" | "unassigned";
  inferred_accessions?: string[];
  groups: {
    id: string;
    members: string[];
    probability: number | null;
    stored_probability: number;
  }[];
}

export interface ProteinGroupingSummary extends ProteinGroupingInput {
  group_count: number;
}

/** File associations needed to register one acquisition in a project. */
export interface AcquisitionInput {
  id: string;
  sample: string;
  fraction: string;
  mzml: string;
  // Alternate source filenames help resolve references retained in merged idXML.
  aliases?: string[];
}

/** The manifest shared by JSON import/export and the interactive project editor. */
export interface ProjectConfiguration {
  protein_groupings?: ProteinGroupingInput[];
  name: string;
  acquisitions: AcquisitionInput[];
  // Each sample can own identification layers spanning several mzML fractions.
  samples: {
    name: string;
    identifications: IdentificationInput[];
  }[];
}

/** Server preparation state, polled independently of the visible application tab. */
export interface ProjectStatus {
  state: string;
  message: string;
  progress: number; // Preparation fraction between 0 and 1.
  token: string | null;
}

/** Literal text matching used by peptide, scan, and protein column filters. */
export interface PsmTextFilter {
  value: string;
  mode: "contains" | "exact";
}

/** Column conditions shared with the backend; retention bounds are minutes. */
export interface PsmColumnFilters {
  fractions: string[];
  layers: string[];
  sequence: PsmTextFilter;
  native: PsmTextFilter;
  proteins: PsmTextFilter;
  precursor_mz_min: number | null;
  precursor_mz_max: number | null;
  rt_min: number | null;
  rt_max: number | null;
  score_min: number | null;
  score_max: number | null;
  score_type: string;
  link: "" | "resolved" | "unresolved";
}

export type PsmSortColumn =
  | "fraction"
  | "sequence"
  | "proteins"
  | "native"
  | "precursor_mz"
  | "rt"
  | "layer"
  | "score"
  | "resolved";

/** Available filter choices across the scoped dataset, independent of its current page. */
export interface PsmFacets {
  fractions: { value: string; label: string }[];
  layers: string[];
  score_types: string[];
}

export interface PsmPage {
  rows: Psm[];
  total: number;
  peptides: number;
  page: number;
  page_size: number;
  facets: PsmFacets;
}

/** Project metadata and overview counts returned for the selected layer. */
export interface ProjectSummary {
  name: string;
  acquisitions: Acquisition[];
  protein_groupings: ProteinGroupingSummary[];
}
