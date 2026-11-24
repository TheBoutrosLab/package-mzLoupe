import type {
  AcquisitionInput,
  ProjectConfiguration,
  ProteinGroupingInput,
  GroupCollection
} from "./api";

/** An editable idXML association with an ID used to track its row in the UI. */
export interface IdentificationRow {
  id: string;
  sample: string;
  name: string;
  path: string;
}

/** An inference input can be staged before the user chooses its collection. */
export interface ProteinGroupingRow extends Omit<ProteinGroupingInput, "collection"> {
  id: string;
  collection: GroupCollection | "";
}

/**
 * A field-level validation message attached to a row ID or the project itself.
 */
export interface RowIssue {
  id: string;
  field: string;
  message: string;
}

/**
 * Hold staged file associations; each edit returns a new draft before
 * activation.
 */
export class ProjectDraft {
  /** Keep sample-level source associations in an immutable draft. */
  constructor(
    public readonly name = "Untitled project",
    public readonly acquisitions: AcquisitionInput[] = [],
    public readonly identifications: IdentificationRow[] = [],
    public readonly groupings: ProteinGroupingRow[] = []
  ) {}

  /** Convert sample-level identification and grouping inputs into editable rows. */
  static fromConfiguration(configuration: ProjectConfiguration): ProjectDraft {
    const identifications: IdentificationRow[] = [];
    for (const sample of configuration.samples) {
      for (const layer of sample.identifications) {
        identifications.push({
          id: crypto.randomUUID(),
          sample: sample.name,
          ...layer
        });
      }
    }

    return new ProjectDraft(
      configuration.name,
      configuration.acquisitions,
      identifications,
      (configuration.protein_groupings || []).map((row) => ({
        ...row,
        id: crypto.randomUUID()
      }))
    );
  }

  /**
   * List samples from both source tables so orphaned identification rows stay
   * visible.
   */
  sampleNames(): string[] {
    return [
      ...new Set(
        [...this.acquisitions, ...this.identifications]
          .map((row) => row.sample)
          .filter(Boolean)
      )
    ].sort();
  }

  /** Rename the project while preserving its source associations. */
  withName(name: string): ProjectDraft {
    return new ProjectDraft(
      name,
      this.acquisitions,
      this.identifications,
      this.groupings
    );
  }

  /** Update one acquisition field without mutating the current draft. */
  withAcquisition(
    id: string,
    field: "sample" | "fraction" | "mzml",
    value: string
  ): ProjectDraft {
    const rows = this.acquisitions.map((row) =>
      row.id === id
        ? {
            ...row,
            [field]: value
          }
        : row
    );
    return new ProjectDraft(this.name, rows, this.identifications, this.groupings);
  }

  /** Update one sample-level identification association by its editor row ID. */
  withIdentification(
    id: string,
    field: "sample" | "name" | "path",
    value: string
  ): ProjectDraft {
    const rows = this.identifications.map((row) =>
      row.id === id
        ? {
            ...row,
            [field]: value
          }
        : row
    );
    return new ProjectDraft(this.name, this.acquisitions, rows, this.groupings);
  }

  /**
   * Add one acquisition per path, assigning an unused fraction label within the
   * sample.
   */
  addAcquisitions(paths: string[], sample: string): ProjectDraft {
    const rows = [...this.acquisitions];
    for (const path of paths) {
      // Search the growing list so files added in the same batch get distinct
      // labels.
      let number = 1;
      while (
        rows.some(
          (row) =>
            row.sample === sample &&
            row.fraction === "F" + String(number).padStart(2, "0")
        )
      ) {
        number++;
      }
      rows.push({
        id: "acq_" + crypto.randomUUID(),
        sample,
        fraction: "F" + String(number).padStart(2, "0"),
        mzml: path
      });
    }
    return new ProjectDraft(this.name, rows, this.identifications, this.groupings);
  }

  /** Associate selected idXML paths with the chosen sample and layer. */
  addIdentifications(paths: string[], sample: string, layer: string): ProjectDraft {
    const rows = paths.map((path) => ({
      id: crypto.randomUUID(),
      sample,
      name: layer,
      path
    }));
    return new ProjectDraft(
      this.name,
      this.acquisitions,
      [...this.identifications, ...rows],
      this.groupings
    );
  }

  /** Remove one acquisition while retaining independent identification inputs. */
  removeAcquisition(id: string): ProjectDraft {
    return new ProjectDraft(
      this.name,
      this.acquisitions.filter((row) => row.id !== id),
      this.identifications,
      this.groupings
    );
  }

  /** Remove one identification association without changing acquisition rows. */
  removeIdentification(id: string): ProjectDraft {
    return new ProjectDraft(
      this.name,
      this.acquisitions,
      this.identifications.filter((row) => row.id !== id),
      this.groupings
    );
  }

  /** Add an inference source independently of acquisition and PSM input rows. */
  addGrouping(): ProjectDraft {
    let number = 1;
    while (this.groupings.some((row) => row.name === `Grouping ${number}`)) number++;
    return new ProjectDraft(this.name, this.acquisitions, this.identifications, [
      ...this.groupings,
      {
        id: crypto.randomUUID(),
        name: `Grouping ${number}`,
        path: "",
        collection: "",
        samples: [],
        layers: []
      }
    ]);
  }

