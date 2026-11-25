import { useEffect, useRef, useState } from "react";
import type { MapData, MapTarget, Psm, Spectrum, Trace } from "./api";
import { useApiRequest } from "./useApiRequest";

interface Context {
  base: string;
  source: string;
  map?: MapData;
  spectrum?: Spectrum;
  candidate?: Psm;
  mapTarget?: MapTarget;
  rtRange?: [number, number];
}

/**
 * Capture the submitted target and RT bounds in seconds independently of later
 * edits.
 */
interface Extraction {
  base: string;
  source: string;
  mz: number;
  ppm: number;
  start: number;
  stop: number;
  label: string;
}

interface LabeledTrace extends Trace {
  label: string;
}

/** Own MS1 targets, automatic/manual extraction, and obsolete-request cancellation. */
export function usePrecursorChromatogram({
  base,
  source,
  map,
  spectrum,
  candidate,
  mapTarget,
  rtRange
}: Context) {
  const [target, setTarget] = useState<number | string>("");
  const [ppm, setPpm] = useState<number | string>(10);
  const [trace, setTrace] = useState<LabeledTrace>();
  const { run: extractTrace, cancel: cancelExtraction, loading: busy } = useApiRequest();
  const [error, setError] = useState("");

  // Read current controls without making each keystroke trigger automatic
  // extraction.
  const latest = useRef({
    base,
    source,
    map,
    spectrum,
    candidate,
    mapTarget,
    rtRange,
    ppm
  });
  latest.current = {
    base,
    source,
    map,
    spectrum,
    candidate,
    mapTarget,
    rtRange,
    ppm
  };

  // A different acquisition or project must not retain the previous signal or
  // target.
  useEffect(() => {
    cancelExtraction();
    setTrace(undefined);
    setError("");
    setTarget("");
  }, [source, base, cancelExtraction]);

  useEffect(() => {
    const context = latest.current;
    // A map click already resolves the coarse cell to a precise measured peak.
    if (context.mapTarget?.source === context.source && context.map) {
      const range = context.rtRange
        ? context.rtRange.map((value) => value * 60)
        : context.map.bounds.slice(0, 2);
      setTarget(context.mapTarget.mz);
      extract({
        base: context.base,
        source: context.source,
        mz: context.mapTarget.mz,
        ppm: Number(context.ppm),
        start: Math.max(0, range[0]),
        stop: range[1],
        label: "MS1 map selection · strongest peak in cell"
      });
      return;
    }
    if (!context.spectrum) {
      cancelExtraction();
      setTrace(undefined);
      return;
    }
    if (!context.map || context.spectrum?.source !== context.source) {
      return;
    }
    // Identifications provide a peptide m/z; an unassigned scan provides an
    // isolation center.
    const mz = context.candidate?.precursor_mz || context.spectrum.mz;
    if (!mz) {
      return;
    }
    setTarget(mz);
    const label = context.candidate?.precursor_mz
      ? context.candidate.precursor_mz_origin === "idXML"
        ? "Peptide precursor from idXML"
        : "Calculated peptide precursor"
      : "MS2 isolation center";
    // Keep the visible interval only when it contains the selected spectrum.
    const range =
      context.rtRange &&
      context.spectrum.rt / 60 >= context.rtRange[0] &&
      context.spectrum.rt / 60 <= context.rtRange[1]
        ? context.rtRange.map((value) => value * 60)
        : context.map.bounds.slice(0, 2);
    extract({
      base: context.base,
      source: context.source,
      mz,
      ppm: Number(context.ppm),
      start: Math.max(0, range[0]),
      stop: range[1],
      label
    });
  }, [spectrum, candidate?.id, mapTarget, map, source, base]);

  /**
   * Submit an immutable extraction and ignore results superseded by a newer
   * selection.
   */
  async function extract(request: Extraction) {
    setError("");
    setTrace(undefined);
    await extractTrace<Trace>({
      url: request.base + "/xic",
      options: {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: request.source,
          mz: request.mz,
          ppm: request.ppm,
          start: request.start,
          stop: request.stop
        })
      },
      onSuccess: (result) => {
        if (
          result.rt.length !== result.intensity.length ||
          !result.rt.every(Number.isFinite) ||
          !result.intensity.every(Number.isFinite)
        ) {
          throw new Error("The server returned invalid chromatogram values.");
        }
        setTrace({ ...result, label: request.label });
      },
      onError: (failure) => setError(failure.message)
    });
  }

  /**
   * Use the current controls and visible RT interval when the user clicks
   * Extract XIC.
   */
  function extractManual() {
    if (!map) {
      return;
    }
    const range = rtRange ? rtRange.map((value) => value * 60) : map.bounds.slice(0, 2);
    extract({
      base,
      source,
      mz: Number(target),
      ppm: Number(ppm),
      start: Math.max(0, range[0]),
      stop: range[1],
      label: "Manual target"
    });
  }

  return { target, setTarget, ppm, setPpm, trace, error, busy, extractManual };
}
