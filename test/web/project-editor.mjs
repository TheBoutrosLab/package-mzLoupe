import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
const demoDirectory = fileURLToPath(new URL("../../demo-data/", import.meta.url));
const artifacts = await mkdtemp(join(tmpdir(), "mzloupe-editor-"));
const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:8765");
await page.getByRole("heading", { name: "MS1 acquisition map" }).waitFor();
await page.getByRole("cell", { name: "scan=80", exact: true }).first().click();
await page.getByText("Assignments", { exact: true }).waitFor();
await page.getByRole("button", { name: "Project setup", exact: true }).click();
await expect(
  page.getByRole("heading", { name: "Project setup", exact: true })
).toBeVisible();
await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
  "Synthetic DDA demonstration"
);
await page.getByLabel("Project name", { exact: true }).fill("Edited local project");
await page.getByRole("button", { name: "Explore", exact: true }).click();
await expect(page.getByText("Assignments", { exact: true })).toBeVisible();
await expect(page.locator(".inspector")).toContainText("scan=80");
await page.getByRole("button", { name: "Project setup", exact: true }).click();
await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
  "Edited local project"
);

const fractions = page.getByRole("textbox", { name: /^Fraction for / });
await fractions.nth(1).fill("F01");
await expect(
  page.getByText("This sample/fraction pair occurs twice").first()
).toBeVisible();
await expect(
  page.getByRole("button", { name: "Apply changes", exact: true })
).toBeDisabled();
await fractions.nth(1).fill("F02");

const paths = page.getByRole("textbox", { name: /^mzML path for / });
const original = await paths.first().inputValue();
await paths.first().fill("/missing/acquisition.mzML");
await expect(
  page.getByText("File does not exist: /missing/acquisition.mzML")
).toBeVisible();
await paths.first().fill(original);
await expect(
  page.getByRole("button", { name: "Apply changes", exact: true })
).toBeEnabled();

await page.getByRole("button", { name: "Add mzML files", exact: true }).click();
await page.getByLabel("Directory", { exact: true }).fill(demoDirectory);
await page.getByRole("button", { name: "Go", exact: true }).click();
await page.getByRole("checkbox", { name: "fraction_01.mzML", exact: true }).check();
await page.getByRole("button", { name: "Use selected files", exact: true }).click();
await expect(paths).toHaveCount(3);
await page.getByRole("button", { name: "Remove acquisition F03", exact: true }).click();
await expect(paths).toHaveCount(2);

await page.getByRole("button", { name: "Add acquisition row", exact: true }).click();
await page.locator('input[aria-label^="Sample for "]').last().fill("Comparison sample");
await paths.last().fill(original);
await page.getByRole("textbox", { name: "Show sample", exact: true }).click();
await page.getByRole("option", { name: "Comparison sample", exact: true }).click();
await expect(paths).toHaveCount(1);
await expect(
  page.getByText(
    "Optionally associate a sample-level idXML with an identification layer."
  )
).toBeVisible();
await page.getByRole("textbox", { name: "Show sample", exact: true }).click();
await page.getByRole("option", { name: "All samples", exact: true }).click();
await expect(paths).toHaveCount(3);
await page.getByRole("button", { name: "Remove acquisition F03", exact: true }).click();
await expect(paths).toHaveCount(2);

await page.getByRole("button", { name: "Add idXML files", exact: true }).click();
await page.getByLabel("Assign layer", { exact: true }).fill("Alternative");
await page.getByLabel("Directory", { exact: true }).fill(demoDirectory);
await page.getByRole("button", { name: "Go", exact: true }).click();
await page.getByRole("checkbox", { name: "sample_Validated.idXML", exact: true }).check();
await page.getByRole("button", { name: "Use selected files", exact: true }).click();
await expect(page.getByRole("textbox", { name: /^idXML path for / })).toHaveCount(3);
await page
  .getByRole("button", { name: "Remove identification Alternative", exact: true })
  .click();
await expect(page.getByRole("textbox", { name: /^idXML path for / })).toHaveCount(2);

await page.getByRole("button", { name: "Save JSON", exact: true }).click();
await page.getByLabel("Directory", { exact: true }).fill(demoDirectory);
await page
  .getByLabel("File name", { exact: true })
  .fill(`project-editor-${Date.now()}.json`);
const savedResponse = page.waitForResponse((response) =>
  response.url().endsWith("/api/save-project")
);
await page.getByRole("button", { name: "Save", exact: true }).click();
const saved = await (await savedResponse).json();
await expect(page.getByText("Saved: " + saved.path, { exact: true })).toBeVisible();
const imported = await page.request.post("http://127.0.0.1:8765/api/import-project", {
  data: { path: saved.path }
});
assert.equal(imported.status(), 200);
const exported = await imported.json();
assert.equal(exported.name, "Edited local project");
assert.equal(exported.acquisitions.length, 2);
assert.equal(exported.samples[0].identifications.length, 2);

await page.screenshot({ path: join(artifacts, "setup.png"), fullPage: true });
await page.getByRole("button", { name: "Apply changes", exact: true }).click();
await page.getByRole("heading", { name: "MS1 acquisition map" }).waitFor();
await page.getByRole("button", { name: "Project setup", exact: true }).click();
await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
  "Edited local project"
);
await page.getByRole("button", { name: "Import JSON", exact: true }).click();
await page
  .getByLabel("Project JSON path", { exact: true })
  .fill(join(demoDirectory, "project.json"));
await page.getByRole("button", { name: "Import into tables", exact: true }).click();
await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
  "Synthetic DDA demonstration"
);
await page.getByRole("button", { name: "Apply changes", exact: true }).click();
await page.getByRole("heading", { name: "MS1 acquisition map" }).waitFor();
assert.deepEqual(errors, []);
console.log(JSON.stringify({ pageErrors: errors, editor: "passed", artifacts }));
await browser.close();
