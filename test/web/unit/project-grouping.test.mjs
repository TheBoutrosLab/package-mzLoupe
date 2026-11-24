import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const ts = require("typescript");
const source = await readFile(
  new URL("../../../web/src/ProjectDraft.ts", import.meta.url),
  "utf8"
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
}).outputText;
const { ProjectDraft } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);

test("grouping edits preserve sample-level identification associations", () => {
  const configuration = {
    name: "Current project",
    samples: [
      {
        name: "Sample 1",
        identifications: [{ name: "Search", path: "/data/search.idXML" }]
      }
    ],
    acquisitions: [
      {
        id: "f01",
        sample: "Sample 1",
        fraction: "F01",
        mzml: "/data/run.mzML"
      }
    ]
  };
  let draft = ProjectDraft.fromConfiguration(configuration).addGrouping();
  const id = draft.groupings[0].id;
  draft = draft.withGrouping(id, {
    path: "/data/groups.idXML",
    collection: "protein_groups"
  });
  const result = draft.toConfiguration();
  assert.deepEqual(result.samples, configuration.samples);
  assert.deepEqual(result.acquisitions, configuration.acquisitions);
  assert.equal(result.protein_groupings[0].collection, "protein_groups");
  draft = draft.withAcquisition("f01", "fraction", "F02");
  assert.equal(draft.groupings.length, 1);
  assert.deepEqual(
    draft.removeGrouping(id).toConfiguration().samples,
    configuration.samples
  );
});

test("editing a grouping path clears the old collection choice", () => {
  let draft = new ProjectDraft().addGrouping();
  const id = draft.groupings[0].id;
  draft = draft.withGrouping(id, { path: "/one.idXML", collection: "protein_groups" });
  assert.equal(
    draft.withGrouping(id, { path: "/two.idXML" }).groupings[0].collection,
    ""
  );
  assert.equal(
    draft.withGrouping(id, { name: "Renamed" }).groupings[0].collection,
    "protein_groups"
  );
});
