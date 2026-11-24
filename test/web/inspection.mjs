import { createRequire } from "node:module";
const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:8765");
await page.getByRole("heading", { name: "MS1 acquisition map" }).waitFor();
await page.getByRole("cell", { name: "scan=80", exact: true }).first().click();
await page.getByText("Assignments", { exact: true }).waitFor();
await page.getByRole("cell", { name: "PEPTIED", exact: true }).first().click();
await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
await page.waitForFunction(() =>
  [...document.querySelectorAll(".plot")].some((plot) =>
    plot.data?.some((trace) => trace.y?.length > 50 && trace.mode === "lines")
  )
);
await page.waitForTimeout(300);
await page.getByRole("button", { name: "F02", exact: false }).click();
await page.waitForTimeout(700);
if (await page.getByText("Assignments", { exact: true }).count())
  throw Error("Fraction switch retained stale scan");
await page.getByRole("cell", { name: "scan=80", exact: true }).first().click();
await page.getByText("Assignments", { exact: true }).waitFor();
await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
await page.waitForTimeout(500);
await page.getByRole("cell", { name: "PEPTIDE", exact: true }).first().click();
await page.waitForFunction(() =>
  [...document.querySelectorAll(".plot")].some((plot) =>
    plot.data?.some((trace) => trace.text?.length > 3)
  )
);
await page.waitForTimeout(500);
await page.locator(".map-panel .nsewdrag").scrollIntoViewIfNeeded();
const dragArea = await page.locator(".map-panel .nsewdrag").boundingBox();
await page.mouse.move(dragArea.x + 60, dragArea.y + 30);
await page.mouse.down();
await page.mouse.move(
  dragArea.x + dragArea.width - 60,
  dragArea.y + dragArea.height - 30,
  { steps: 8 }
);
await page.mouse.up();
await page.waitForTimeout(500);
const ranges = await page
  .locator(".plot")
  .evaluateAll((plots) => [plots[0].layout.xaxis.range, plots[1].layout.xaxis.range]);
if (Math.abs(ranges[0][0] - ranges[1][0]) > 0.001)
  throw Error("RT axes are not synchronized");
const url = page.url();
await page.reload();
await page.getByText("Assignments", { exact: true }).waitFor();
if (page.url() !== url) throw Error("Saved scan URL changed during restore");
await page.waitForFunction(() =>
  [...document.querySelectorAll(".plot")].some((plot) =>
    plot.data?.some((trace) => trace.text?.length > 3)
  )
);
await page.getByRole("button", { name: "Extract XIC", exact: true }).click();
await page.waitForTimeout(700);
await page.screenshot({
  path: "/private/tmp/mzloupe-build/dashboard.png",
  fullPage: true
});
console.log(JSON.stringify({ pageErrors: errors, title: await page.title() }));
await browser.close();
if (errors.length) process.exit(1);
