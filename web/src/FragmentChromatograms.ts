import type { Data } from "plotly.js";
import type { FragmentTrace } from "./api";
import { FragmentIons } from "./FragmentIons";

/** Pure display helpers keep measured intensities independent of view settings. */
export class FragmentChromatograms {
  /** Scale each visible ion to its own maximum, preserving empty and zero traces. */
  static intensities(values: number[], relative: boolean): number[] {
    if (!relative) return values;
    const maximum = values.reduce((largest, value) => Math.max(largest, value), 0);
    return values.map((value) => (maximum > 0 ? (100 * value) / maximum : 0));
  }

  /** Build one line per enabled fragment without adding unrelated-window zeros. */
  static plot(
    trace: FragmentTrace,
    selected: Set<string>,
    relative: boolean,
    focused?: string
  ): Data[] {
    const activeFocus = focused && selected.has(focused) ? focused : undefined;
    return trace.fragments
      .filter((fragment) => selected.has(FragmentIons.id(fragment)))
      .map((fragment) => ({
        x: trace.rt.map((rt) => rt / 60),
        y: this.intensities(fragment.intensity, relative),
        type: "scatter",
        mode: "lines",
        name: `${fragment.label} · ${fragment.mz.toFixed(5)} m/z`,
        customdata: trace.rt.map(() => FragmentIons.id(fragment)),
        opacity: activeFocus && FragmentIons.id(fragment) !== activeFocus ? 0.2 : 1,
        line: {
          color: FragmentIons.color(fragment),
          width: activeFocus === FragmentIons.id(fragment) ? 3 : 1.5
        },
        hovertemplate: "%{x:.2f} min<br>%{y:.3g}<extra>%{fullData.name}</extra>"
      }));
  }
}
