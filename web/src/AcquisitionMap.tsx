import { useMemo, useState } from "react";
import { Checkbox, Group, Select } from "@mantine/core";
import type { Data, Layout, PlotRelayoutEvent } from "plotly.js";
import type { Acquisition, MapData, MapCell, MapTarget, Spectrum } from "./api";
import { Plot } from "./Plot";
import { HeatmapContrast } from "./HeatmapContrast";
import type { ContrastSettings } from "./HeatmapContrast";
import { HeatmapContrastControl } from "./HeatmapContrastControl";

interface Props {
  source: string;
  fractions: Acquisition[];
  map?: MapData;
  spectrum?: Spectrum;
  target?: MapTarget;
  onCell: (cell: MapCell) => void;
  // Plot viewports use minutes; requests to the server use seconds.
  rtRange?: [number, number];
  cursor: Layout["shapes"];
  onSource: (source: string) => void;
  onScan: (ordinal: number) => void;
  onZoom: (event: PlotRelayoutEvent) => void;
}

/**
 * Display one acquisition and emit either an MS2 scan or an MS1 cell selection.
 */
export function AcquisitionMap({
  source,
  fractions,
  map,
  spectrum,
  target,
  rtRange,
  cursor,
  onSource,
  onScan,
  onCell,
  onZoom
}: Props) {
  // Dense DIA acquisitions remain readable until the user enables all MS2
  // markers.
  const [showEvents, setShowEvents] = useState(false);
  const [contrast, setContrast] = useState<ContrastSettings>({ mode: "auto" });
  // Sort the small overview once per map. Selection and zoom changes only update
  // rendering, and custom limits stay fixed across acquisitions for comparison.
  const statistics = useMemo(() => new HeatmapContrast(map?.intensity || []), [map]);
  const colorLimits = statistics.limits(contrast);
  const data: Data[] = [];
  if (map) {
    // Match the server's 240 time bins and 160 m/z bins, positioning cells at
    // their centers.
    data.push({
      type: "heatmap",
      z: map.intensity,
      x: Array.from(
        { length: 240 },
        (_, index) =>
          (map.bounds[0] + ((index + 0.5) / 240) * (map.bounds[1] - map.bounds[0])) / 60
      ),
      y: Array.from(
        { length: 160 },
        (_, index) =>
          map.bounds[2] + ((index + 0.5) / 160) * (map.bounds[3] - map.bounds[2])
      ),
      zmin: colorLimits.lower,
      zmax: colorLimits.upper,
      colorscale: [
        [0, "#020329"],
        [0.22, "#071b63"],
        [0.45, "#1067a5"],
        [0.65, "#1bb1c0"],
        [0.82, "#a4dab7"],
        [1, "#ffe073"]
      ],
      showscale: false,
      hovertemplate:
        "%{x:.2f} min<br>%{y:.2f} m/z<br>log₁₀(1 + I): %{z:.2f}<extra>MS1 intensity</extra>"
    });
    if (showEvents) {
      data.push({
        type: "scatter",
        mode: "markers",
        x: map.events.map((event) => event.rt / 60),
        y: map.events.map((event) => event.mz),
        customdata: map.events.map((event) => event.ordinal),
        marker: {
          symbol: "diamond-open",
          color: "#c66b22",
          size: 4,
          opacity: 0.45
        },
        hovertemplate: "%{x:.2f} min<br>%{y:.4f} m/z<extra>MS2 isolation center</extra>"
      });
    }
    // Draw only selections belonging to the acquisition currently on screen.
    if (target?.source === source) {
      data.push({
        type: "scatter",
        mode: "markers",
        x: [target.rt / 60],
        y: [target.mz],
        marker: {
          symbol: "cross",
          color: "#d35f20",
          size: 10
        },
        hovertemplate: "%{x:.2f} min<br>%{y:.5f} m/z<extra>Selected MS1 peak</extra>"
      });
    }
    if (spectrum?.source === source && spectrum.level === 2 && spectrum.mz) {
      data.push({
        type: "scatter",
        mode: "markers",
        x: [spectrum.rt / 60],
        y: [spectrum.mz],
        customdata: [spectrum.ordinal],
        marker: {
          symbol: "diamond",
          color: "#e48735",
          size: 10,
          line: {
            color: "#fff",
            width: 1
          }
        },
        hovertemplate:
          "%{x:.2f} min<br>%{y:.4f} m/z<extra>Selected MS2 isolation center</extra>"
      });
    }
  }

  return (
    <section className="panel map-panel">
      <div className="panel-title">
        <h2>MS1 acquisition map</h2>
        <Group>
          {map && (
            <HeatmapContrastControl
              settings={contrast}
              limits={colorLimits}
              onChange={setContrast}
            />
          )}
          <Checkbox
            label="Show MS2 events"
            checked={showEvents}
            onChange={(event) => setShowEvents(event.currentTarget.checked)}
          />
          <Select
            aria-label="Active fraction"
            data={fractions.map((row) => ({
              value: row.id,
              label: row.fraction
            }))}
            value={source}
            onChange={(value) => onSource(value || "")}
          />
        </Group>
      </div>
      {map && (
        <Plot
          data={data}
          onZoom={onZoom}
          layout={{
            uirevision: source,
            shapes: cursor,
            plot_bgcolor: "#020329",
            xaxis: {
              range: rtRange || [map.bounds[0] / 60, map.bounds[1] / 60],
              title: { text: "Retention time (min)" }
            },
            yaxis: { title: { text: "MS1 m/z" } },
            showlegend: false
          }}
          onClick={(event) => {
            const point = event.points[0];
            // MS2 markers carry a scan ordinal; heatmap cells carry only coarse
            // coordinates.
            if (point.customdata !== undefined) {
              onScan(Number(point.customdata));
              return;
            }
            if (point.data.type !== "heatmap") {
              return;
            }
            // Send the full cell bounds so the server can locate a measured MS1
            // peak.
            const width = (map.bounds[1] - map.bounds[0]) / 240;
            const height = (map.bounds[3] - map.bounds[2]) / 160;
            const rt = Number(point.x) * 60;
            const mz = Number(point.y);
            onCell({
              source,
              start: Math.max(0, rt - width / 2),
              stop: rt + width / 2,
              mz_start: Math.max(Number.EPSILON, mz - height / 2),
              mz_stop: mz + height / 2
            });
          }}
        />
      )}
    </section>
  );
}
