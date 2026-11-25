import { useEffect, useState } from "react";
import type { AcquisitionMode, FragmentTrace, Psm, Trace } from "./api";
import { useApiRequest } from "./useApiRequest";

interface Context {
  base: string;
  source: string;
  mode?: AcquisitionMode;
  candidate?: Psm;
  trace?: Trace;
  ppm: number;
  rtRange?: [number, number];
  matchedCount: number;
}

/** Request fragments only after explicit activation for the current selected PSM. */
export function useFragmentChromatograms({
  base,
  source,
  mode,
  candidate,
  trace,
  ppm,
  rtRange,
  matchedCount
}: Context) {
  const selection = `${base}:${source}:${candidate?.id}`;
  const [activation, setActivation] = useState({ selection, enabled: false });
  // Reset activation before rendering a different PSM, including a return to one
  // inspected earlier. Interval and tolerance changes retain the current choice.
  if (activation.selection !== selection) {
    setActivation({ selection, enabled: false });
  }
  const [relative, setRelative] = useState(false);
  const [loaded, setLoaded] = useState<{ key: string; trace: FragmentTrace }>();
  const { run, cancel, loading, error } = useApiRequest();

  // Fragments describe the selected peptide, never a manually edited or map target.
  const sameTarget =
    trace &&
    candidate?.precursor_mz &&
    Math.abs(trace.mz - candidate.precursor_mz) < candidate.precursor_mz * 1e-10;
  const available =
    mode === "DIA" &&
    candidate?.source === source &&
    Boolean(candidate?.resolved && sameTarget && matchedCount && ppm > 0);
  const start = trace
    ? Math.max(trace.start, rtRange ? rtRange[0] * 60 : trace.start)
    : 0;
  const stop = trace ? Math.min(trace.stop, rtRange ? rtRange[1] * 60 : trace.stop) : 0;
  const enabled = activation.selection === selection && activation.enabled;
  const key = JSON.stringify([selection, ppm, start, stop, available]);
  const result = enabled && loaded?.key === key ? loaded.trace : undefined;

  useEffect(() => {
    cancel();
    setLoaded(undefined);
    if (!enabled || !available || stop <= start || !candidate) return;
    void run<FragmentTrace>({
      url: base + "/fragment-xic",
      options: {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ psm_id: candidate.id, ppm, start, stop })
      },
      onSuccess: (value) => {
        if (
          value.source !== source ||
          value.psm_id !== candidate.id ||
          value.fragments.some(
            (fragment) => fragment.intensity.length !== value.rt.length
          )
        ) {
          throw new Error(
            "The server returned fragment traces for a different selection."
          );
        }
        setLoaded({ key, trace: value });
      }
    });
    return cancel;
  }, [key, enabled, run, cancel]);

  return {
    available,
    enabled,
    result,
    loading,
    error,
    relative,
    setRelative,
    toggle: () => setActivation({ selection, enabled: !enabled })
  };
}
