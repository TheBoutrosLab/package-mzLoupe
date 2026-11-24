import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

/** Complete and validate Vite's report using reviewed notices omitted from npm. */
export class BundledLicenses {
  static report = new URL(
    "../../mzloupe/static/assets/THIRD_PARTY_NOTICES.txt",
    import.meta.url
  );

  // The version is deliberate: review the upstream notice when this package changes.
  // Source: https://github.com/theKashey/react-remove-scroll-bar/blob/master/LICENSE
  static supplements = new Map([
    [
      "react-remove-scroll-bar - 2.3.8 (MIT)",
      new URL("../licenses/react-remove-scroll-bar-LICENSE.txt", import.meta.url)
    ]
  ]);

  /** Preserve collected texts and reject dependencies without a complete notice. */
  static complete(report) {
    const [introduction, ...sections] = report.split("\n## ");
    if (!sections.length)
      throw new Error("The bundled dependency license report is empty.");

    const completed = sections.map((section) => {
      const newline = section.indexOf("\n");
      const header = newline < 0 ? section : section.slice(0, newline);
      const text = newline < 0 ? "" : section.slice(newline + 1).trim();
      if (text) return section;

      const supplement = this.supplements.get(header);
      if (!supplement) {
        throw new Error(`Missing bundled license text: ${header}`);
      }
      return `${header}\n\n${readFileSync(supplement, "utf8").trim()}\n`;
    });
    return [introduction, ...completed].join("\n## ");
  }

  /** Complete the generated asset before packaging the compiled dashboard. */
  static write() {
    const original = readFileSync(this.report, "utf8");
    writeFileSync(this.report, this.complete(original));
  }
}

// Allow unit tests to import the validator without writing a build artifact.
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  BundledLicenses.write();
}
