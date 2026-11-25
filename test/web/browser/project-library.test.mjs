import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { ApiSession } from "../fixtures/ApiSession.mjs";
import { BrowserArtifacts } from "../browser-artifacts.mjs";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");

test("Project library saves drafts, reopens projects, protects edits, and manages history", async () => {
  const api = new ApiSession("library_browser_api.py");
  let browser;
  try {
    await api.ready;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1700, height: 1150 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await api.route(page);
    await page.goto("https://mzloupe.test");
    await expect(
      page.getByRole("heading", { name: "Projects", exact: true })
    ).toBeVisible();
    const original = (await api.request({ method: "GET", url: "/api/library" })).body[0];
    const initialId = original.id;
    const row = () => page.getByRole("row").filter({ hasText: "Renamed experiment" });

    // Editing reads configuration only; preparation starts only with Save and explore/Open.
    await page
      .getByRole("button", { name: "Actions for " + original.name, exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
    await page.getByLabel("Project name", { exact: true }).fill("Renamed experiment");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(page.getByText("Project saved.", { exact: true })).toBeVisible();
    let records = (await api.request({ method: "GET", url: "/api/library" })).body;
    assert.equal(records.length, 1);
    assert.equal(records[0].id, initialId);
    assert.equal(records[0].has_cache, false);

    // A setup URL restores the saved editor without triggering scientific preparation.
    await page.reload();
    await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
      "Renamed experiment"
    );
    assert.equal(
      (await api.request({ method: "GET", url: "/api/status" })).body.state,
      "empty"
    );

    // Switching away from a changed draft requires an explicit discard decision.
    await page.getByLabel("Project name", { exact: true }).fill("Unsaved name");
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    await page.getByRole("button", { name: "New project", exact: true }).click();
    await expect(
      page.getByRole("dialog", { name: "Unsaved project changes" })
    ).toBeVisible();
    await page.getByRole("button", { name: "Keep editing", exact: true }).click();
    await page.getByRole("button", { name: "New project", exact: true }).click();
    await page.getByRole("button", { name: "Discard changes", exact: true }).click();
    await page.getByLabel("Project name", { exact: true }).fill("Draft project");
    await page.getByRole("button", { name: "Save project", exact: true }).click();
    await expect(page.getByText("Project saved.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    const draftRow = page.getByRole("row").filter({ hasText: "Draft project" });
    await expect(draftRow).toContainText("draft");

    await page
      .getByRole("button", { name: "Actions for Draft project", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Archive", exact: true }).click();
    await expect(draftRow).toHaveCount(0);
    await page.getByLabel("Include archived", { exact: true }).check();
    await expect(draftRow).toContainText("Archived");
    await page
      .getByRole("button", { name: "Actions for Draft project", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Restore", exact: true }).click();
    await expect(draftRow).not.toContainText("Archived");

    await row().getByRole("button", { name: "Open", exact: true }).click();
    await expect(page.locator(".map-panel .plot")).toBeVisible({ timeout: 30000 });
    const opened = (await api.request({ method: "GET", url: "/api/status" })).body;
    assert.equal(opened.project_id, initialId);
    await page.getByRole("button", { name: "Project setup", exact: true }).click();
    await expect(page.locator(".preparation-plan")).toContainText("2 reused");
    await page.getByLabel("Project name", { exact: true }).fill("Prepared experiment");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(page.getByText("Project saved.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Explore", exact: true }).click();
    await expect(page.getByText(/Showing the previous prepared revision/)).toBeVisible();
    await page.getByRole("button", { name: "Project setup", exact: true }).click();
    await page.getByRole("button", { name: "Save and explore", exact: true }).click();
    await expect(
      page.getByText(/Showing the previous prepared revision/)
    ).not.toBeVisible();
    await expect(page.locator(".map-panel .plot")).toBeVisible();
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    const activeRow = page.getByRole("row").filter({ hasText: "Prepared experiment" });
    await expect(activeRow).toContainText("ready");
    await page
      .getByRole("button", { name: "Actions for Prepared experiment", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Duplicate", exact: true }).click();
    await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
      "Prepared experiment (copy)"
    );
    records = (
      await api.request({ method: "GET", url: "/api/library?include_archived=true" })
    ).body;
    assert.equal(records.length, 3);
    assert.equal(
      records.find((record) => record.id === initialId).name,
      "Prepared experiment"
    );
    assert.deepEqual(errors, []);
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    const copyRow = page
      .getByRole("row")
      .filter({ hasText: "Prepared experiment (copy)" });
    await expect(copyRow).toBeVisible();
    await page
      .getByRole("button", {
        name: "Actions for Prepared experiment (copy)",
        exact: true
      })
      .click();
    await page.getByRole("menuitem", { name: "Clear cache", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Clear cache" })).not.toBeVisible();
    await expect(copyRow).toContainText("needs preparation");
    await page
      .getByRole("button", {
        name: "Actions for Prepared experiment (copy)",
        exact: true
      })
      .click();
    await page.getByRole("menuitem", { name: "Delete project", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(copyRow).toHaveCount(0);
    assert.equal(
      (await api.request({ method: "GET", url: "/api/library?include_archived=true" }))
        .body.length,
      2
    );
    // Closing releases scientific readers so cache clearing works without restarting.
    await page
      .getByRole("button", { name: "Actions for Prepared experiment", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Close project", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Explore", exact: true })
    ).not.toBeVisible();
    assert.equal(
      (await api.request({ method: "GET", url: "/api/status" })).body.state,
      "empty"
    );
    await page
      .getByRole("button", { name: "Actions for Prepared experiment", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Clear cache", exact: true }).click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(
      page.getByRole("row").filter({ hasText: "Prepared experiment" })
    ).toContainText("needs preparation");
    await expect(
      page.getByRole("dialog", { name: "Clear cache", exact: true })
    ).not.toBeVisible();
    assert.deepEqual(errors, []);
    await page.screenshot({
      path: BrowserArtifacts.path("project-library.png"),
      fullPage: true,
      animations: "disabled"
    });
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "project-library");
    throw error;
  } finally {
    await browser?.close();
    await api.close();
  }
});
