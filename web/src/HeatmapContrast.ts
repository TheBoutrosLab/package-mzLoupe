/** Color endpoints expressed in the map's existing log10(1 + intensity) units. */
export interface ColorLimits {
  lower: number;
  upper: number;
}

/** Automatic limits follow the acquisition; custom limits can be shared across fractions. */
export type ContrastSettings =
  { mode: "auto" } | { mode: "full" } | { mode: "custom"; limits: ColorLimits };

/** Calculate display contrast without modifying measured or binned intensity values. */
export class HeatmapContrast {
  static readonly lowerPercentile = 5;
  static readonly upperPercentile = 99.5;

  readonly positive: number[];

  /** Collect finite positive map intensities once for percentile calculations. */
  constructor(intensity: number[][]) {
    // Zero bins represent empty signal. Exclude them from percentile statistics
    // so sparse maps get the same useful contrast as dense maps.
    this.positive = intensity
      .flat()
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((first, second) => first - second);
  }

  /** Interpolate a percentile in sorted, nonzero bin values. */
  percentile(percent: number): number {
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
      throw new RangeError("Percentiles must be between 0 and 100");
    }
    if (!this.positive.length) {
      return 0;
    }
    const position = (percent / 100) * (this.positive.length - 1);
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    return (
      this.positive[lower] +
      (this.positive[upper] - this.positive[lower]) * (position - lower)
    );
  }

  /** Use the true maximum, avoiding the unused palette range from rounded limits. */
  fullRange(): ColorLimits {
    const maximum = this.positive[this.positive.length - 1] || 1;
    return { lower: 0, upper: maximum };
  }

  /** Spread meaningful signal over the palette; keep empty and flat maps well-defined. */
  automatic(): ColorLimits {
    const lower = this.percentile(HeatmapContrast.lowerPercentile);
    const upper = this.percentile(HeatmapContrast.upperPercentile);
    return upper > lower ? { lower, upper } : this.fullRange();
  }

  /** Choose acquisition-wide display limits independently of the current zoom. */
  limits(settings: ContrastSettings): ColorLimits {
    if (settings.mode === "custom") {
      return settings.limits;
    }
    return settings.mode === "full" ? this.fullRange() : this.automatic();
  }

  /** Accept complete manual values while allowing inputs to be empty during editing. */
  static custom(lower: number | string, upper: number | string): ColorLimits | undefined {
    if (
      typeof lower !== "number" ||
      typeof upper !== "number" ||
      !Number.isFinite(lower) ||
      !Number.isFinite(upper) ||
      lower < 0 ||
      upper <= lower
    ) {
      return undefined;
    }
    return { lower, upper };
  }
}
