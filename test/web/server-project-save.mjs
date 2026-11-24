import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const root = fileURLToPath(new URL("../../", import.meta.url));
const assets = path.join(root, "mzloupe/static");
const origin = "https://mzloupe.test";
const serverFiles = new Map();
const saves = [];
const requests = [];
const configuration = {
  name: "Remote analysis",
  acquisitions: ["01", "02"].map((number) => ({
    id: "fraction_" + number,
    sample: "Sample 1",
    fraction: "F" + number,
    mzml: "/remote/data/fraction_" + number + ".mzML"
  })),
  samples: [
    {
      name: "Sample 1",
      identifications: [
        { name: "Search", path: "/remote/data/search.idXML" },
        { name: "Validated", path: "/remote/data/validated.idXML" }
      ]
    }
  ]
};
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
  const downloads = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("download", (download) => downloads.push(download.suggestedFilename()));

  // Route fixtures and compiled assets in-process, without starting any server.
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) {
      const filename = path.join(
        assets,
        url.pathname === "/" ? "index.html" : url.pathname
      );
      return route.fulfill({
        body: await readFile(filename),
        contentType: mimeTypes[path.extname(filename)] || "application/octet-stream"
      });
    }
    requests.push(url.pathname);
    if (url.pathname === "/api/status") {
      return route.fulfill({
        json: {
          state: "empty",
          message: "Open a local project",
          progress: 0,
          token: null
        }
      });
    }
    if (url.pathname === "/api/import-project") {
      return route.fulfill({ json: configuration });
    }
    if (url.pathname === "/api/validate-project") {
      return route.fulfill({ json: { issues: [] } });
    }
    if (url.pathname === "/api/files") {
      assert.equal(url.searchParams.get("kind"), "directory");
      const directory =
        url.searchParams.get("path") === "~"
          ? "/remote/home/czhu"
          : url.searchParams.get("path");
      return route.fulfill({
        json: {
          directory,
          parent: path.posix.dirname(directory),
          entries: [],
          truncated: false
        }
      });
    }
    if (url.pathname === "/api/save-project") {
      const body = request.postDataJSON();
      saves.push(body);
      const target = path.posix.join(body.directory, body.filename);
      if (body.directory === "/denied") {
        return route.fulfill({
          status: 400,
          json: { detail: "Permission denied on server" }
        });
      }
      if (serverFiles.has(target) && !body.overwrite) {
        return route.fulfill({
          status: 409,
          json: { detail: "File already exists on server" }
        });
      }
      serverFiles.set(target, JSON.stringify(body.project));
      return route.fulfill({ json: { path: target } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });

  await page.goto(origin);
  await page.getByRole("button", { name: "Import JSON", exact: true }).click();
  await page
    .getByLabel("Project JSON path", { exact: true })
    .fill("/remote/project.json");
  await page.getByRole("button", { name: "Import into tables", exact: true }).click();
  await expect(page.getByLabel("Project name", { exact: true })).toHaveValue(
    "Remote analysis"
  );
  await expect(
    page.getByRole("button", { name: "Download JSON", exact: true })
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Save JSON", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Save project JSON", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Save project JSON" })).not.toHaveCSS(
    "color",
    "rgb(255, 255, 255)"
  );
  await page.getByLabel("File name", { exact: true }).fill("../wrong.json");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByLabel("File name", { exact: true }).fill("session.json");
  await page.getByRole("button", { name: "Browse directory", exact: true }).click();
  const directoryPicker = page.getByRole("dialog", {
    name: "Select directory",
    exact: true
  });
  await expect(directoryPicker).toBeVisible();
  await expect(directoryPicker.getByLabel("Directory", { exact: true })).toHaveValue(
    "/remote/home/czhu"
  );
  await directoryPicker
    .getByLabel("Directory", { exact: true })
    .fill("/scratch/projects");
  await expect(
    page.getByRole("button", { name: "Use this directory", exact: true })
  ).toBeDisabled();
  await page.getByRole("button", { name: "Go", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Use this directory", exact: true })
  ).toBeEnabled();
  await page.getByRole("button", { name: "Use this directory", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Directory", { exact: true })).toHaveValue(
    "/scratch/projects"
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Saved: /scratch/projects/session.json", { exact: true })
  ).toBeVisible();
  const original = serverFiles.get("/scratch/projects/session.json");
  assert.equal(JSON.parse(original).name, "Remote analysis");
  assert.equal(saves[0].overwrite, false);
  assert.deepEqual(
    saves[0].project.acquisitions.map((row) => row.id),
    ["fraction_01", "fraction_02"]
  );
  assert.ok(saves[0].project.acquisitions.every((row) => !("identifications" in row)));
  assert.deepEqual(
    saves[0].project.samples[0].identifications.map((row) => row.name),
    ["Search", "Validated"]
  );
  assert.deepEqual(downloads, []);

  // Existing files remain untouched until the user explicitly chooses replacement.
  await page.getByLabel("Project name", { exact: true }).fill("Updated remote analysis");
  await page.getByRole("button", { name: "Save JSON", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Replace file", exact: true })
  ).toBeVisible();
  assert.equal(serverFiles.get("/scratch/projects/session.json"), original);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).not.toBeVisible();

  await page.getByRole("button", { name: "Save JSON", exact: true }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Replace file", exact: true })
  ).toBeVisible();
  await page.getByLabel("File name", { exact: true }).fill("other.json");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Saved: /scratch/projects/other.json", { exact: true })
  ).toBeVisible();
  assert.equal(saves.at(-1).overwrite, false);
  assert.equal(serverFiles.get("/scratch/projects/session.json"), original);

  await page.getByRole("button", { name: "Save JSON", exact: true }).click();
  await page.getByLabel("File name", { exact: true }).fill("session.json");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Replace file", exact: true }).click();
  await expect(
    page.getByText("Saved: /scratch/projects/session.json", { exact: true })
  ).toBeVisible();
  assert.equal(saves.at(-1).overwrite, true);
  assert.equal(
    JSON.parse(serverFiles.get("/scratch/projects/session.json")).name,
    "Updated remote analysis"
  );

  await page.getByRole("button", { name: "Save JSON", exact: true }).click();
  await dialog.getByLabel("Directory", { exact: true }).fill("/denied");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toContainText("Permission denied on server");
  await dialog.getByLabel("Directory", { exact: true }).fill("/scratch/projects");
  await dialog.screenshot({ path: "/private/tmp/mzloupe-save-server-dialog.png" });
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  assert.ok(!requests.includes("/api/open-configuration"));
  assert.ok(!requests.includes("/api/open"));
  assert.deepEqual(downloads, []);
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify({
      savedPaths: [...serverFiles.keys()],
      saveAttempts: saves.length,
      downloads,
      pageErrors: errors
    })
  );
} finally {
  await browser.close();
}
