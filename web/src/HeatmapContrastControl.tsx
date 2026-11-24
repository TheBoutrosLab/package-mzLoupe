import { useState } from "react";
import { Button, Group, NumberInput, Popover, Select, Stack, Text } from "@mantine/core";
import { HeatmapContrast } from "./HeatmapContrast";
import type { ColorLimits, ContrastSettings } from "./HeatmapContrast";

interface Props {
  settings: ContrastSettings;
  limits: ColorLimits;
  onChange: (settings: ContrastSettings) => void;
}

/** Edit color limits separately from spectrum selection, zoom, and signal values. */
export function HeatmapContrastControl({ settings, limits, onChange }: Props) {
  const [lower, setLower] = useState<number | string>(limits.lower);
  const [upper, setUpper] = useState<number | string>(limits.upper);
  const modeLabel =
    settings.mode === "full" ? "Full" : settings.mode === "custom" ? "Custom" : "Auto";
  const invalid = settings.mode === "custom" && !HeatmapContrast.custom(lower, upper);

  /** Start manual editing from the currently displayed range. */
  function chooseMode(value: string | null) {
    if (value === "custom") {
      setLower(limits.lower);
      setUpper(limits.upper);
      onChange({ mode: "custom", limits });
    } else {
      onChange({ mode: value === "full" ? "full" : "auto" });
    }
  }

  /** Preserve the last valid scale while a user is typing incomplete or reversed limits. */
  function changeLimits(nextLower: number | string, nextUpper: number | string) {
    setLower(nextLower);
    setUpper(nextUpper);
    const nextLimits = HeatmapContrast.custom(nextLower, nextUpper);
    if (nextLimits) {
      onChange({ mode: "custom", limits: nextLimits });
    }
  }

  return (
    <Popover
      width={320}
      position="bottom-end"
      withArrow
      withinPortal
    >
      <Popover.Target>
        <Button
          variant="subtle"
          size="xs"
          aria-label="Adjust heatmap contrast"
        >
          Contrast: {modeLabel}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="sm">
          <Select
            label="Color contrast"
            value={settings.mode}
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
            onChange={chooseMode}
            data={[
              { value: "auto", label: "Auto (5th–99.5th percentile)" },
              { value: "full", label: "Full range" },
              { value: "custom", label: "Custom limits" }
            ]}
          />
          {settings.mode === "custom" && (
            <>
              <Group
                grow
                align="start"
                wrap="nowrap"
              >
                <NumberInput
                  label="Lower color limit"
                  value={lower}
                  onChange={(value) => changeLimits(value, upper)}
                  min={0}
                  step={0.1}
                  decimalScale={3}
                />
                <NumberInput
                  label="Upper color limit"
                  value={upper}
                  onChange={(value) => changeLimits(lower, value)}
                  min={0}
                  step={0.1}
                  decimalScale={3}
                />
              </Group>
              {invalid && (
                <Text
                  size="xs"
                  c="red"
                  role="alert"
                >
                  Enter a nonnegative lower limit smaller than the upper limit.
                </Text>
              )}
            </>
          )}
          <Text size="xs">
            Color limits · log₁₀(1 + I): {limits.lower.toFixed(3)}–
            {limits.upper.toFixed(3)}
          </Text>
          <Text
            size="xs"
            c="dimmed"
          >
            {settings.mode === "auto"
              ? "Auto uses nonzero bins across this acquisition."
              : settings.mode === "full"
                ? "Full range uses zero through the highest bin intensity."
                : "Custom limits stay fixed when switching fractions."}{" "}
            Colors outside the limits use dark blue or pale yellow. Hover values remain
            unchanged.
          </Text>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
