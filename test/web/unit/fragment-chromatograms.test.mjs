import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const typescript = require("typescript");

/** Load the pure fragment models without a browser or frontend build. */
async function compile(name, dependencies = {}) {
  const source = await readFile(
    new URL(`../../../web/src/${name}.ts`, import.meta.url),
    "utf8"
  );
  let compiled = typescript.transpileModule(source, {
    compilerOptions: {
      module: typescript.ModuleKind.ESNext,
      target: typescript.ScriptTarget.ES2022
    }
  }).outputText;
  for (const [specifier, url] of Object.entries(dependencies)) {
    compiled = compiled.replaceAll(`"${specifier}"`, JSON.stringify(url));
  }
  return "data:text/javascript;base64," + Buffer.from(compiled).toString("base64");
}
const ionsModule = await compile("FragmentIons");
const { FragmentIons } = await import(ionsModule);
const { FragmentChromatograms } = await import(
  await compile("FragmentChromatograms", {
    "./FragmentIons": ionsModule
  })
);

test("relative scaling preserves raw values and handles absent signal", () => {
  const values = [0, 50, 200];
  assert.deepEqual(FragmentChromatograms.intensities(values, true), [0, 25, 100]);
  assert.deepEqual(values, [0, 50, 200]);
  assert.equal(FragmentChromatograms.intensities(values, false), values);
  assert.deepEqual(FragmentChromatograms.intensities([0, 0], true), [0, 0]);
  assert.deepEqual(FragmentChromatograms.intensities([], true), []);
});

test("visibility and focus preserve measured RT points and stable ion colors", () => {
  const trace = {
    rt: [60, 84],
    fragments: [
      { label: "b2+", mz: 200, charge: 1, intensity: [2, 4] },
      { label: "y3+", mz: 400, charge: 1, intensity: [1, 10] }
    ]
  };
  const selected = new Set(trace.fragments.map((ion) => FragmentIons.id(ion)));
  const id = FragmentIons.id(trace.fragments[1]);
  const lines = FragmentChromatograms.plot(trace, selected, false, id);
  assert.deepEqual(lines[1].x, [1, 1.4]);
  assert.deepEqual(lines[1].y, [1, 10]);
  assert.equal(lines[1].line.color, FragmentIons.color(trace.fragments[1]));
  assert.equal(lines[1].line.width, 3);
  assert.equal(lines[0].opacity, 0.2);
  selected.delete(FragmentIons.id(trace.fragments[0]));
  const only = FragmentChromatograms.plot(
    { ...trace, fragments: [...trace.fragments].reverse() },
    selected,
    false
  );
  assert.equal(only.length, 1);
  assert.equal(only[0].line.color, lines[1].line.color);
});

test("fragment colors do not repeat after ten ions or change when sorted", () => {
  const ions = Array.from({ length: 40 }, (_, index) => ({
    label: `y${index + 1}+`,
    mz: 100 + index,
    charge: 1
  }));
  const colors = ions.map((ion) => FragmentIons.color(ion));
  assert.equal(new Set(colors).size, ions.length);
  assert.equal(FragmentIons.color(ions[0]), colors[0]);
  assert.notEqual(colors[0], colors[10]);
});

test("table rows retain signed mass errors, raw spectrum intensity, and ambiguous assignments", () => {
  const annotations = [
    { label: "b2+", mz: 200, charge: 1, ppm: -2.5, index: 0 },
    { label: "y3+", mz: 200.001, charge: 1, ppm: 2.5, index: 0 },
    { label: "y4+", mz: 400, charge: 1, ppm: 1.5, index: 1 }
  ];
  const rows = FragmentIons.rows({ intensities: [1200, 300] }, annotations);
  assert.deepEqual(
    rows.map((ion) => ion.intensity),
    [1200, 1200, 300]
  );
  assert.deepEqual(
    rows.map((ion) => ion.ppm),
    [-2.5, 2.5, 1.5]
  );
  assert.deepEqual(
    rows.map((ion) => ion.peakAssignments),
    [2, 2, 1]
  );
  assert.equal(new Set(rows.map((ion) => ion.id)).size, 3);
  assert.deepEqual(FragmentIons.rows(undefined, annotations), []);
});

test("Top 6 ranks by spectrum intensity without mutating rows or identities", () => {
  const rows = Array.from({ length: 8 }, (_, index) => ({
    id: String(index),
    label: `y${index + 1}+`,
    intensity: index * 100,
    mz: 100 + index,
    charge: 1,
    ppm: 0,
    index,
    peakAssignments: 1
  }));
  const original = structuredClone(rows);
  assert.deepEqual([...FragmentIons.top(rows)], ["7", "6", "5", "4", "3", "2"]);
  assert.deepEqual(rows, original);
  const selected = FragmentIons.top(rows);
  const ascending = FragmentIons.sort(rows, "mz", "asc");
  assert.deepEqual(
    ascending.filter((ion) => selected.has(ion.id)).map((ion) => ion.id),
    ["2", "3", "4", "5", "6", "7"]
  );
});
