import { useMemo } from "react";
import { NumberInput, Table } from "@mantine/core";
import type { Data } from "plotly.js";
import { Acquisition, Annotation, Psm, Spectrum } from "./api";
import { Plot } from "./Plot";
import { FragmentIons } from "./FragmentIons";
import { FragmentIonTable } from "./FragmentIonTable";
import type { FragmentSelection } from "./useFragmentSelection";

interface Props {
  source: string;
  active?: Acquisition;
  spectrum?: Spectrum;
  candidate?: Psm;
  annotations: Annotation[];
  fragmentSelection: FragmentSelection;
  fragmentPpm: number | string;
  setFragmentPpm: (value: number | string) => void;
  setCandidate: (candidate: Psm) => void;
}

/**
 * Show measured fragment peaks and candidate assignments for the selected
 * spectrum.
 */
export function SpectrumInspector({
  source,
  active,
  spectrum,
  candidate,
  annotations,
  fragmentSelection,
  fragmentPpm,
  setFragmentPpm,
  setCandidate
}: Props) {
  const spectrumData = useMemo(() => {
    if (!spectrum) {
      return [];
    }
    // Each centroid becomes a vertical stick; null separates it from the next
    // peak.
    const x: (number | null)[] = [],
      y: (number | null)[] = [];
    spectrum.masses.forEach((mass, index) => {
      x.push(mass, mass, null);
      y.push(0, spectrum.intensities[index], null);
    });
    // Annotation indices refer back to the same measured peak arrays.
    const traces = [
      {
        x,
        y,
        type: "scatter",
        mode: "lines",
        line: {
          color: "#6d8195",
          width: 1
        },
        hoverinfo: "skip"
      },
      {
        x: annotations.map((item) => spectrum.masses[item.index]),
        y: annotations.map((item) => spectrum.intensities[item.index]),
        text: annotations.map((item) => item.label),
        customdata: annotations.map((item) => FragmentIons.id(item)),
        mode: "markers+text",
        textposition: "top center",
        marker: {
          color: annotations.map((item) => FragmentIons.color(item)),
          size: annotations.map((item) =>
            FragmentIons.id(item) === fragmentSelection.focused ? 9 : 5
          )
        },
        textfont: { color: annotations.map((item) => FragmentIons.color(item)) },
        type: "scatter",
        hovertemplate: "%{text}<br>%{x:.5f} m/z<extra></extra>"
      }
    ] as Data[];
    const focused = annotations.find(
      (item) => FragmentIons.id(item) === fragmentSelection.focused
    );
    if (focused) {
      const mass = spectrum.masses[focused.index];
      traces.push({
        x: [mass, mass],
        y: [0, spectrum.intensities[focused.index]],
        type: "scatter",
        mode: "lines",
        line: { color: FragmentIons.color(focused), width: 3 },
        hoverinfo: "skip"
      });
    }
    return traces;
  }, [spectrum, annotations, fragmentSelection.focused]);

  return (
    <aside className="panel inspector">
      <div className="panel-title">
        <h2>Evidence inspector</h2>
        <span>{spectrum ? spectrum.native : "Choose a scan"}</span>
      </div>
      {spectrum ? (
        <>
          <div className="scan-info">
            <strong>{candidate?.sequence || "Unassigned spectrum"}</strong>
            <span>
              {active?.fraction} · {(spectrum.rt / 60).toFixed(2)} min · isolation center{" "}
              {spectrum.mz?.toFixed(5)} m/z · charge{" "}
              {candidate?.charge || spectrum.charge || "unreported"}
            </span>
          </div>
          <NumberInput
            className="tolerance"
            label="Fragment tolerance (ppm)"
            value={fragmentPpm}
            onChange={setFragmentPpm}
            min={0.1}
            max={1000}
          />
          {/* Preserve spectrum zoom when switching candidates for the same source and scan. */}
          <Plot
            data={spectrumData}
            onClick={(event) => {
              const ion = event.points.find(
                (item) => typeof item.customdata === "string"
              );
              if (ion) fragmentSelection.focus(String(ion.customdata));
            }}
            layout={{
              uirevision: source + spectrum.ordinal,
              xaxis: { title: { text: "Fragment m/z" } },
              yaxis: { title: { text: "Intensity" } },
              showlegend: false
            }}
          />
          {candidate && (
            <FragmentIonTable
              key={`${source}:${spectrum.ordinal}:${candidate.id}`}
              mode={active?.mode}
              fragments={fragmentSelection}
            />
          )}
          <h3>Assignments</h3>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Layer</Table.Th>
                <Table.Th>Sequence</Table.Th>
                <Table.Th>Score</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {spectrum.candidates.map((row) => (
                <Table.Tr
                  key={row.id}
                  className={candidate?.id === row.id ? "selected" : ""}
                  onClick={() => setCandidate(row)}
                >
                  <Table.Td>{row.layer}</Table.Td>
                  <Table.Td>{row.sequence}</Table.Td>
                  <Table.Td
                    title={
                      row.score_type +
                      (row.higher_better ? " (higher is better)" : " (lower is better)")
                    }
                  >
                    {row.score.toPrecision(3)}
                    <small>{row.score_type}</small>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </>
      ) : (
        <div className="empty">
          Enable MS2 events and click a marker, or select a PSM below to inspect its
          measured spectrum.
        </div>
      )}
    </aside>
  );
}
