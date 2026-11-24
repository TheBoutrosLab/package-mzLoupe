import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Checkbox, Group, NumberInput } from "@mantine/core";
import type { Data, Layout, PlotRelayoutEvent } from "plotly.js";
import type { MapData, MapTarget, Psm, Spectrum, Trace } from "./api";
import { useApiRequest } from "./useApiRequest";
import { Plot } from "./Plot";
import { PsmMarkers } from "./PsmMarkers";

interface Props {
  base: string;
  source: string;
  fraction?: string;
  layer: string;
  map?: MapData;
  spectrum?: Spectrum;
  candidate?: Psm;
  mapTarget?: MapTarget;
  rtRange?: [number, number];
  cursor: Layout["shapes"];
  onZoom: (event: PlotRelayoutEvent) => void;
  onPsm: (psm: Psm) => void;
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

/**
 * Extract and display MS1 signal for a peptide, map peak, or manually entered
 * target.
 */
export function PrecursorChromatogram({
  base,
  source,
  fraction,
  layer,
  map,
  spectrum,
  candidate,
  mapTarget,
  rtRange,
  cursor,
  onZoom,
  onPsm
}: Props) {
  const [target, setTarget] = useState<number | string>("");
  const [ppm, setPpm] = useState<number | string>(10);
  const [trace, setTrace] = useState<LabeledTrace>();
  const { run: extractTrace, cancel: cancelExtraction, loading: busy } = useApiRequest();
  const [error, setError] = useState("");
  const [showPsms, setShowPsms] = useState(true);

  // Evidence belongs to the submitted extraction, independently of table filters
  // and later edits to the m/z or tolerance controls.
  const psmScans = useMemo(() => PsmMarkers.group(trace?.psms || []), [trace]);
  const psmCount = trace?.psms.length || 0;
  const psmSummary =
    `${psmCount} matching ${psmCount === 1 ? "PSM" : "PSMs"} in ` +
    `${psmScans.length} MS2 ${psmScans.length === 1 ? "scan" : "scans"}`;
  const data: Data[] = [];
  if (trace) {
    data.push({
      x: trace.rt.map((rt) => rt / 60),
      y: trace.intensity,
      type: "scatter",
      mode: "lines",
      name: "MS1 intensity",
      line: { color: "#008979" }
    });
    if (showPsms && psmScans.length) {
      data.push(PsmMarkers.plot(psmScans, layer, candidate?.id));
    }
  }

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

  return (
    <section className="panel chromatogram-panel">
      <div className="panel-title">
        <h2>Precursor chromatogram</h2>
        <span>{fraction}</span>
      </div>
      <Group
        className="extraction"
        align="end"
      >
        <NumberInput
          label="Target m/z"
          value={target}
          onChange={setTarget}
          decimalScale={5}
          min={1}
        />
        <NumberInput
          label="Tolerance (ppm)"
          value={ppm}
          onChange={setPpm}
          min={0.1}
          max={1000}
        />
        <Button
          onClick={extractManual}
          loading={busy}
          disabled={!map || Number(target) <= 0 || !Number(ppm)}
        >
          Extract XIC
        </Button>
        <Checkbox
          label="Show PSMs (all layers)"
          checked={showPsms}
          onChange={(event) => setShowPsms(event.currentTarget.checked)}
        />
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {busy && <p className="caption">Extracting MS1 chromatogram…</p>}
      {trace && (
        <p className="caption">
          {trace.label} · {trace.mz.toFixed(5)} m/z · ±{trace.ppm} ppm ·{" "}
          {(trace.start / 60).toFixed(2)}–{(trace.stop / 60).toFixed(2)} min
        </p>
      )}
      {trace?.scan_count === 0 && (
        <p className="caption">No MS1 scans are available in this time interval.</p>
      )}
      {trace && trace.scan_count > 0 && trace.matched_scan_count === 0 && (
        <p className="caption">
          No positive MS1 signal was found within this m/z tolerance.
        </p>
      )}
      {trace && showPsms && (
        <p className="caption">
          {trace.psms.length > 0
            ? `${psmSummary} · all layers. Hover a mark for assignments; click to inspect.`
            : "No matching PSMs in this fraction, time interval, and m/z tolerance (all layers)."}
        </p>
      )}
      {trace && (trace.scan_count > 0 || psmScans.length > 0) ? (
        <Plot
          data={data}
          onClick={(event) => {
            // Only evidence marks carry a PSM ID; clicking the signal line does
            // not change the selected spectrum.
            const point = event.points.find(
              (item) => typeof item.customdata === "number"
            );
            const psm = trace.psms.find((item) => item.id === point?.customdata);
            if (psm) {
              onPsm(psm);
            }
          }}
          onZoom={onZoom}
          layout={{
            shapes: cursor,
            xaxis: {
              range:
                rtRange || (map ? [map.bounds[0] / 60, map.bounds[1] / 60] : undefined),
              title: { text: "Retention time (min)" }
            },
            yaxis: {
              title: { text: "Intensity" },
              rangemode: "tozero"
            },
            // Marks form a bottom evidence row, separate from measured intensity.
            yaxis2: {
              overlaying: "y",
              range: [0, 1],
              visible: false,
              fixedrange: true,
              showgrid: false,
              zeroline: false
            },
            showlegend: false
          }}
        />
      ) : (
        !busy &&
        !trace && (
          <div className="empty small">
            Select a PSM or click the MS1 map to extract a chromatogram automatically, or
            enter an m/z target.
          </div>
        )
      )}
    </section>
  );
}
