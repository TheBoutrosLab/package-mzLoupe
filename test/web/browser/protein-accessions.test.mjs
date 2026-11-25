import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BrowserArtifacts } from "../browser-artifacts.mjs";

test("Protein accession displays preserve membership and isolate spectrum selection", async () => {
  const require = createRequire(new URL("../../../web/package.json", import.meta.url));
  const { chromium, expect } = require("@playwright/test");
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const assets = path.join(root, "mzloupe/static");
  const origin = "https://mzloupe.test";
  const accessions = ["sp|P0CE47|EFTU1_ECOLI", "sp|P0CE48|EFTU2_ECOLI"];
  const longAccession = "DECOY_contaminant_" + "a_very_long_accession_".repeat(8);
  const acquisition = {
    id: "fraction_01",
    sample: "Protein preview",
    fraction: "F01",
    ms2: 4,
    identified: 3,
    layers: ["Validated"]
  };
  const configuration = {
    name: "Protein preview",
    acquisitions: [{ ...acquisition, mzml: "/example/fraction_01.mzML" }],
    samples: [{ name: acquisition.sample, identifications: [] }]
  };
  const rows = [
    accessions,
    [longAccession],
    [],
    ["DECOY_sp|P12345|NAME", "contaminant_protein"]
  ].map((proteins, index) => ({
    id: index + 1,
    source: acquisition.id,
    layer: "Validated",
    sequence: "PEPTIDE",
    native: "scan=" + (index + 1),
    protein_accessions: proteins,
    score: 0.001,
    score_type: "PEP",
    rank: 1,
    resolved: 1,
    ordinal: index,
    fraction: "F01",
    rt: 240 + index,
    charge: 2,
    precursor_mz: 400.6873,
    precursor_mz_origin: "idXML",
    link_reason: ""
  }));
  const mimeTypes = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml"
  };
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    const errors = [];
    const selectionRequests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    // Check the exact copy payload without accessing the user's real clipboard.
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: async (text) => {
            window.copiedAccessions = text;
          }
        }
      });
    });
    // All data and assets are fulfilled here; this test starts no HTTP server.
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/library") return route.fulfill({ json: [] });
      if (url.pathname === "/api/preparation-plan")
        return route.fulfill({ json: { added: 0, changed: 0, reused: 2 } });

      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith("/api/")) {
        const filename = path.join(
          assets,
          url.pathname === "/" ? "index.html" : url.pathname
        );
        return route.fulfill({
          body: await readFile(filename),
          contentType: mimeTypes[path.extname(filename)]
        });
      }
      let json;
      if (url.pathname === "/api/status") {
        json = {
          state: "ready",
          message: "Protein preview",
          progress: 1,
          token: "proteins"
        };
      } else if (url.pathname === "/api/configuration") {
        json = configuration;
      } else if (url.pathname === "/api/validate-project") {
        json = { issues: [] };
      } else if (url.pathname === "/api/projects/proteins") {
        json = {
          name: "Protein preview",
          acquisitions: [acquisition],
          protein_groupings: []
        };
      } else if (url.pathname.endsWith("/psms")) {
        json = {
          rows,
          total: rows.length,
          peptides: 1,
          page: 0,
          page_size: 50,
          facets: {
            fractions: [{ value: acquisition.id, label: acquisition.fraction }],
            layers: acquisition.layers,
            score_types: ["PEP"]
          }
        };
      } else if (url.pathname.endsWith("/map")) {
        json = {
          intensity: [
            [2, 3],
            [4, 5]
          ],
          bounds: [0, 600, 350, 800],
          scale_max: 5,
          events: []
        };
      } else {
        selectionRequests.push(url.pathname);
        return route.fulfill({
          status: 400,
          json: { detail: "Unexpected spectrum selection" }
        });
      }
      return route.fulfill({ json });
    });
    await page.goto(origin);
    await expect(page.locator('th[data-accessor="proteins"]')).toBeVisible();
    await expect(page.locator('th[data-accessor="rank"]')).toHaveCount(0);
    const shared = page.getByRole("button", {
      name: "Show 2 proteins: " + accessions[0],
      exact: true
    });
    await expect(shared).toContainText("P0CE47");
    await expect(shared).toContainText("+1");
    await shared.click();
    await expect(page.getByText("Mapped proteins (2)", { exact: true })).toBeVisible();
    for (const accession of accessions) {
      await expect(
        page.locator(".protein-accession-list li", { hasText: accession })
      ).toBeVisible();
    }
    await page.getByRole("button", { name: "Copy all", exact: true }).click();
    assert.equal(
      await page.evaluate(() => window.copiedAccessions),
      accessions.join("\n")
    );
    await expect(page.getByRole("status")).toHaveText("Copied");
    await page.keyboard.press("Escape");
    await expect(page.locator(".protein-accession-list")).not.toBeVisible();
    await shared.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".protein-accession-list")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Copy all", exact: true })
    ).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(page.locator(".protein-accession-list")).not.toBeVisible();

    const longButton = page.getByRole("button", {
      name: "Show 1 protein: " + longAccession,
      exact: true
    });
    const dimensions = await longButton
      .locator(".protein-representative")
      .evaluate((node) => ({
        width: node.clientWidth,
        content: node.scrollWidth,
        overflow: getComputedStyle(node).textOverflow
      }));
    assert.ok(dimensions.width <= 180);
    assert.ok(dimensions.content > dimensions.width);
    assert.equal(dimensions.overflow, "ellipsis");
    await longButton.click();
    await expect(
      page.locator(".protein-accession-list li", { hasText: longAccession })
    ).toBeVisible();
    await page.keyboard.press("Escape");
    const prefixed = page.getByRole("button", {
      name: "Show 2 proteins: DECOY_sp|P12345|NAME",
      exact: true
    });
    await expect(prefixed).toContainText("DECOY_sp|P12345|NAME");
    await expect(page.getByTitle("No protein mappings reported")).toHaveText("—");
    assert.deepEqual(selectionRequests, []);
    assert.deepEqual(errors, []);
    await shared.click();
    await page.screenshot({
      path: BrowserArtifacts.path("mzloupe-protein-accessions.png")
    });
    console.log(
      "Protein column, full lists, copy payload, keyboard access, ellipsis, and selection isolation passed."
    );
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "protein-accessions");
    throw error;
  } finally {
    await browser.close();
  }
});
