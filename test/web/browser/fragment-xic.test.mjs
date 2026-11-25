import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { ApiSession } from "../fixtures/ApiSession.mjs";
import { BrowserArtifacts } from "../browser-artifacts.mjs";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");

test("DIA fragments overlay the MS1 trace on demand and discard stale responses", async () => {
  const api = new ApiSession("fragment_browser_api.py");
  let browser;
  let release;
  let resolveDelayed;
  try {
    await api.ready;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1800, height: 1200 } });
    const errors = [];
    const batches = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await api.route(page);
    // Delay one real API response to exercise superseded selections.
    await page.route("**/fragment-xic", async (route) => {
      const request = route.request().postDataJSON();
      batches.push(request);
      const response = await api.request({
        method: "POST",
        url: new URL(route.request().url()).pathname,
        body: request
      });
      if (release) {
        const pending = release;
        release = undefined;
        await pending;
      }
      await route.fulfill({ status: response.status, json: response.body });
    });
    await page.goto("https://mzloupe.test");
    await page.getByRole("cell", { name: "scan=80", exact: true }).first().click();
    const panel = page.locator(".chromatogram-panel");
    const plot = panel.locator(".plot");
    const show = panel.getByRole("button", { name: "Show fragment XICs", exact: true });
    await expect(show).toBeEnabled();
    const ionTable = page.getByRole("region", { name: "Fragment ions", exact: true });
    await expect(ionTable.getByRole("checkbox", { checked: true })).toHaveCount(6);
    assert.deepEqual(await ionTable.locator("thead th").allTextContents(), [
      "XIC",
      "Ion",
      "Charge",
      "m/z",
      "Error (ppm)",
      "Intensity"
    ]);
    assert.equal(batches.length, 0);
    await show.click();
    await expect(panel.getByText(/matched b\/y ions ·/)).toBeVisible();
    await expect(
      panel.getByRole("radio", { name: "Raw intensity", exact: true })
    ).toBeChecked();
    await page.waitForFunction(() => {
      const node = document.querySelector(".chromatogram-panel .plot");
      return (
        node?.data?.filter((trace) => trace.mode === "lines").length > 5 &&
        node.layout.yaxis.title.text === "Intensity" &&
        Math.max(...node.data[0].y) > 100
      );
    });
    await panel.getByText("Relative intensity", { exact: true }).click();
    await page.waitForFunction(() => {
      const node = document.querySelector(".chromatogram-panel .plot");
      return (
        node?.data?.filter((trace) => trace.mode === "lines").length > 5 &&
        node.layout.yaxis.title.text === "Relative intensity (%)"
      );
    });
    const relative = await plot.evaluate((node) =>
      node.data
        .filter((trace) => trace.mode === "lines")
        .map((trace) => ({ name: trace.name, max: Math.max(...trace.y) }))
    );
    assert.ok(relative.every((trace) => Math.abs(trace.max - 100) < 1e-6));
    assert.equal(batches.length, 1);
    await panel.getByText("Raw intensity", { exact: true }).click();
    await page.waitForFunction(() => {
      const node = document.querySelector(".chromatogram-panel .plot");
      return (
        node?.layout.yaxis.title.text === "Intensity" && Math.max(...node.data[0].y) > 100
      );
    });
    const name = relative[1].name;
    const label = name.split(" · ")[0];
    const firstFragment = ionTable.getByRole("checkbox", {
      name: `Show ${label} XIC`,
      exact: true
    });
    const originalColor = await plot.evaluate(
      (node, name) => node.data.find((trace) => trace.name === name).line.color,
      name
    );

    // Sorting and filtering only change table rows, not selected traces or colors.
    await ionTable.locator('th[data-accessor="mz"]').click();
    await expect(firstFragment).toBeChecked();
    await ionTable
      .locator(
        'th[data-accessor="label"] .mantine-datatable-header-cell-filter-action-icon'
      )
      .click();
    const filter = page.getByRole("textbox", { name: "Find fragment ion", exact: true });
    await filter.fill("y");
    await expect(ionTable.getByText(/6 of 11 matched assignments/)).toBeVisible();
    assert.equal(
      await plot.evaluate(
        (node) => node.data.filter((trace) => trace.mode === "lines").length
      ),
      7
    );
    await filter.fill("");
    await ionTable.getByRole("heading", { name: "Fragment ions", exact: true }).click();
    assert.equal(
      await plot.evaluate(
        (node, name) => node.data.find((trace) => trace.name === name).line.color,
        name
      ),
      originalColor
    );
    await ionTable.getByRole("button", { name: "All matched", exact: true }).click();
    await expect
      .poll(() =>
        plot.evaluate(
          (node) => node.data.filter((trace) => trace.mode === "lines").length
        )
      )
      .toBe(12);
    await ionTable.getByRole("button", { name: "Clear", exact: true }).click();
    await expect
      .poll(() =>
        plot.evaluate(
          (node) => node.data.filter((trace) => trace.mode === "lines").length
        )
      )
      .toBe(1);
    await ionTable.getByRole("button", { name: "Top 6", exact: true }).click();
    await expect
      .poll(() =>
        plot.evaluate(
          (node) => node.data.filter((trace) => trace.mode === "lines").length
        )
      )
      .toBe(7);
    assert.equal(batches.length, 1);

    // Focus is shared by the ion label, spectrum marker, and chromatogram trace.
    await ionTable
      .getByRole("button", { name: `Highlight ${label}`, exact: true })
      .click();
    await page.waitForFunction(
      (name) =>
        document
          .querySelector(".chromatogram-panel .plot")
          .data.some((trace) => trace.name === name && trace.line.width === 3),
      name
    );
    const focused = await page
      .locator(".inspector .plot")
      .evaluate((node) => node.data.find((trace) => trace.line?.width === 3));
    assert.equal(focused.line.color, originalColor);
    assert.equal(focused.x[0], focused.x[1]);
    await ionTable
      .getByRole("button", { name: `Highlight ${label}`, exact: true })
      .click();
    await firstFragment.uncheck();
    await page.waitForFunction(
      (name) =>
        !document
          .querySelector(".chromatogram-panel .plot")
          .data.some((trace) => trace.name === name),
      name
    );
    assert.equal(batches.length, 1);
    await firstFragment.check();
    await panel.getByText("Relative intensity", { exact: true }).click();
    await page.locator(".map-panel .plot").evaluate((node) =>
      node.emit("plotly_relayout", {
        "xaxis.range[0]": 3.5,
        "xaxis.range[1]": 4.7
      })
    );
    await expect.poll(() => batches.length).toBe(2);
    assert.equal(batches[1].start, 210);
    assert.equal(batches[1].stop, 282);
    await expect(panel.getByText(/matched b\/y ions ·/)).toBeVisible();
    await page.waitForFunction(() => {
      const nodes = [...document.querySelectorAll(".explorer .plot")];
      return (
        nodes.length === 2 && nodes.every((node) => node.layout.xaxis.range[0] === 3.5)
      );
    });
    const margins = await page
      .locator(".explorer .plot")
      .evaluateAll((nodes) =>
        nodes.map((node) => [node._fullLayout.margin.l, node._fullLayout.margin.r])
      );
    assert.deepEqual(margins[0], margins[1]);
    await panel.screenshot({ path: BrowserArtifacts.path("mzloupe-fragment-xic.png") });
    await page
      .locator(".inspector")
      .screenshot({ path: BrowserArtifacts.path("mzloupe-fragment-table.png") });

    await panel.getByRole("button", { name: "Hide fragment XICs" }).click();
    release = new Promise((done) => {
      resolveDelayed = done;
    });
    await show.click();
    await expect.poll(() => batches.length).toBe(3);
    await page.getByRole("button", { name: /^F02/ }).click();
    const ddaRow = page
      .getByRole("row")
      .filter({ hasText: "F02" })
      .filter({ has: page.getByRole("cell", { name: "scan=80", exact: true }) });
    await expect(ddaRow).toBeVisible();
    await ddaRow.click();
    await expect(show).toBeDisabled();
    await expect(
      ionTable.getByRole("heading", { name: "Fragment ions", exact: true })
    ).toBeVisible();
    await expect(ionTable.getByRole("checkbox")).toHaveCount(0);
    await expect(
      ionTable.getByRole("button", { name: "Top 6", exact: true })
    ).toHaveCount(0);
    await expect(
      panel.getByText("Fragment XICs require DIA mode in project setup.")
    ).toBeVisible();
    resolveDelayed();
    await expect(panel.getByText(/matched b\/y ions ·/)).toHaveCount(0);
    await expect
      .poll(() =>
        plot.evaluate(
          (node) => node.data.filter((trace) => trace.mode === "lines").length
        )
      )
      .toBe(1);
    assert.equal(batches.length, 3);

    // Revisiting a previously enabled PSM starts in MS1-only mode again.
    await page.getByRole("button", { name: /^F01/ }).click();
    const diaRow = page
      .getByRole("row")
      .filter({ hasText: "F01" })
      .filter({
        has: page.getByRole("cell", { name: "scan=80", exact: true })
      });
    await expect(diaRow).toBeVisible();
    await diaRow.click();
    await expect(show).toBeEnabled();
    assert.equal(batches.length, 3);

    // Mode selections round-trip through the same editor used for other inputs.
    await page.getByRole("button", { name: "Project setup", exact: true }).click();
    const mode = page.getByRole("textbox", {
      name: "Acquisition mode for fraction_02",
      exact: true
    });
    await expect(mode).toHaveValue("DDA");
    await mode.click();
    await page.getByRole("option", { name: "DIA", exact: true }).click();
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(page.getByText("Project saved.", { exact: true })).toBeVisible();
    const saved = (await api.request({ method: "GET", url: "/api/library" })).body[0];
    assert.equal(saved.configuration.acquisitions[1].mode, "DIA");
    assert.deepEqual(errors, []);
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "fragment-xic");
    throw error;
  } finally {
    resolveDelayed?.();
    await browser?.close();
    await api.close();
  }
});
