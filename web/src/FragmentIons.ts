import type { Annotation, Spectrum } from "./api";

/** One peptide-fragment assignment and its measurement in the selected spectrum. */
export interface FragmentIon extends Annotation {
  id: string;
  intensity: number;
  peakAssignments: number;
}

export type FragmentSortColumn = "label" | "charge" | "mz" | "ppm" | "intensity";

/** Own fragment identities, spectrum measurements, ranking, and display colors. */
export class FragmentIons {
  /** Keep identity independent of table order, filtering, or extraction intervals. */
  static id(ion: Pick<Annotation, "label" | "charge" | "mz">): string {
    return `${ion.label}:${ion.charge}:${ion.mz.toPrecision(12)}`;
  }

  /** Generate colors from ion identity instead of cycling a fixed-size palette. */
  static color(ion: Pick<Annotation, "label" | "charge" | "mz">): string {
    let hash = 2166136261;
    for (const character of this.id(ion)) {
      hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
    }
    const hue = ((hash >>> 0) / 4294967296) * 360;
    return `hsl(${hue.toFixed(3)}, 65%, 40%)`;
  }

  /** Join annotations to measured intensities, retaining ambiguous peak assignments. */
  static rows(spectrum: Spectrum | undefined, annotations: Annotation[]): FragmentIon[] {
    if (!spectrum) return [];
    const counts = new Map<number, number>();
    for (const ion of annotations) {
      counts.set(ion.index, (counts.get(ion.index) || 0) + 1);
    }
    return annotations.map((ion) => ({
      ...ion,
      id: this.id(ion),
      intensity: spectrum.intensities[ion.index],
      peakAssignments: counts.get(ion.index) || 1
    }));
  }

  /** Rank by selected-spectrum intensity, without using chromatographic peak heights. */
  static top(rows: FragmentIon[], count = 6): Set<string> {
    return new Set(
      this.sort(rows, "intensity", "desc")
        .slice(0, count)
        .map((ion) => ion.id)
    );
  }

  /** Sort a copy so table ordering cannot mutate spectrum or selection state. */
  static sort(
    rows: FragmentIon[],
    column: FragmentSortColumn,
    direction: "asc" | "desc"
  ): FragmentIon[] {
    return [...rows].sort((left, right) => {
      const first = left[column];
      const second = right[column];
      const comparison =
        typeof first === "string" && typeof second === "string"
          ? first.localeCompare(second, undefined, { numeric: true })
          : Number(first) - Number(second);
      const ordered = direction === "asc" ? comparison : -comparison;
      return ordered || left.mz - right.mz || left.id.localeCompare(right.id);
    });
  }
}
