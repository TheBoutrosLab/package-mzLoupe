import { createRequire } from "node:module";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const url = process.env.MZLOUPE_URL || "http://127.0.0.1:8765";
const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 1200 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const status = await (await page.request.get(url + "/api/status")).json();
  if (status.state !== "ready") {
    throw new Error("Start this check with the synthetic demo project ready.");
  }
  const base = url + "/api/projects/" + status.token;
  const results = await (
    await page.request.get(
      base +
        "/psms?" +
        new URLSearchParams({
          sample: "Synthetic sample",
          source: "fraction_01",
          filters: JSON.stringify({ layers: ["Validated"] })
        })
    )
  ).json();
  const initial = results.rows.find((psm) => psm.ordinal === 79);
  await page.goto(
    url +
      "?" +
      new URLSearchParams({
        source: initial.source,
        scan: initial.ordinal,
        psm: initial.id
      })
  );

  const panel = page.locator(".chromatogram-panel");
  const plot = panel.locator(".plot");
  const toggle = page.getByRole("checkbox", { name: "Show PSMs (all layers)" });
  await expect(panel).toContainText("15 matching PSMs in 5 MS2 scans");
  await page.waitForFunction(
    () => document.querySelector(".chromatogram-panel .plot")?.data?.[1]?.x?.length === 5
  );
  const evidence = await plot.evaluate((node) => ({
    yRange: node._fullLayout.yaxis.range,
    text: node.data[1].hovertext,
    ids: node.data[1].customdata
  }));
  expect(evidence.text[0]).toContain("Search");
  expect(evidence.text[0]).toContain("Validated");
  expect(evidence.text[0]).toContain("PEPTIDE");
  expect(evidence.text[0]).toContain("PEPTIED");

  // Column filtering and overlay visibility do not change extraction evidence or scale.
  await page
    .locator(
      '.results th[data-accessor="sequence"] .mantine-datatable-header-cell-filter-action-icon'
    )
    .click();
  await page
    .getByRole("textbox", { name: "Peptide sequence", exact: true })
    .fill("absent-sequence");
  await page
    .getByRole("heading", { name: "Peptide-spectrum matches", exact: true })
    .click();
  await expect(
    page.locator(".results").getByText("No matching PSMs.", { exact: true })
  ).toBeVisible();
  await expect(panel).toContainText("15 matching PSMs in 5 MS2 scans");
  await toggle.uncheck();
  await page.waitForFunction(
    () => document.querySelector(".chromatogram-panel .plot")?.data?.length === 1
  );
  expect(await plot.evaluate((node) => node._fullLayout.yaxis.range)).toEqual(
    evidence.yRange
  );
  await toggle.check();
  await page.waitForFunction(
    () => document.querySelector(".chromatogram-panel .plot")?.data?.length === 2
  );

  // Click a later scan's actual Plotly marker, rather than dispatching a synthetic event.
  await plot.scrollIntoViewIfNeeded();
  const location = await plot.evaluate((node) => ({
    x: node._fullLayout.xaxis._offset + node._fullLayout.xaxis.l2p(node.data[1].x[4]),
    y: node._fullLayout.yaxis2._offset + node._fullLayout.yaxis2.l2p(node.data[1].y[4])
  }));
  const box = await plot.boundingBox();
  await page.mouse.move(box.x + location.x, box.y + location.y);
  await expect(plot.locator(".hoverlayer")).toContainText("Validated");
  await page.mouse.click(box.x + location.x, box.y + location.y);
  await expect(page).toHaveURL(new RegExp("psm=" + evidence.ids[4] + "(?:&|$)"));
  await expect(page.locator(".inspector .panel-title")).toContainText("scan=92");
  await page.waitForFunction(
    () =>
      document.querySelector(".chromatogram-panel .plot")?.data?.[1]?.marker
        ?.color?.[4] === "#e48735"
  );
  await panel.screenshot({
    path: process.env.MZLOUPE_SCREENSHOT || "/private/tmp/mzloupe-xic-psm-marks.png"
  });

  // A real MS1 signal can have no peptide evidence at its precursor m/z.
  const target = page.getByRole("textbox", { name: "Target m/z", exact: true });
  await target.fill("450");
  await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
  await expect(panel).toContainText("No matching PSMs in this fraction");
  await page.waitForFunction(
    () => document.querySelector(".chromatogram-panel .plot")?.data?.length === 1
  );

  // Evidence still renders when the interval contains an MS2 scan but no MS1 scans.
  await plot.evaluate((node) =>
    node.emit("plotly_relayout", {
      "xaxis.range[0]": 236 / 60,
      "xaxis.range[1]": 238 / 60
    })
  );
  await target.fill("400.6873");
  await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
  await expect(panel).toContainText("No MS1 scans are available");
  await expect(panel).toContainText("3 matching PSMs in 1 MS2 scan");
  await page.waitForFunction(() => {
    const traces = document.querySelector(".chromatogram-panel .plot")?.data;
    return traces?.[0]?.x?.length === 0 && traces?.[1]?.x?.length === 1;
  });

  expect(errors).toEqual([]);
  console.log(JSON.stringify({ marks: 5, matchingCandidates: 15, pageErrors: errors }));
} finally {
  await browser.close();
}
