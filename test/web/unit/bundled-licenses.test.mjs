import assert from "node:assert/strict";
import test from "node:test";
import { BundledLicenses } from "../../../web/scripts/BundledLicenses.mjs";

test("collected dependency notices remain unchanged", () => {
  const report =
    "# Licenses\n\n## example - 1.0.0 (MIT)\n\nCopyright holder and full notice.\n";
  assert.equal(BundledLicenses.complete(report), report);
});

test("the reviewed upstream notice fills the omitted npm license", () => {
  const report = "# Licenses\n\n## react-remove-scroll-bar - 2.3.8 (MIT)\n";
  const completed = BundledLicenses.complete(report);
  assert.match(completed, /Copyright \(c\) 2025 Anton Korzunov/);
  assert.match(completed, /Permission is hereby granted/);
  assert.match(completed, /THE SOFTWARE IS PROVIDED/);
  assert.equal(BundledLicenses.complete(completed), completed);
});

test("missing notices and unreviewed package versions stop the build", () => {
  for (const header of [
    "unknown - 1.0.0 (MIT)",
    "react-remove-scroll-bar - 2.3.9 (MIT)"
  ]) {
    assert.throws(
      () => BundledLicenses.complete(`# Licenses\n\n## ${header}\n`),
      /Missing bundled license text/
    );
  }
  assert.throws(() => BundledLicenses.complete("# Licenses\n"), /report is empty/);
});
