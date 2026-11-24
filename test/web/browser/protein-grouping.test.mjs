import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BrowserArtifacts } from "../browser-artifacts.mjs";

test("Protein grouping supports collection choices, scopes, and ambiguous assignments", async () => {
  const require = createRequire(new URL("../../../web/package.json", import.meta.url));
  const { chromium, expect } = require("@playwright/test");
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const assets = path.join(root, "mzloupe/static");
  const origin = "https://mzloupe.test";
  const acquisition = {
    id: "f01",
    sample: "Sample 1",
    fraction: "F01",
    ms2: 3,
    identified: 3,
    layers: ["Validated"]
  };
  const groupings = [
    {
      name: "Parent groups",
      path: "/data/both.idXML",
      collection: "protein_groups",
      samples: [],
      layers: [],
      group_count: 1
    },
    {
      name: "Subgroups",
      path: "/data/both.idXML",
      collection: "indistinguishable_proteins",
      samples: [],
      layers: [],
      group_count: 2
    }
  ];
  let configuration = {
    name: "Grouping preview",
    acquisitions: [
      { id: "f01", sample: "Sample 1", fraction: "F01", mzml: "/data/f01.mzML" }
    ],
    samples: [
      {
        name: "Sample 1",
        identifications: [{ name: "Validated", path: "/data/psms.idXML" }]
      }
    ],
    protein_groupings: groupings.map(({ group_count, ...row }) => row)
  };
  const parent = {
    id: "0:0",
    members: ["C", "D", "A", "B"],
    probability: 0.99,
    stored_probability: 0.99
  };
  const subgroups = [
    ["A", "B"],
    ["C", "D"]
  ].map((members, index) => ({
    id: `0:${index}`,
    members,
    probability: null,
    stored_probability: 0
  }));
  const rows = [["A"], ["A", "C"], []].map((accessions, index) => ({
    id: index + 1,
    source: "f01",
    layer: "Validated",
    sequence: "PEPTIDE",
    native: `scan=${index + 1}`,
    protein_accessions: accessions,
    score: 0.001,
    score_type: "PEP",
    rank: 1,
    resolved: 1,
    ordinal: index,
    fraction: "F01",
    rt: 240,
    charge: 2,
    precursor_mz: 400.6873,
    precursor_mz_origin: "idXML",
    link_reason: "",
    protein_groupings: [
      {
        name: "Parent groups",
        collection: "protein_groups",
        basis: "peptide",
        inferred_accessions: accessions,
        status: index === 2 ? "unassigned" : "assigned",
        groups: index === 2 ? [] : [parent]
      },
      {
        name: "Subgroups",
        collection: "indistinguishable_proteins",
        basis: "peptide",
        inferred_accessions: accessions,
        status: ["assigned", "ambiguous", "unassigned"][index],
        groups: index === 2 ? [] : index === 1 ? subgroups : [subgroups[0]]
      }
    ]
  }));
  const mimeTypes = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml"
  };
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1800, height: 1200 } });
    const errors = [];
    const unexpected = [];
    const selections = [];
    let applied;
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() =>
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: async (value) => {
            window.copiedAccessions = value;
          }
        }
      })
    );
    // Fulfill every request locally: no listening port, raw-data access, or server.
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
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
          message: "Grouping preview",
          progress: 1,
          token: applied ? "groups-2" : "groups"
        };
      } else if (url.pathname === "/api/configuration") {
        json = configuration;
      } else if (url.pathname === "/api/validate-project") {
        json = { issues: [] };
      } else if (url.pathname === "/api/open-configuration") {
        applied = route.request().postDataJSON();
        configuration = applied;
        json = { accepted: true };
      } else if (url.pathname === "/api/protein-groupings/inspect") {
        const input = route.request().postDataJSON().path;
        json = input.includes("empty")
          ? { protein_groups: 0, indistinguishable_proteins: 0 }
          : {
              protein_groups: input.includes("only") ? 0 : 1,
              indistinguishable_proteins: 2
            };
      } else if (/\/api\/projects\/groups(?:-2)?$/.test(url.pathname)) {
        json = {
          name: "Grouping preview",
          acquisitions: [acquisition],
          protein_groupings: groupings
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
        if (/spectra|xic|annotations/.test(url.pathname)) selections.push(url.pathname);
        else unexpected.push(url.pathname);
        return route.fulfill({
          status: 400,
          json: { detail: "Unexpected test request" }
        });
      }
      return route.fulfill({ json });
    });
    await page.goto(origin);
    const firstRow = page.locator(".protein-cell").nth(0);
    await expect(firstRow).toHaveText("C+3");
    await firstRow.getByRole("button").click();
    await expect(page.getByText("Representative: C", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Original peptide mappings (1)", { exact: true })
    ).toBeVisible();
    await expect(
      page.getByText("Inference peptide mappings", { exact: true })
    ).toBeVisible();
    await page.getByRole("button", { name: "Copy group members", exact: true }).click();
    assert.equal(await page.evaluate(() => window.copiedAccessions), "C\nD\nA\nB");
    await page.keyboard.press("Escape");
    const view = page.getByRole("textbox", {
      name: "Protein grouping view",
      exact: true
    });
    await view.click();
    await page.getByRole("option", { name: "Subgroups", exact: true }).click();
    await expect(firstRow).toHaveText("A+1");
    await expect(page.locator(".protein-cell").nth(1)).toHaveText("A (+1); C (+1)");
    await expect(
      page.locator(".protein-cell").nth(1).getByRole("button")
    ).toHaveAttribute("title", "Subgroups: A (+1); C (+1)");
    await expect(
      page.getByRole("textbox", { name: "Search PSMs", exact: true })
    ).toHaveCount(0);
    await expect(page.locator(".protein-cell").nth(2)).toHaveText("Not assigned");
    await page.locator(".protein-cell").nth(1).getByRole("button").click();
    await expect(page.getByText("Representative: A", { exact: true })).toBeVisible();
    await expect(page.getByText("Representative: C", { exact: true })).toBeVisible();
    await expect(
      page.getByText("No unique group assignment.", { exact: true })
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator(".protein-popover")).toHaveCount(0);

    await firstRow.getByRole("button").click();
    await expect(
      page.getByText("Probability: Not supplied", { exact: true })
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await view.click();
    await page
      .getByRole("option", { name: "Original peptide mappings", exact: true })
      .click();
    await expect(firstRow).toHaveText("A");
    assert.deepEqual(selections, []);

    await page.getByRole("button", { name: "Project setup", exact: true }).click();
    const panel = page.locator(".protein-grouping-panel");
    await page.getByRole("button", { name: "Add protein grouping", exact: true }).click();
    const row = panel.locator("tbody tr").last();
    const name = row.getByRole("textbox", { name: /^Grouping name/ });
    const file = row.getByRole("textbox", { name: /^Grouping idXML path/ });
    const collection = row.getByRole("textbox", { name: /^Group collection/ });
    await file.fill("/data/only.idXML");
    await name.fill("Custom grouping");
    await expect(collection).toHaveValue("Indistinguishable proteins (2)");
    await expect(name).toHaveValue("Custom grouping");
    await file.fill("/data/empty.idXML");
    await expect(
      row.getByText("This idXML contains no protein groups.", { exact: true })
    ).toBeVisible();
    await file.fill("/data/both.idXML");
    await expect(collection).toHaveValue("");
    await expect(collection).toHaveAttribute("placeholder", "Choose collection");
    await collection.click();
    await expect(
      page.getByRole("option", { name: "Protein groups (1)", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("option", { name: "Indistinguishable proteins (2)", exact: true })
    ).toBeVisible();
    await page.getByRole("option", { name: "Protein groups (1)", exact: true }).click();
    await row.getByRole("textbox", { name: /^Grouping samples/ }).click();
    await page.getByRole("option", { name: "Sample 1", exact: true }).click();
    await page.keyboard.press("Escape");
    await row.getByRole("textbox", { name: /^Grouping layers/ }).click();
    await page.getByRole("option", { name: "Validated", exact: true }).click();
    await page.keyboard.press("Escape");
    await panel.screenshot({
      path: BrowserArtifacts.path("mzloupe-grouping-inputs.png")
    });
    await page.getByRole("button", { name: "Apply changes", exact: true }).click();
    await expect.poll(() => applied?.protein_groupings?.length).toBe(3);
    assert.deepEqual(applied.protein_groupings[2], {
      name: "Custom grouping",
      path: "/data/both.idXML",
      collection: "protein_groups",
      samples: ["Sample 1"],
      layers: ["Validated"]
    });
    assert.deepEqual(errors, []);
    assert.deepEqual(unexpected, []);
    console.log(
      "Grouping selection, ambiguity, original mappings, copy, automatic collection choice, scopes, and activation passed."
    );
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "protein-grouping");
    throw error;
  } finally {
    await browser.close();
  }
});
