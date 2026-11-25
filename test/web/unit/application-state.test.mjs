import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../../../web/package.json", import.meta.url));
const ts = require("typescript");

/** Compile the real pure models without loading a browser or React application. */
function moduleUrl(source) {
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  return "data:text/javascript;base64," + Buffer.from(compiled).toString("base64");
}

const draftUrl = moduleUrl(
  await readFile(new URL("../../../web/src/ProjectDraft.ts", import.meta.url), "utf8")
);
const { ProjectDraft } = await import(draftUrl);
const applicationSource = await readFile(
  new URL("../../../web/src/ApplicationModel.ts", import.meta.url),
  "utf8"
);
const { ApplicationModel } = await import(
  moduleUrl(applicationSource.replace('"./ProjectDraft"', JSON.stringify(draftUrl)))
);

test("ordinary edits retain project identity and drafts remain dirty across library navigation", () => {
  let state = ApplicationModel.reduce(ApplicationModel.initial(), { type: "new" });
  const identifier = state.draft.id;
  const draft = state.draft
    .withName("Edited study")
    .addAcquisitions(["/data/fraction.mzML"], "Sample 1");
  assert.equal(draft.id, identifier);
  state = ApplicationModel.reduce(state, { type: "draft", draft });
  assert.equal(ApplicationModel.hasUnsavedChanges(state), true);
  state = ApplicationModel.reduce(state, { type: "navigate", view: "library" });
  assert.equal(state.draft, draft);
  assert.equal(ApplicationModel.hasUnsavedChanges(state), true);
  const another = ApplicationModel.reduce(state, { type: "new" });
  assert.notEqual(another.draft.id, identifier);
  assert.equal(ApplicationModel.hasUnsavedChanges(another), false);
});

test("saving establishes a clean baseline under the registered identity", () => {
  let state = ApplicationModel.reduce(ApplicationModel.initial(), { type: "new" });
  const draft = state.draft.withName("Saved study");
  state = ApplicationModel.reduce(state, { type: "draft", draft });
  state = ApplicationModel.reduce(state, {
    type: "saved",
    project: { configuration: draft.toConfiguration() }
  });
  assert.equal(state.draft.id, draft.id);
  assert.equal(state.registered, true);
  assert.equal(ApplicationModel.hasUnsavedChanges(state), false);
  assert.equal(state.view, "setup");
});

test("status polling cannot replace a draft or override explicit project navigation", () => {
  let state = ApplicationModel.reduce(ApplicationModel.initial(), { type: "new" });
  const draft = state.draft.withName("Unsaved project");
  state = ApplicationModel.reduce(state, { type: "draft", draft });
  state = ApplicationModel.reduce(state, {
    type: "status",
    status: {
      state: "ready",
      token: "other-project",
      message: "Another study",
      progress: 1
    }
  });
  assert.equal(state.draft, draft);
  assert.equal(state.view, "setup");
  assert.equal(ApplicationModel.hasUnsavedChanges(state), true);
  const restored = ProjectDraft.fromConfiguration(draft.toConfiguration());
  assert.equal(restored.withName("Renamed again").id, draft.id);
});
