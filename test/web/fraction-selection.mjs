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
  const base = url + "/api/projects/" + status.token;
  const project = await (await page.request.get(base)).json();
  const fractions = project.acquisitions;
  await page.goto(url);
  await page.getByRole("heading", { name: "MS1 acquisition map" }).waitFor();
  const observations = [];
  for (const fraction of fractions) {
    await page.getByRole("button", { name: new RegExp("^" + fraction.fraction) }).click();
    await expect(
      page.locator(".results tbody tr").first().locator("td").first()
    ).toHaveText(fraction.fraction);
    await page.locator(".results tbody tr").first().click();
    await expect(page.locator(".chromatogram-panel .caption").first()).toContainText(
      "Peptide precursor"
    );
    await page.waitForFunction(
      () => document.querySelector(".chromatogram-panel .plot")?.data?.[0]?.y?.length > 0
    );
    const trace = await page.locator(".chromatogram-panel .plot").evaluate((plot) => ({
      count: plot.data[0].y.length,
      max: Math.max(...plot.data[0].y)
    }));
    const active = await page
      .getByRole("textbox", { name: "Active fraction", exact: true })
      .inputValue();
    if (active !== fraction.fraction) throw Error("PSM jumped fractions: " + active);
    observations.push({ fraction: active, ...trace });
    await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
    await expect(page.locator(".chromatogram-panel .caption").first()).toContainText(
      "Manual target"
    );
  }
  // Explicit sample-wide searching may navigate to another fraction.
  const targetFraction = fractions[1];
  const psms = await (
    await page.request.get(
      base +
        "/psms?" +
        new URLSearchParams({ sample: targetFraction.sample, source: targetFraction.id })
    )
  ).json();
  const target = psms.rows[0];
  await page.getByRole("textbox", { name: "PSM scope", exact: true }).click();
  await page.getByRole("option", { name: "All sample fractions", exact: true }).click();
  await page
    .locator(
      '.results th[data-accessor="native"] .mantine-datatable-header-cell-filter-action-icon'
    )
    .click();
  await page
    .getByRole("textbox", { name: "Native scan ID", exact: true })
    .fill(target.native);
  await page.getByRole("textbox", { name: "Match", exact: true }).click();
  await page.getByRole("option", { name: "Exactly matches", exact: true }).click();
  await page
    .getByRole("heading", { name: "Peptide-spectrum matches", exact: true })
    .click();
  const row = page
    .locator(".results tbody tr")
    .filter({ hasText: target.native })
    .filter({ hasText: targetFraction.fraction })
    .first();
  await row.click();
  await expect(
    page.getByRole("textbox", { name: "Active fraction", exact: true })
  ).toHaveValue(targetFraction.fraction);
  await page.waitForFunction(
    () => document.querySelector(".chromatogram-panel .plot")?.data?.[0]?.y?.length > 0
  );
  // Physically click a populated heatmap cell and verify precise peak selection + XIC.
  await page.locator(".map-panel .plot").scrollIntoViewIfNeeded();
  const location = await page.locator(".map-panel .plot").evaluate((plot) => {
    const data = plot.data[0];
    let best = { value: -1, x: 0, y: 0 };
    for (let y = 0; y < data.z.length; y++)
      for (let x = 0; x < data.z[y].length; x++) {
        if (data.z[y][x] > best.value) best = { value: data.z[y][x], x, y };
      }
    return {
      x: plot._fullLayout.xaxis._offset + plot._fullLayout.xaxis.l2p(data.x[best.x]),
      y: plot._fullLayout.yaxis._offset + plot._fullLayout.yaxis.l2p(data.y[best.y])
    };
  });
  const box = await page.locator(".map-panel .plot").boundingBox();
  const response = page.waitForResponse((response) =>
    response.url().endsWith("/map-target")
  );
  await page.mouse.click(box.x + location.x, box.y + location.y);
  const selected = await (await response).json();
  if (!selected.mz) throw Error(JSON.stringify(selected));
  await expect(page.locator(".chromatogram-panel .caption").first()).toContainText(
    "MS1 map selection"
  );
  await page.waitForFunction(
    () =>
      Math.max(
        ...(document.querySelector(".chromatogram-panel .plot")?.data?.[0]?.y || [0])
      ) > 0
  );
  const input = await page
    .getByRole("textbox", { name: "Target m/z", exact: true })
    .inputValue();
  if (Math.abs(Number(input) - selected.mz) > 0.00001)
    throw Error("Map target not propagated");
  expect(errors).toEqual([]);
  await page.screenshot({
    path: "/private/tmp/mzloupe-selection-fixed.png",
    fullPage: true
  });
} finally {
  await browser.close();
}
