import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { BrowserArtifacts } from "../browser-artifacts.mjs";

test("Request cancellation rejects stale responses and survives consumer remounts", async () => {
  const require = createRequire(new URL("../../../web/package.json", import.meta.url));
  const { chromium, expect } = require("@playwright/test");
  const { build } = await import(require.resolve("vite"));
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const web = path.join(root, "web");
  // Compile the real hook into an isolated consumer without writing application assets.
  const built = await build({
    configFile: false,
    root: web,
    logLevel: "silent",
    define: { "process.env.NODE_ENV": JSON.stringify("development") },
    resolve: {
      alias: {
        react: path.join(web, "node_modules/react"),
        "react-dom": path.join(web, "node_modules/react-dom")
      }
    },
    build: {
      write: false,
      minify: false,
      lib: {
        entry: fileURLToPath(new URL("../fixtures/RequestHarness.tsx", import.meta.url)),
        name: "RequestHarness",
        formats: ["iife"]
      }
    }
  });
  const outputs = Array.isArray(built) ? built : [built];
  const script = outputs
    .flatMap((output) => output.output)
    .find((item) => item.type === "chunk").code;
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("https://mzloupe.test/**", (route) => {
      if (new URL(route.request().url()).pathname === "/harness.js") {
        return route.fulfill({ contentType: "text/javascript", body: script });
      }
      return route.fulfill({
        contentType: "text/html",
        body: '<div id="root"></div><script src="/harness.js"></script>'
      });
    });
    await page.goto("https://mzloupe.test");
    await page.waitForFunction(() =>
      window.requests?.some((item) => item.url === "first" && !item.signal.aborted)
    );
    await expect
      .poll(() =>
        page.evaluate(() => window.requests.filter((item) => item.url === "first").length)
      )
      .toBe(2);
    await page.getByRole("button", { name: "second", exact: true }).click();
    await page.waitForFunction(() =>
      window.requests.some((item) => item.url === "second")
    );
    assert.equal(
      await page.evaluate(() =>
        window.requests
          .filter((item) => item.url === "first")
          .every((item) => item.signal.aborted)
      ),
      true
    );
    await page.evaluate(() =>
      window.requests
        .filter((item) => item.url === "first")
        .forEach((item) => item.resolve({ name: "obsolete" }))
    );
    await expect(page.getByTestId("result")).toHaveText("");
    await expect(page.getByTestId("loading")).toHaveText("true");

    await page.getByRole("button", { name: "third", exact: true }).click();
    await page.waitForFunction(() =>
      window.requests.some((item) => item.url === "third")
    );
    await page.evaluate(() =>
      window.requests
        .find((item) => item.url === "second")
        .reject(new Error("late failure"))
    );
    await expect(page.getByTestId("error")).toHaveText("");
    await expect(page.getByTestId("loading")).toHaveText("true");
    await page.evaluate(() =>
      window.requests.find((item) => item.url === "third").resolve({ name: "current" })
    );
    await expect(page.getByTestId("result")).toHaveText("current");
    await expect(page.getByTestId("loading")).toHaveText("false");

    await page.getByRole("button", { name: "fourth", exact: true }).click();
    await page.waitForFunction(() =>
      window.requests.some((item) => item.url === "fourth")
    );
    await page.evaluate(() =>
      window.requests
        .find((item) => item.url === "fourth")
        .reject(new Error("server error"))
    );
    await expect(page.getByTestId("error")).toHaveText("server error");
    await expect(page.getByTestId("loading")).toHaveText("false");

    await page.getByRole("button", { name: "fifth", exact: true }).click();
    await page.waitForFunction(() =>
      window.requests.some((item) => item.url === "fifth")
    );
    await page.getByRole("button", { name: "Toggle consumer", exact: true }).click();
    assert.equal(
      await page.evaluate(() =>
        window.requests
          .filter((item) => item.url === "fifth")
          .every((item) => item.signal.aborted)
      ),
      true
    );
    await page.evaluate(() =>
      window.requests
        .filter((item) => item.url === "fifth")
        .forEach((item) => item.resolve({ name: "unmounted" }))
    );
    assert.deepEqual(await page.evaluate(() => window.successes), ["current"]);
    await page.getByRole("button", { name: "Toggle consumer", exact: true }).click();
    await page.waitForFunction(() =>
      window.requests.some((item) => item.url === "fifth" && !item.signal.aborted)
    );
    await page.evaluate(() =>
      window.requests
        .find((item) => item.url === "fifth" && !item.signal.aborted)
        .resolve({ name: "remounted" })
    );
    await expect(page.getByTestId("result")).toHaveText("remounted");
    assert.deepEqual(await page.evaluate(() => window.successes), [
      "current",
      "remounted"
    ]);
    assert.deepEqual(errors, []);
    console.log(
      "Request aborts, late responses/errors, loading state, and consumer unmount/remount passed."
    );
  } catch (error) {
    await BrowserArtifacts.captureFailure(browser, "request-cancellation");
    throw error;
  } finally {
    await browser.close();
  }
});
