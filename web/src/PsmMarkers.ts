import type { Data } from "plotly.js";
import type { Psm } from "./api";

/** One MS2 scan and every candidate matching the current precursor extraction. */
export interface PsmScan {
  rt: number;
  candidates: Psm[];
}

/** Group chromatogram evidence and describe a selectable mark for each MS2 scan. */
export class PsmMarkers {
  /** Keep same-scan assignments together so layers and ranks do not hide each other. */
  static group(psms: Psm[]): PsmScan[] {
    const scans = new Map<string, PsmScan>();
    for (const psm of psms) {
      if (
        !psm.resolved ||
        psm.source === null ||
        psm.ordinal === null ||
        psm.rt === null
      ) {
        continue;
      }
      const key = psm.source + ":" + psm.ordinal;
      let scan = scans.get(key);
      if (!scan) {
        scan = { rt: psm.rt, candidates: [] };
        scans.set(key, scan);
      }
      scan.candidates.push(psm);
    }
    return [...scans.values()].sort((first, second) => first.rt - second.rt);
  }

  /** Prefer the selected candidate, then the active layer's best-ranked candidate. */
  static preferred(scan: PsmScan, layer: string, selectedId?: number): Psm {
    return (
      scan.candidates.find((psm) => psm.id === selectedId) ||
      scan.candidates.find((psm) => psm.layer === layer) ||
      scan.candidates[0]
    );
  }

  /** Escape file-supplied labels before inserting them into Plotly hover text. */
  static escape(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /** Show every matching candidate; different sequences at the same m/z remain visible. */
  static hover(scan: PsmScan): string {
    const assignments = scan.candidates.map((psm) => {
      const sequence = this.escape(psm.sequence);
      const layer = this.escape(psm.layer);
      const scoreType = this.escape(psm.score_type);
      return (
        `<b>${sequence}</b> · ${psm.charge}+ · ${psm.precursor_mz?.toFixed(5)} m/z` +
        `<br>${layer} · rank ${psm.rank} · ${scoreType}: ${psm.score.toPrecision(3)}`
      );
    });
    return (
      `${(scan.rt / 60).toFixed(2)} min · ${this.escape(scan.candidates[0].native)}` +
      "<br>" +
      assignments.join("<br><br>")
    );
  }

  /** Place marks on a fixed overlay axis so evidence never changes the intensity scale. */
  static plot(scans: PsmScan[], layer: string, selectedId?: number): Data {
    const selected = scans.map((scan) =>
      scan.candidates.some((psm) => psm.id === selectedId)
    );
    return {
      name: "PSM evidence",
      type: "scatter",
      mode: "markers",
      x: scans.map((scan) => scan.rt / 60),
      y: scans.map(() => 0.04),
      yaxis: "y2",
      customdata: scans.map((scan) => this.preferred(scan, layer, selectedId).id),
      hovertext: scans.map((scan) => this.hover(scan)),
      hovertemplate: "%{hovertext}<extra>PSM evidence</extra>",
      marker: {
        symbol: "triangle-up",
        size: selected.map((value) => (value ? 12 : 9)),
        color: selected.map((value) => (value ? "#e48735" : "#6554a4")),
        line: { color: "#ffffff", width: 1 }
      }
    };
  }
}
