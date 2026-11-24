import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const ts = require("typescript");
const source = await readFile(
  new URL("../../web/src/ExplorerState.ts", import.meta.url),
  "utf8"
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
}).outputText;
const { ExplorerModel } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);
const reduce = ExplorerModel.reduce;
const project = {
  name: "Evidence",
  protein_groupings: [],
  acquisitions: [
    {
      id: "f1",
      sample: "A",
      fraction: "F01",
      layers: ["Validated"],
      ms2: 3,
      identified: 1
    },
    {
      id: "f2",
      sample: "A",
      fraction: "F02",
      layers: ["Validated"],
      ms2: 3,
      identified: 1
    },
    { id: "f3", sample: "B", fraction: "F01", layers: ["Search"], ms2: 3, identified: 1 }
  ]
};
const candidate = { id: 1, source: "f1", ordinal: 7, layer: "Validated", resolved: 1 };
const second = { ...candidate, id: 2 };
const spectrum = { source: "f1", ordinal: 7, rt: 120, candidates: [candidate, second] };
const map = { intensity: [[1]], bounds: [0, 600, 100, 1000], events: [] };

/** Start with one project and a fully selected scan in its first fraction. */
function inspected() {
  let state = reduce(ExplorerModel.initial(), {
    type: "projectOpened",
    token: "project"
  });
  state = reduce(state, {
    type: "projectLoaded",
    token: "project",
    layer: "Validated",
    project,
    preferredSource: null
  });
  state = reduce(state, { type: "mapLoaded", token: "project", source: "f1", map });
  state = reduce(state, {
    type: "spectrumRequested",
    source: "f1",
    ordinal: 7,
    psmId: 1
  });
  return reduce(state, {
    type: "spectrumLoaded",
    token: "project",
    revision: state.revision,
    spectrum
  });
}

test("a cross-fraction PSM switches source and clears previous evidence atomically", () => {
  const previous = { ...inspected(), annotations: [{ label: "y1" }], rtRange: [1, 3] };
  const state = reduce(previous, {
    type: "spectrumRequested",
    source: "f2",
    ordinal: 7,
    psmId: 9
  });
  assert.equal(state.source, "f2");
  assert.equal(state.sample, "A");
  assert.equal(state.selection.psmId, 9);
  assert.equal(state.map, undefined);
  assert.equal(state.spectrum, undefined);
  assert.equal(state.candidate, undefined);
  assert.equal(state.mapTarget, undefined);
  assert.equal(state.rtRange, undefined);
  assert.deepEqual(state.annotations, []);
  assert.equal(previous.spectrum, spectrum);
  assert.equal(previous.map, map);
});

test("late spectrum and map responses cannot overwrite another fraction or project", () => {
  const previous = inspected();
  const state = reduce(previous, { type: "sourceSelected", source: "f2" });
  assert.equal(
    reduce(state, {
      type: "spectrumLoaded",
      token: "project",
      revision: previous.revision,
      spectrum
    }),
    state
  );
  assert.equal(
    reduce(state, { type: "mapLoaded", token: "project", source: "f1", map }),
    state
  );
  const reopened = reduce(previous, { type: "projectOpened", token: "other" });
  assert.equal(
    reduce(reopened, {
      type: "spectrumLoaded",
      token: "project",
      revision: previous.revision,
      spectrum
    }),
    reopened
  );
});

test("a newer selection wins even when the previous response has the same scan ID", () => {
  const previous = inspected();
  const requested = reduce(previous, {
    type: "spectrumRequested",
    source: "f1",
    ordinal: 7,
    psmId: 2
  });
  assert.equal(
    reduce(requested, {
      type: "spectrumLoaded",
      token: "project",
      revision: previous.revision,
      spectrum
    }),
    requested
  );
  const state = reduce(requested, {
    type: "spectrumLoaded",
    token: "project",
    revision: requested.revision,
    spectrum
  });
  assert.equal(state.candidate.id, 2);
});

test("candidate selection preserves measured data and clears only its annotations", () => {
  const previous = { ...inspected(), annotations: [{ label: "y1" }], rtRange: [1, 3] };
  const state = reduce(previous, { type: "candidateSelected", candidate: second });
  assert.equal(state.spectrum, previous.spectrum);
  assert.equal(state.map, previous.map);
  assert.equal(state.selection, previous.selection);
  assert.equal(state.rtRange, previous.rtRange);
  assert.equal(state.candidate, second);
  assert.deepEqual(state.annotations, []);
  assert.equal(
    reduce(state, {
      type: "annotationsLoaded",
      token: "project",
      candidateId: 1,
      annotations: [{ label: "wrong" }]
    }),
    state
  );
});

test("a map selection invalidates an in-flight spectrum and selects only MS1 evidence", () => {
  const previous = inspected();
  const cell = { source: "f1", start: 0, stop: 300, mz_start: 400, mz_stop: 401 };
  const requested = reduce(previous, { type: "mapTargetRequested", cell });
  assert.equal(
    reduce(requested, {
      type: "spectrumLoaded",
      token: "project",
      revision: previous.revision,
      spectrum
    }),
    requested
  );
  const target = { source: "f1", mz: 400.6, rt: 130, ordinal: 8, intensity: 100 };
  const state = reduce(requested, {
    type: "mapTargetLoaded",
    token: "project",
    revision: requested.revision,
    target
  });
  assert.equal(state.mapTarget, target);
  assert.equal(state.spectrum, undefined);
  assert.equal(state.map, previous.map);
});

test("overview refresh preserves inspection and viewport resets only to reveal a scan", () => {
  let state = { ...inspected(), rtRange: [1, 3] };
  const refreshed = reduce(state, {
    type: "projectLoaded",
    token: "project",
    layer: "Validated",
    project,
    preferredSource: "f2"
  });
  assert.equal(refreshed.source, "f1");
  assert.equal(refreshed.spectrum, state.spectrum);
  assert.equal(refreshed.map, state.map);
  state = reduce(state, { type: "spectrumRequested", source: "f1", ordinal: 8 });
  state = reduce(state, {
    type: "spectrumLoaded",
    token: "project",
    revision: state.revision,
    spectrum: { ...spectrum, ordinal: 8, rt: 500 }
  });
  assert.equal(state.rtRange, undefined);
});

test("an initial linked source selects its sample and late overview responses are ignored", () => {
  const initial = reduce(ExplorerModel.initial(), {
    type: "projectOpened",
    token: "project"
  });
  const state = reduce(initial, {
    type: "projectLoaded",
    token: "project",
    layer: "Validated",
    project,
    preferredSource: "f3"
  });
  assert.equal(state.sample, "B");
  assert.equal(state.source, "f3");
  const changed = reduce(state, { type: "layerSelected", layer: "Search" });
  assert.equal(
    reduce(changed, {
      type: "projectLoaded",
      token: "project",
      layer: "Validated",
      project,
      preferredSource: null
    }),
    changed
  );
});
