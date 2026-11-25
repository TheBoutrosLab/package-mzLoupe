import { useMemo, useState } from "react";
import { Alert, Button, Checkbox, Group, NumberInput } from "@mantine/core";
import type { Data, Layout, PlotRelayoutEvent } from "plotly.js";
import type {
  AcquisitionMode,
  Annotation,
  MapData,
  MapTarget,
  Psm,
  Spectrum
} from "./api";
import { usePrecursorChromatogram } from "./usePrecursorChromatogram";
import { Plot } from "./Plot";
import { PsmMarkers } from "./PsmMarkers";
import { FragmentChromatograms } from "./FragmentChromatograms";
import { FragmentXicControls } from "./FragmentXicControls";
import { useFragmentChromatograms } from "./useFragmentChromatograms";
import type { FragmentSelection } from "./useFragmentSelection";

interface Props {
  base: string;
  source: string;
  fraction?: string;
  mode?: AcquisitionMode;
  annotations: Annotation[];
  fragmentPpm: number;
  fragmentSelection: FragmentSelection;
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
 * Extract and display MS1 signal for a peptide, map peak, or manually entered
 * target.
 */
export function PrecursorChromatogram({
  base,
  source,
  fraction,
  mode,
  annotations,
  fragmentPpm,
  fragmentSelection,
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
  const { target, setTarget, ppm, setPpm, trace, error, busy, extractManual } =
    usePrecursorChromatogram({
      base,
      source,
      map,
      spectrum,
      candidate,
      mapTarget,
      rtRange
    });
  const [showPsms, setShowPsms] = useState(true);
  const fragments = useFragmentChromatograms({
    base,
    source,
    mode,
    candidate: mapTarget ? undefined : candidate,
    trace,
    ppm: fragmentPpm,
    rtRange,
    matchedCount: annotations.length
  });
  const relative = Boolean(fragments.result && fragments.relative);

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
      y: FragmentChromatograms.intensities(trace.intensity, relative),
      type: "scatter",
      mode: "lines",
      name: "MS1 intensity",
      opacity:
        fragments.result &&
        fragmentSelection.focused &&
        fragmentSelection.selected.has(fragmentSelection.focused)
          ? 0.3
          : 1,
      line: { color: "#008979" }
    });
    if (fragments.result) {
      data.push(
        ...FragmentChromatograms.plot(
          fragments.result,
          fragmentSelection.selected,
          fragments.relative,
          fragmentSelection.focused
        )
      );
    }
    if (showPsms && psmScans.length) {
      data.push(PsmMarkers.plot(psmScans, layer, candidate?.id));
    }
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
      <FragmentXicControls
        mode={mode}
        fragments={fragments}
      />
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
            } else {
              const ion = event.points.find(
                (item) => typeof item.customdata === "string"
              );
              if (ion) fragmentSelection.focus(String(ion.customdata));
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
              title: { text: relative ? "Relative intensity (%)" : "Intensity" },
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
