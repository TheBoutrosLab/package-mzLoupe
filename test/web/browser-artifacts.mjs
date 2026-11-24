import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

/** Store browser diagnostics in a portable local directory or CI's artifact directory. */
export class BrowserArtifacts {
  /** Resolve a screenshot filename without relying on a platform-specific temporary path. */
  static path(filename) {
    const directory =
      process.env.MZLOUPE_TEST_ARTIFACTS || path.join(tmpdir(), "mzloupe-browser-tests");
    mkdirSync(directory, { recursive: true });
    return path.join(directory, filename);
  }

  /** Capture open pages on failure without hiding the original test error. */
  static async captureFailure(browser, name) {
    const pages = browser?.contexts().flatMap((context) => context.pages()) || [];
    for (const [index, page] of pages.entries()) {
      if (page.isClosed()) continue;
      try {
        await page.screenshot({
          path: this.path(`${name}-failure-${index + 1}.png`),
          fullPage: true,
          timeout: 5000
        });
      } catch (error) {
        console.warn(`Could not capture ${name} failure screenshot: ${error.message}`);
      }
    }
  }
}
