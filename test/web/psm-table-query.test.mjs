import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const ts = require("typescript");
const source = await readFile(
  new URL("../../web/src/PsmTableQuery.ts", import.meta.url),
  "utf8"
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
}).outputText;
const { PsmTableQuery } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);

test("zero numeric bounds activate a column and independent drafts share no nested state", () => {
  const first = PsmTableQuery.filters();
  const second = PsmTableQuery.filters();
  first.score_max = 0;
  first.sequence.value = "PEPTIDE";
  first.layers.push("Search");
  assert.equal(PsmTableQuery.activeCount(first), 3);
  assert.equal(PsmTableQuery.activeCount(second), 0);
  assert.equal(second.sequence.value, "");
  assert.deepEqual(second.layers, []);
});

test("open ranges are valid and reversed RT or score ranges remain explicit errors", () => {
  const filters = PsmTableQuery.filters();
  filters.rt_min = 0;
  assert.equal(PsmTableQuery.error(filters), "");
  filters.rt_min = 5;
  filters.rt_max = 4;
  assert.equal(PsmTableQuery.error(filters), "RT minimum must not exceed maximum.");
  filters.rt_max = 5;
  filters.score_min = -1;
  filters.score_max = -2;
  assert.equal(PsmTableQuery.error(filters), "Score minimum must not exceed maximum.");
});

test("table queries serialize all conditions and convert page numbering once", () => {
  const state = PsmTableQuery.initial("Validated");
  state.page = 3;
  state.pageSize = 100;
  state.filters.proteins = { value: "P0CE47", mode: "exact" };
  const parameters = PsmTableQuery.parameters(
    state,
    "Sample 1",
    "fraction_02",
    "Subgroups"
  );
  assert.equal(parameters.get("page"), "2");
  assert.equal(parameters.get("page_size"), "100");
  assert.equal(parameters.get("source"), "fraction_02");
  assert.equal(parameters.get("grouping"), "Subgroups");
  assert.equal(parameters.has("layer"), false);
  assert.equal(parameters.has("search"), false);
  assert.deepEqual(JSON.parse(parameters.get("filters")).layers, ["Validated"]);
  assert.deepEqual(JSON.parse(parameters.get("filters")).proteins, {
    value: "P0CE47",
    mode: "exact"
  });
  state.scope = "sample";
  assert.equal(
    PsmTableQuery.parameters(state, "Sample 1", "fraction_02", "").has("source"),
    false
  );
});

test("precursor ranges preserve full-precision query values", () => {
  const state = PsmTableQuery.initial("Validated");
  state.filters.precursor_mz_min = 400.68;
  state.filters.precursor_mz_max = 400.7;
  const parameters = PsmTableQuery.parameters(state, "Sample", "run", "");
  const filters = JSON.parse(parameters.get("filters"));
  assert.equal(filters.precursor_mz_min, 400.68);
  assert.equal(PsmTableQuery.activeCount(state.filters), 2);
  state.filters.precursor_mz_max = 399;
  assert.equal(
    PsmTableQuery.error(state.filters),
    "Precursor m/z minimum must not exceed maximum."
  );
});