  /** A new file requires a fresh collection choice after its contents are inspected. */
  withGrouping(id: string, changes: Partial<ProteinGroupingRow>): ProjectDraft {
    const rows = this.groupings.map((row) => {
      if (row.id !== id) return row;
      const changedFile = changes.path !== undefined && changes.path !== row.path;
      return {
        ...row,
        collection: changedFile ? ("" as const) : row.collection,
        ...changes
      };
    });
    return new ProjectDraft(this.name, this.acquisitions, this.identifications, rows);
  }

  /** Remove an inference view without changing any PSM or acquisition inputs. */
  removeGrouping(id: string): ProjectDraft {
    return new ProjectDraft(
      this.name,
      this.acquisitions,
      this.identifications,
      this.groupings.filter((row) => row.id !== id)
    );
  }

  /** List available layers within a grouping's selected samples. */
  groupingLayers(samples: string[]): string[] {
    return [
      ...new Set(
        this.identifications
          .filter((row) => !samples.length || samples.includes(row.sample))
          .map((row) => row.name)
          .filter(Boolean)
      )
    ].sort();
  }

  /**
   * Check row associations locally; the server separately checks file
   * existence.
   */
  issues(): RowIssue[] {
    const issues: RowIssue[] = [];
    if (!this.name.trim()) {
      issues.push({
        id: "project",
        field: "name",
        message: "Enter a project name"
      });
    }
    if (!this.acquisitions.length) {
      issues.push({
        id: "project",
        field: "acquisitions",
        message: "Add at least one mzML acquisition"
      });
    }

    // Required acquisition fields and sample/fraction uniqueness.
    for (const row of this.acquisitions) {
      for (const field of ["sample", "fraction", "mzml"] as const) {
        if (!row[field].trim()) {
          issues.push({
            id: row.id,
            field,
            message: "Required"
          });
        }
      }
      if (
        this.acquisitions.some(
          (other) =>
            other.id !== row.id &&
            other.sample.trim() === row.sample.trim() &&
            other.fraction.trim() === row.fraction.trim()
        )
      ) {
        issues.push({
          id: row.id,
          field: "fraction",
          message: "This sample/fraction pair occurs twice"
        });
      }
    }

    // Required identification fields and membership in a registered sample.
    for (const row of this.identifications) {
      for (const field of ["sample", "name", "path"] as const) {
        if (!row[field].trim()) {
          issues.push({
            id: row.id,
            field,
            message: "Required"
          });
        }
      }
      if (
        !this.acquisitions.some(
          (acquisition) => acquisition.sample.trim() === row.sample.trim()
        )
      ) {
        issues.push({
          id: row.id,
          field: "sample",
          message: "This sample needs an acquisition"
        });
      }
      // A named layer belongs to one identification file per sample.
      const duplicate = this.identifications.some(
        (other) =>
          other.id !== row.id &&
          other.sample.trim() === row.sample.trim() &&
          other.name.trim() === row.name.trim()
      );
      if (duplicate) {
        issues.push({
          id: row.id,
          field: "name",
          message: "Choose a unique layer for this sample"
        });
      }
    }
    for (const row of this.groupings) {
      for (const field of ["name", "path", "collection"] as const) {
        if (!row[field].trim()) issues.push({ id: row.id, field, message: "Required" });
      }
      if (
        this.groupings.some(
          (other) => other.id !== row.id && other.name.trim() === row.name.trim()
        )
      ) {
        issues.push({
          id: row.id,
          field: "name",
          message: "Choose a unique grouping name"
        });
      }
      if (
        row.samples.some(
          (name) => !this.acquisitions.some((item) => item.sample === name)
        )
      ) {
        issues.push({
          id: row.id,
          field: "samples",
          message: "Choose registered samples"
        });
      }
      const layers = this.groupingLayers(row.samples);
      if (row.layers.some((name) => !layers.includes(name))) {
        issues.push({
          id: row.id,
          field: "layers",
          message: "Choose layers in the selected samples"
        });
      }
    }
    return issues;
  }

  /** Serialize sample-level sources for activation or JSON export. */
  toConfiguration(): ProjectConfiguration {
    // Trim at the serialization boundary so editing does not rewrite the
    // visible input.
    const acquisitions = this.acquisitions.map((row) => ({
      ...row,
      sample: row.sample.trim(),
      fraction: row.fraction.trim(),
      mzml: row.mzml.trim()
    }));
    // Store each identification file once under its sample.
    const samples = this.sampleNames()
      .map((name) => name.trim())
      .filter((name, index, names) => names.indexOf(name) === index)
      .map((name) => ({
        name,
        identifications: this.identifications
          .filter((row) => row.sample.trim() === name)
          .map((row) => ({
            name: row.name.trim(),
            path: row.path.trim()
          }))
      }))
      .filter((row) => row.identifications.length > 0);
    return {
      name: this.name.trim(),
      protein_groupings: this.groupings.map(({ id, ...row }) => ({
        ...row,
        name: row.name.trim(),
        path: row.path.trim(),
        collection: row.collection as GroupCollection
      })),
      acquisitions,
      samples
    };
  }
}
