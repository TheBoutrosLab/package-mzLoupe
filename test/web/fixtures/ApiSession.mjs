import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

/** Own a real FastAPI test client over pipes, including deterministic worker cleanup. */
export class ApiSession {
  static root = fileURLToPath(new URL("../../../", import.meta.url));

  /** Start one isolated backend worker and expose its readiness separately from requests. */
  constructor(script) {
    const python = process.env.MZLOUPE_TEST_PYTHON || "python3";
    this.waiting = new Map();
    this.serial = 0;
    this.error = "";
    this.worker = spawn(python, [path.join(ApiSession.root, "test/python", script)], {
      cwd: ApiSession.root,
      env: { ...process.env, PYTHONPATH: ApiSession.root },
      stdio: ["pipe", "pipe", "pipe"]
    });
    this.ready = new Promise((resolve, reject) => {
      this.worker.on("error", reject);
      this.worker.stderr.on("data", (data) => {
        this.error += data;
      });
      this.lines = createInterface({ input: this.worker.stdout });
      this.lines.on("line", (line) => {
        if (line === "MZLOUPE_READY") resolve();
        if (line.startsWith("MZLOUPE_RESPONSE ")) {
          const response = JSON.parse(line.slice("MZLOUPE_RESPONSE ".length));
          this.waiting.get(response.id)?.resolve(response);
          this.waiting.delete(response.id);
        }
      });
      this.worker.on("exit", (code) => {
        const failure = new Error(`ASGI worker exited (${code}): ${this.error}`);
        reject(failure);
        for (const request of this.waiting.values()) request.reject(failure);
      });
    });
    this.exited = new Promise((resolve) => this.worker.once("close", resolve));
  }

  /** Send one API operation without creating a listening socket or remote connection. */
  request(request) {
    const id = this.serial++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      this.worker.stdin.write(JSON.stringify({ id, ...request }) + "\n");
    });
  }

  /** Fulfill browser API and compiled-asset requests from this fixture's local worker. */
  async route(page, origin = "https://mzloupe.test") {
    const mime = {
      ".html": "text/html",
      ".js": "text/javascript",
      ".css": "text/css",
      ".svg": "image/svg+xml"
    };
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin) return route.abort();
      if (url.pathname.startsWith("/api/")) {
        const response = await this.request({
          method: request.method(),
          url: url.pathname + url.search,
          body: request.postDataJSON()
        });
        return route.fulfill({ status: response.status, json: response.body });
      }
      const filename = path.join(
        ApiSession.root,
        "mzloupe/static",
        url.pathname === "/" ? "index.html" : url.pathname
      );
      return route.fulfill({
        body: await readFile(filename),
        contentType: mime[path.extname(filename)]
      });
    });
  }

  /** Close the input pipe and wait for backend resources to be released before finishing. */
  async close() {
    this.worker.stdin.end();
    const timeout = setTimeout(() => this.worker.kill(), 5000);
    await this.exited;
    clearTimeout(timeout);
    this.lines.close();
  }
}
