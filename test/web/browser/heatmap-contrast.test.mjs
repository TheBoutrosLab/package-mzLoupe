import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BrowserArtifacts } from "../browser-artifacts.mjs";

test("Heatmap contrast preserves data and supports automatic, full, and custom limits", async () => {
  const require = createRequire(new URL("../../../web/package.json", import.meta.url));
  const { chromium, expect } = require("@playwright/test");
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const assets = path.join(root, "mzloupe/static");
  const origin = "https://mzloupe.test";
  const fixture = process.env.MZLOUPE_MAP_FIXTURE;
  const original = fixture
    ? JSON.parse(await readFile(fixture, "utf8"))
    : {
        intensity: Array.from({ length: 160 }, (_, row) =>
          Array.from({ length: 240 }, (_, column) =>
            row > 130 && column % 3 === 0 ? 0 : 6 + row / 100 + column / 200
          )
        ),
        bounds: [0, 5400, 350, 1300],
        scale_max: 10,
        events: []
      };
  // A rare bright bin exercises automatic clipping without altering the rest of the fixture.
  if (!fixture) {
    original.intensity[0][0] = 12;
  }
  const actualMaximum = Math.max(...original.intensity.flat());
  const second = {
    ...original,
    intensity: original.intensity.map((row) => row.map((value) => value / 2))
  };
  const acquisitions = ["01", "02"].map((number) => ({
    id: "fraction_" + number,
    sample: "Contrast preview",
    fraction: "F" + number,
    ms2: 0,
    identified: null,
    layers: []
  }));
  const configuration = {
    name: "Contrast preview",
    acquisitions: acquisitions.map((row) => ({
      id: row.id,
      sample: row.sample,
      fraction: row.fraction,
      mzml: "/example/" + row.id + ".mzML"
    })),
    samples: [{ name: "Contrast preview", identifications: [] }]
  };
  const mimeTypes = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml"
  };

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1800, height: 1100 } });
    const errors = [];
    const requests = [];
    page.on("pageerror", (error) => errors.push(error.message));

    // Fulfill assets and API fixtures directly from this process: no HTTP server or
    // listening port is started, and no mzML preparation runs for this UI check.
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname === "/api/library") return route.fulfill({ json: [] });
      if (url.pathname === "/api/preparation-plan")
        return route.fulfill({ json: { added: 0, changed: 0, reused: 2 } });

      if (url.origin !== origin) {
        return route.abort();
      }
      if (url.pathname.startsWith("/api/")) {
        requests.push(url.pathname);
        let json;
        if (url.pathname === "/api/status") {
          json = {
            state: "ready",
            message: "Contrast preview",
            progress: 1,
            token: "contrast"
          };
        } else if (url.pathname === "/api/configuration") {
          json = configuration;
        } else if (url.pathname.endsWith("/map")) {
          json = url.pathname.includes("fraction_02") ? second : original;
        } else if (url.pathname.endsWith("/psms")) {
          json = {
            rows: [],
            total: 0,
            peptides: 0,
            page: 0,
            page_size: 50,
            facets: { fractions: [], layers: [], score_types: [] }
          };
        } else if (url.pathname === "/api/projects/contrast") {
          json = { name: "Contrast preview", acquisitions, protein_groupings: [] };
        } else {
          return route.fulfill({
            status: 404,
            json: { detail: "Unexpected test request" }
          });
        }
        return route.fulfill({ json });
      }
      const filename = path.join(
        assets,
        url.pathname === "/" ? "index.html" : url.pathname
      );
      return route.fulfill({
        body: await readFile(filename),
        contentType: mimeTypes[path.extname(filename)] || "application/octet-stream"
      });
    });

    await page.goto(origin);
    const panel = page.locator(".map-panel");
    const plot = panel.locator(".plot");
    const contrast = page.getByRole("button", { name: "Adjust heatmap contrast" });
    await expect(contrast).toContainText("Auto");
    await page.waitForFunction(
      () => document.querySelector(".map-panel .plot")?.data?.[0]?.zmax
    );
    const automatic = await plot.evaluate((node) => ({
      lower: node.data[0].zmin,
      upper: node.data[0].zmax,
      intensity: node.data[0].z,
      showscale: node.data[0].showscale
    }));
    assert.ok(automatic.lower > 0);
    assert.ok(automatic.upper < actualMaximum);
    assert.deepEqual(automatic.intensity, original.intensity);
    assert.equal(automatic.showscale, false);
    await panel.screenshot({ path: BrowserArtifacts.path("mzloupe-contrast-auto.png") });

    await contrast.click();
    const mode = page.getByRole("textbox", { name: "Color contrast", exact: true });
    await mode.click();
    await page.getByRole("option", { name: "Full range", exact: true }).click();
    await page.waitForFunction((maximum) => {
      const trace = document.querySelector(".map-panel .plot")?.data?.[0];
      return trace?.zmin === 0 && trace?.zmax === maximum;
    }, actualMaximum);
    await page.getByRole("heading", { name: "MS1 acquisition map" }).click();
    await expect(mode).not.toBeVisible();
    await panel.screenshot({ path: BrowserArtifacts.path("mzloupe-contrast-full.png") });

    await contrast.click();
    await mode.click();
    await page.getByRole("option", { name: "Custom limits", exact: true }).click();
    const lower = page.getByRole("textbox", { name: "Lower color limit", exact: true });
    const upper = page.getByRole("textbox", { name: "Upper color limit", exact: true });
    await upper.fill("8.8");
    await lower.fill("6.8");
    await page.waitForFunction(() => {
      const trace = document.querySelector(".map-panel .plot")?.data?.[0];
      return trace?.zmin === 6.8 && trace?.zmax === 8.8;
    });
    await panel.screenshot({
      path: BrowserArtifacts.path("mzloupe-contrast-custom.png")
    });
    await lower.fill("9.8");
    await expect(page.getByRole("alert")).toContainText(
      "lower limit smaller than the upper limit"
    );
    assert.deepEqual(
      await plot.evaluate((node) => [node.data[0].zmin, node.data[0].zmax]),
      [6.8, 8.8]
    );
    await lower.fill("6.8");
    await page.getByRole("heading", { name: "MS1 acquisition map" }).click();
    await expect(mode).not.toBeVisible();

    // Color changes preserve raw hover values and the linked retention-time viewport.
    assert.deepEqual(await plot.evaluate((node) => node.data[0].z), original.intensity);
    const start = original.bounds[0] / 60;
    const stop = original.bounds[1] / 60;
    const zoom = [start + (stop - start) * 0.2, start + (stop - start) * 0.4];
    await plot.evaluate(
      (node, range) =>
        node.emit("plotly_relayout", {
          "xaxis.range[0]": range[0],
          "xaxis.range[1]": range[1]
        }),
      zoom
    );
    await page.waitForFunction((range) => {
      const axis = document.querySelector(".map-panel .plot")?._fullLayout?.xaxis;
      return axis?.range?.[0] === range[0] && axis?.range?.[1] === range[1];
    }, zoom);
    await contrast.click();
    await mode.click();
    await page
      .getByRole("option", { name: "Auto (5th–99.5th percentile)", exact: true })
      .click();
    await page.waitForFunction((limits) => {
      const trace = document.querySelector(".map-panel .plot")?.data?.[0];
      return trace?.zmin === limits.lower && trace?.zmax === limits.upper;
    }, automatic);
    assert.deepEqual(await plot.evaluate((node) => node._fullLayout.xaxis.range), zoom);

    await mode.click();
    await page.getByRole("option", { name: "Custom limits", exact: true }).click();
    await upper.fill("8.8");
    await lower.fill("6.8");
    await page.getByRole("heading", { name: "MS1 acquisition map" }).click();
    await expect(mode).not.toBeVisible();
    await page.getByRole("button", { name: /^F02/ }).click();
    await page.waitForFunction((value) => {
      const trace = document.querySelector(".map-panel .plot")?.data?.[0];
      return trace?.z?.[0]?.[0] === value && trace?.zmin === 6.8 && trace?.zmax === 8.8;
    }, second.intensity[0][0]);
    assert.ok(
      !requests.some((url) => url.endsWith("/xic") || url.endsWith("/map-target"))
    );
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify({
        automatic: [automatic.lower, automatic.upper],
        full: [0, actualMaximum],
        custom: [6.8, 8.8],
        pageErrors: errors
      })
    );
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "heatmap-contrast");
    throw error;
  } finally {
    await browser.close();
  }
});
