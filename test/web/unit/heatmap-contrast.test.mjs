import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const typescript = require("typescript");
const source = await readFile(
  new URL("../../../web/src/HeatmapContrast.ts", import.meta.url),
  "utf8"
);
const compiled = typescript.transpileModule(source, {
  compilerOptions: {
    module: typescript.ModuleKind.ESNext,
    target: typescript.ScriptTarget.ES2022
  }
}).outputText;
const { HeatmapContrast } = await import(
  "data:text/javascript;base64," + Buffer.from(compiled).toString("base64")
);

test("automatic contrast excludes empty bins and preserves original intensities", () => {
  const grid = [
    [0, 1, 2],
    [0, 3, 4, 5]
  ];
  const original = structuredClone(grid);
  const contrast = new HeatmapContrast(grid);
  const limits = contrast.automatic();
  assert.ok(Math.abs(limits.lower - 1.2) < 1e-12);
  assert.ok(Math.abs(limits.upper - 4.98) < 1e-12);
  assert.deepEqual(grid, original);
  const sparse = new HeatmapContrast([[...Array(1000).fill(0), 1, 2, 3, 4, 5]]);
  assert.deepEqual(sparse.automatic(), limits);
});

test("isolated bright outliers do not consume the automatic color range", () => {
  const values = Array.from({ length: 1000 }, (_, index) => 6 + index / 1000);
  const contrast = new HeatmapContrast([[...values, 20]]);
  assert.ok(contrast.automatic().lower > 6);
  assert.ok(contrast.automatic().upper < 7);
  assert.deepEqual(contrast.fullRange(), { lower: 0, upper: 20 });
});

test("full range reaches the actual maximum without rounding upward", () => {
  const contrast = new HeatmapContrast([[0, 2, 9.2]]);
  assert.deepEqual(contrast.limits({ mode: "full" }), { lower: 0, upper: 9.2 });
  assert.deepEqual(contrast.limits({ mode: "auto" }), contrast.automatic());
});

test("empty and constant maps always have a valid color range", () => {
  assert.deepEqual(new HeatmapContrast([]).automatic(), { lower: 0, upper: 1 });
  assert.deepEqual(new HeatmapContrast([[0, 0]]).automatic(), { lower: 0, upper: 1 });
  assert.deepEqual(new HeatmapContrast([[0, 4.5, 4.5]]).automatic(), {
    lower: 0,
    upper: 4.5
  });
  assert.deepEqual(new HeatmapContrast([[NaN, Infinity, -1, 0, 2]]).automatic(), {
    lower: 0,
    upper: 2
  });
});

test("custom limits stay fixed across acquisitions and reject invalid edits", () => {
  const limits = HeatmapContrast.custom(6.8, 8.8);
  assert.deepEqual(limits, { lower: 6.8, upper: 8.8 });
  const settings = { mode: "custom", limits };
  assert.deepEqual(new HeatmapContrast([[1, 2, 3]]).limits(settings), limits);
  assert.deepEqual(new HeatmapContrast([[7, 8, 9]]).limits(settings), limits);
  for (const [lower, upper] of [
    ["", 8],
    [6, ""],
    [8, 8],
    [9, 8],
    [-1, 8],
    [NaN, 8],
    [0, Infinity]
  ]) {
    assert.equal(HeatmapContrast.custom(lower, upper), undefined);
  }
});
