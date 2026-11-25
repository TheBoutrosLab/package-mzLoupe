import { Alert, Button, Group, SegmentedControl } from "@mantine/core";
import type { AcquisitionMode } from "./api";
import { useFragmentChromatograms } from "./useFragmentChromatograms";

interface Props {
  mode?: AcquisitionMode;
  fragments: ReturnType<typeof useFragmentChromatograms>;
}

/** Keep fragment extraction opt-in and show the identity of every overlaid ion. */
export function FragmentXicControls({ mode, fragments }: Props) {
  const { available, enabled, result, loading, error, relative } = fragments;
  return (
    <div className="extraction fragment-controls">
      <Group>
        <Button
          variant="light"
          disabled={!available && !enabled}
          onClick={fragments.toggle}
        >
          {enabled ? "Hide fragment XICs" : "Show fragment XICs"}
        </Button>
        {enabled && (
          <SegmentedControl
            aria-label="Chromatogram intensity scale"
            value={relative ? "relative" : "raw"}
            onChange={(value) => fragments.setRelative(value === "relative")}
            data={[
              { value: "raw", label: "Raw intensity" },
              { value: "relative", label: "Relative intensity" }
            ]}
          />
        )}
      </Group>
      {!available && !enabled && (
        <p className="caption">
          {mode !== "DIA"
            ? "Fragment XICs require DIA mode in project setup."
            : "Select a resolved PSM with matched b/y ions and extract its precursor XIC."}
        </p>
      )}
      {loading && <p className="caption">Extracting matched fragment chromatograms…</p>}
      {enabled && error && <Alert color="red">{error}</Alert>}
      {result && (
        <p className="caption">
          {result.fragments.length} matched b/y ions · ±{result.ppm} ppm · isolation{" "}
          {result.isolation_lower_mz.toFixed(4)}–{result.isolation_upper_mz.toFixed(4)}{" "}
          m/z
          {result.scan_count === 0 && " · No eligible MS2 scans in this interval."}
        </p>
      )}
    </div>
  );
}
