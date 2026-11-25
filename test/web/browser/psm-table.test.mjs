import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ApiSession } from "../fixtures/ApiSession.mjs";
import { BrowserArtifacts } from "../browser-artifacts.mjs";

test("PSM table filtering and inspection stay linked to the Python API", async () => {
  const require = createRequire(new URL("../../../web/package.json", import.meta.url));
  const { chromium, expect } = require("@playwright/test");
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const assets = path.join(root, "mzloupe/static");
  const origin = "https://mzloupe.test";
  const session = new ApiSession("psm_browser_api.py");
  const api = (request) => session.request(request);
  const mime = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml"
  };
  let browser;
  try {
    await session.ready;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1800, height: 1200 } });
    const errors = [];
    const selections = [];
    const queries = [];
    let last;
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) {
        const filename = path.join(
          assets,
          url.pathname === "/" ? "index.html" : url.pathname
        );
        return route.fulfill({
          body: await readFile(filename),
          contentType: mime[path.extname(filename)]
        });
      }
      if (/spectra|xic|annotations/.test(url.pathname)) selections.push(url.pathname);
      const result = await api({
        method: request.method(),
        url: url.pathname + url.search,
        body: request.postDataJSON()
      });
      if (url.pathname.endsWith("/psms")) {
        queries.push(url.searchParams);
        last = { parameters: url.searchParams, body: result.body };
      }
      return route.fulfill({ status: result.status, json: result.body });
    });
    await page.goto(origin);
    await expect(
      page.getByRole("textbox", { name: "Search PSMs", exact: true })
    ).toHaveCount(0);
    const table = page.locator(".psm-datatable");
    const heading = page.getByRole("heading", {
      name: "Peptide-spectrum matches",
      exact: true
    });
    async function filter(column) {
      await table
        .locator(
          `th[data-accessor="${column}"] .mantine-datatable-header-cell-filter-action-icon`
        )
        .click();
    }
    async function settled(predicate) {
      await expect.poll(() => !!last && predicate(last)).toBe(true);
      await expect(table.locator(".mantine-datatable-loader-fetching")).toHaveCount(0);
    }
    await settled(
      (value) =>
        value.parameters.get("source") === "fraction_01" && value.body.total === 5
    );
    await page.getByRole("textbox", { name: "PSM scope", exact: true }).click();
    await page.getByRole("option", { name: "All sample fractions", exact: true }).click();
    await settled((value) => !value.parameters.has("source") && value.body.total === 10);
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled((value) => value.body.total === 161);

    await expect(table.locator('th[data-accessor="precursor_mz"]')).toContainText(
      "Precursor m/z"
    );
    await expect(table.locator("tbody tr").first()).toContainText("400.68730");
    await table.locator('th[data-accessor="precursor_mz"]').click();
    await settled((value) => value.parameters.get("sort_by") === "precursor_mz");
    await filter("precursor_mz");
    await page
      .getByRole("textbox", { name: "Minimum precursor m/z", exact: true })
      .fill("400.68");
    await page
      .getByRole("textbox", { name: "Maximum precursor m/z", exact: true })
      .fill("400.70");
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).precursor_mz_max === 400.7 &&
        value.body.total === 161
    );
    await heading.click();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled(
      (value) => JSON.parse(value.parameters.get("filters")).precursor_mz_max === null
    );

    // Select one real PSM, then ensure table operations never request another plot.
    await table.locator("tbody tr").first().click();
    await expect(page.locator(".inspector .plot")).toBeVisible();
    await expect(page.locator(".chromatogram-panel .plot")).toBeVisible();
    await expect(
      page.locator(".chromatogram-panel .caption").filter({ hasText: "Extracting" })
    ).toHaveCount(0);
    const selectionCount = selections.length;

    await table.locator('th[data-accessor="proteins"]').click();
    await settled(
      (value) =>
        value.parameters.get("sort_by") === "proteins" && value.body.total === 161
    );
    assert.ok(last.body.rows.every((row) => row.protein_accessions.length > 0));
    assert.equal(selections.length, selectionCount);

    await table.locator('th[data-accessor="score"]').click();
    await table.locator('th[data-accessor="score"]').click();
    await settled(
      (value) =>
        value.parameters.get("sort_by") === "score" &&
        value.parameters.get("sort_direction") === "desc"
    );
    assert.equal(last.body.rows[0].score, 0.42); // Highest value was inserted beyond page one.
    await page.getByRole("button", { name: "next page", exact: true }).click();
    await settled((value) => value.parameters.get("page") === "1");

    await filter("proteins");
    await page
      .getByRole("textbox", { name: "Protein accession", exact: true })
      .fill("zz_hidden_127");
    await settled(
      (value) =>
        value.body.total === 1 &&
        JSON.parse(value.parameters.get("filters")).proteins.value === "zz_hidden_127"
    );
    assert.equal(last.parameters.get("page"), "0");
    assert.equal(last.body.rows[0].score, 0.127);
    await heading.click();
    await expect(table.locator("tbody tr")).toHaveCount(1);
    await expect(table.locator(".protein-cell")).toContainText("P0CE47");
    assert.equal(selections.length, selectionCount);

    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled((value) => value.body.total === 161);
    await filter("sequence");
    await page
      .getByRole("textbox", { name: "Peptide sequence", exact: true })
      .fill("PEP%");
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).sequence.value === "PEP%" &&
        value.body.total === 0
    );
    await page
      .getByRole("textbox", { name: "Peptide sequence", exact: true })
      .fill("PEPTIDE");
    await page.getByRole("textbox", { name: "Match", exact: true }).click();
    await page.getByRole("option", { name: "Exactly matches", exact: true }).click();
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).sequence.mode === "exact" &&
        value.body.total > 50
    );
    await heading.click();
    await expect(table.locator('th[data-accessor="sequence"] [data-active]')).toHaveCount(
      1
    );

    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled((value) => value.body.total === 161);
    await filter("rt");
    await page
      .getByRole("textbox", { name: "Minimum RT (min)", exact: true })
      .fill("3.9");
    await page
      .getByRole("textbox", { name: "Maximum RT (min)", exact: true })
      .fill("4.2");
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).rt_max === 4.2 && value.body.total > 0
    );
    assert.ok(last.body.rows.every((row) => row.rt >= 234 && row.rt <= 252));
    const beforeInvalid = queries.length;
    await page.getByRole("textbox", { name: "Minimum RT (min)", exact: true }).fill("5");
    await expect(
      page.getByText("RT minimum must not exceed maximum.", { exact: true })
    ).toBeVisible();
    await page.waitForTimeout(250);
    assert.equal(queries.length, beforeInvalid);
    await page
      .getByRole("textbox", { name: "Minimum RT (min)", exact: true })
      .fill("3.9");
    await heading.click();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled((value) => value.body.total === 161);
    await filter("resolved");
    await page.getByRole("textbox", { name: "Link status", exact: true }).click();
    await page.getByRole("option", { name: "Unresolved", exact: true }).click();
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).link === "unresolved" &&
        value.body.total === 1
    );
    assert.equal(last.body.rows[0].source, null);
    await heading.click();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await settled((value) => value.body.total === 161);
    await filter("layer");
    await page
      .getByRole("textbox", { name: "Identification layers", exact: true })
      .click();
    await page.getByRole("option", { name: "Search", exact: true }).click();
    await heading.click();
    await settled(
      (value) =>
        JSON.parse(value.parameters.get("filters")).layers.includes("Search") &&
        value.body.total === 151
    );
    await filter("fraction");
    await page.getByRole("textbox", { name: "Fractions", exact: true }).click();
    await page.getByRole("option", { name: "F02", exact: true }).click();
    await heading.click();
    await settled((value) =>
      JSON.parse(value.parameters.get("filters")).fractions.includes("fraction_02")
    );
    assert.ok(
      last.body.rows.every(
        (row) => row.source === "fraction_02" && row.layer === "Search"
      )
    );
    assert.equal(selections.length, selectionCount);

    // Follow a real PSM across fractions without waiting for a map reset effect.
    const crossFraction = last.body.rows[0];
    assert.equal(crossFraction.source, "fraction_02");
    assert.equal(crossFraction.resolved, 1);
    await table.locator("tbody tr").first().click();
    await expect(
      page.getByRole("textbox", { name: "Active fraction", exact: true })
    ).toHaveValue("F02");
    await expect(page.locator(".scan-info strong")).toHaveText(crossFraction.sequence);
    await expect
      .poll(() => new URL(page.url()).searchParams.get("source"))
      .toBe("fraction_02");
    await expect
      .poll(() => new URL(page.url()).searchParams.get("psm"))
      .toBe(String(crossFraction.id));

    // Restoring the address must preserve both the acquisition and explicit candidate.
    const linked = page.url();
    assert.equal(
      new URL(linked).searchParams.get("project"),
      (await api({ method: "GET", url: "/api/status" })).body.project_id
    );
    await page.reload();
    await expect(
      page.getByRole("textbox", { name: "Active fraction", exact: true })
    ).toHaveValue("F02");
    await expect(page.locator(".scan-info strong")).toHaveText(crossFraction.sequence);
    await expect.poll(() => page.url()).toBe(linked);
    await page.getByRole("button", { name: "F01", exact: false }).click();
    await expect(page.locator(".inspector .plot")).toHaveCount(0);
    await page.waitForFunction(
      () =>
        document.querySelector(".map-panel .plot")?._fullLayout?.uirevision ===
        "fraction_01"
    );

    // Selecting measured MS1 evidence replaces the spectrum and drives its XIC.
    await page.locator(".map-panel .plot").scrollIntoViewIfNeeded();
    const mapCoordinates = await page.locator(".map-panel .plot").evaluate((node) => {
      const box = node.getBoundingClientRect();
      const x = node._fullLayout.xaxis;
      const y = node._fullLayout.yaxis;
      return {
        x: box.left + x._offset + x.l2p(4),
        y: box.top + y._offset + y.l2p(400.6873)
      };
    });
    await page.mouse.click(mapCoordinates.x, mapCoordinates.y);
    await expect(page.locator(".chromatogram-panel .caption").first()).toContainText(
      "MS1 map selection"
    );
    await expect(page.locator(".chromatogram-panel .plot")).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: "Target m/z", exact: true })
    ).toHaveValue("400.6873");
    await expect(page.locator(".inspector .plot")).toHaveCount(0);

    await expect(
      page.getByRole("button", { name: "Filter PSMs", exact: true })
    ).toHaveCount(0);
    assert.deepEqual(errors, []);
    await page
      .locator(".results")
      .screenshot({ path: BrowserArtifacts.path("mzloupe-psm-datatable.png") });
    console.log(
      "Real ASGI API: table operations, cross-fraction selection, linked-view restore, and MS1/XIC selection passed."
    );
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "psm-table");
    throw error;
  } finally {
    await browser?.close();
    await session.close();
  }
});
