import { useState } from "react";
import { Alert, Button, Collapse, Select } from "@mantine/core";
import type { ProjectStatus } from "./api";
import { AcquisitionMap } from "./AcquisitionMap";
import { PrecursorChromatogram } from "./PrecursorChromatogram";
import { SpectrumInspector } from "./SpectrumInspector";
import { PsmTable } from "./PsmTable";
import { useExplorer } from "./useExplorer";
import { useFragmentSelection } from "./useFragmentSelection";

/** Compose linked evidence views around typed explorer transitions. */
export function Dashboard({
  status,
  visible = true
}: {
  status: ProjectStatus;
  visible?: boolean;
}) {
  const [overview, setOverview] = useState(true);
  const [fragmentPpm, setFragmentPpm] = useState<number | string>(20);
  const explorer = useExplorer(status, fragmentPpm, visible);
  const {
    state,
    base,
    ready,
    error,
    clearError,
    selectSample,
    selectSource,
    selectLayer,
    selectCandidate,
    choosePsm,
    openSpectrum,
    chooseMapCell,
    changeTimeRange
  } = explorer;
  const {
    project,
    sample,
    source,
    layer,
    mapTarget,
    map,
    rtRange,
    spectrum,
    candidate,
    annotations
  } = state;
  const fragmentSelection = useFragmentSelection(
    `${base}:${source}:${candidate?.id}:${spectrum?.ordinal}`,
    spectrum,
    annotations
  );
  const fractions = project.acquisitions.filter((row) => row.sample === sample);
  const active = fractions.find((row) => row.id === source);
  const layers = [...new Set(project.acquisitions.flatMap((row) => row.layers))];

  // Convert seconds to minutes; paper coordinates make the cursor span each
  // plot's height.
  const cursor = spectrum
    ? [
        {
          type: "line" as const,
          x0: spectrum.rt / 60,
          x1: spectrum.rt / 60,
          y0: 0,
          y1: 1,
          yref: "paper" as const,
          line: {
            color: "#e48735",
            dash: "dot" as const,
            width: 1
          }
        }
      ]
    : [];

  return (
    <div className="dashboard">
      {error && (
        <Alert
          color="red"
          withCloseButton
          onClose={clearError}
        >
          {error}
        </Alert>
      )}
      {ready ? (
        <>
          <section className="toolbar">
            <Select
              label="Sample"
              data={[...new Set(project.acquisitions.map((row) => row.sample))]}
              value={sample}
              onChange={(value) => selectSample(value || "")}
            />
            <Select
              label="Identification layer"
              data={layers}
              value={layers.includes(layer) ? layer : null}
              placeholder="Choose a layer"
              onChange={(value) => selectLayer(value || "")}
            />
            <Button
              variant="subtle"
              onClick={() => setOverview(!overview)}
            >
              {overview ? "Collapse overview" : "Sample overview"}
            </Button>
          </section>
          {/* The overview summarizes all fractions; the plots below show the active acquisition. */}
          <Collapse in={overview}>
            <section className="overview">
              <div className="overview-heading">
                <h2>Sample overview</h2>
                <span>
                  {fractions.length} fractions ·{" "}
                  {fractions.reduce((sum, row) => sum + row.ms2, 0).toLocaleString()} MS2
                  scans
                </span>
              </div>
              <div className="fraction-cards">
                {fractions.map((row) => (
                  <button
                    className={source === row.id ? "fraction active" : "fraction"}
                    key={row.id}
                    onClick={() => selectSource(row.id)}
                  >
                    <b>{row.fraction}</b>
                    <span>{row.ms2.toLocaleString()} MS2 scans</span>
                    <strong>
                      {row.identified === null
                        ? "No ID layer"
                        : ((100 * row.identified) / Math.max(1, row.ms2)).toFixed(1) +
                          "% identified"}
                    </strong>
                    <div className="rate">
                      <i
                        style={{
                          width:
                            (100 * (row.identified || 0)) / Math.max(1, row.ms2) + "%"
                        }}
                      />
                    </div>
                  </button>
                ))}
              </div>
            </section>
          </Collapse>
          <main className="workspace">
            <div className="explorer">
              <AcquisitionMap
                source={source}
                fractions={fractions}
                map={map}
                spectrum={spectrum}
                target={mapTarget}
                onCell={chooseMapCell}
                rtRange={rtRange}
                cursor={cursor}
                onSource={selectSource}
                onScan={(ordinal) => openSpectrum(source, ordinal)}
                onZoom={changeTimeRange}
              />
              <PrecursorChromatogram
                base={base}
                source={source}
                fraction={active?.fraction}
                mode={active?.mode}
                annotations={annotations}
                fragmentPpm={Number(fragmentPpm)}
                fragmentSelection={fragmentSelection}
                layer={layer}
                map={map}
                spectrum={spectrum}
                candidate={candidate}
                mapTarget={mapTarget}
                rtRange={rtRange}
                cursor={cursor}
                onZoom={changeTimeRange}
                onPsm={choosePsm}
              />
            </div>
            <SpectrumInspector
              source={source}
              active={active}
              spectrum={spectrum}
              candidate={candidate}
              annotations={annotations}
              fragmentPpm={fragmentPpm}
              fragmentSelection={fragmentSelection}
              setFragmentPpm={setFragmentPpm}
              setCandidate={selectCandidate}
            />
          </main>
          <PsmTable
            key={`${state.token}:${sample}`}
            token={state.token}
            sample={sample}
            source={source}
            layer={layer}
            acquisitions={project.acquisitions}
            groupings={project.protein_groupings}
            selectedId={candidate?.id}
            onSelect={choosePsm}
          />
        </>
      ) : null}
      <footer>
        mzLoupe · Local acquisition inspection <span>mzML signal + idXML evidence</span>
      </footer>
    </div>
  );
}
