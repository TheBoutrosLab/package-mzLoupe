import type { PsmColumnFilters, PsmSortColumn } from "./api";

/** State needed to request a complete-dataset filter/order and one display page. */
export interface PsmTableRequest {
  filters: PsmColumnFilters;
  sort: { columnAccessor: PsmSortColumn; direction: "asc" | "desc" };
  page: number; // Mantine DataTable uses one-based page numbers.
  pageSize: number;
  scope: "fraction" | "sample";
}

/** Keep query serialization and validation separate from React rendering. */
export class PsmTableQuery {
  /** Return fresh nested filters so edits never share mutable default values. */
  static filters(layer = ""): PsmColumnFilters {
    return {
      fractions: [],
      layers: layer ? [layer] : [],
      sequence: { value: "", mode: "contains" },
      native: { value: "", mode: "contains" },
      proteins: { value: "", mode: "contains" },
      precursor_mz_min: null,
      precursor_mz_max: null,
      rt_min: null,
      rt_max: null,
      score_min: null,
      score_max: null,
      score_type: "",
      link: ""
    };
  }

  /** Start in the active fraction and the globally selected identification layer. */
  static initial(layer: string): PsmTableRequest {
    return {
      filters: this.filters(layer),
      sort: { columnAccessor: "rt", direction: "asc" },
      page: 1,
      pageSize: 50,
      scope: "fraction"
    };
  }

  /** Reject reversed bounds locally while retaining the last valid results. */
  static error(filters: PsmColumnFilters): string {
    for (const [label, lower, upper] of [
      ["Precursor m/z", filters.precursor_mz_min, filters.precursor_mz_max],
      ["RT", filters.rt_min, filters.rt_max],
      ["Score", filters.score_min, filters.score_max]
    ] as const) {
      if (lower != null && upper != null && lower > upper) {
        return `${label} minimum must not exceed maximum.`;
      }
    }
    return "";
  }

  /** Count filtered columns rather than counting both ends of a numeric interval. */
  static activeCount(filters: PsmColumnFilters): number {
    return [
      filters.fractions.length,
      filters.layers.length,
      filters.sequence.value,
      filters.native.value,
      filters.proteins.value,
      filters.precursor_mz_min != null || filters.precursor_mz_max != null,
      filters.rt_min != null || filters.rt_max != null,
      filters.score_min != null || filters.score_max != null || filters.score_type,
      filters.link
    ].filter(Boolean).length;
  }

  /** Convert display pages to the zero-based API and preserve all filter semantics. */
  static parameters(
    state: PsmTableRequest,
    sample: string,
    source: string,
    grouping: string
  ): URLSearchParams {
    const parameters = new URLSearchParams({
      sample,
      filters: JSON.stringify(state.filters),
      grouping,
      sort_by: state.sort.columnAccessor,
      sort_direction: state.sort.direction,
      page: String(state.page - 1),
      page_size: String(state.pageSize)
    });
    if (state.scope === "fraction") parameters.set("source", source);
    return parameters;
  }
}
