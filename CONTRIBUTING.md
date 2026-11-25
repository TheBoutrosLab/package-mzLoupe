# Contribution Guidelines

Create a new pull request with an explanation of what the PR is fixing.


## Python readability

- Document modules, classes, constructors, and public functions/methods. Explain
  their responsibilities and any scientific units or provenance rules.
- Keep short, obvious calls such as `value.replace("\\", "/")` on one line.
  For longer calls, normally put each argument on its own line when that
  improves readability. Keep function definitions on one line when they fit
  within the 100-character limit; use one parameter per line for longer
  signatures. Choose line breaks for clarity rather than mechanically.
- Keep short loop and condition headers on one line when they fit. Keep lines
  within the 100-character limit configured in `.pylintrc`.
- Separate loading, source resolution, scientific conversion, and persistence
  into clearly named public methods with a straightforward dependency flow.
- Use classes to group related responsibilities; use functions when a class
  adds no useful organization. Use private helpers only when necessary.
- Resolve lint findings in the code. Pylint uses the type stubs supplied
  with native dependencies; keep member checks enabled.

Check every backend module with:

```sh
pylint --source-roots=. mzloupe/*.py \
  mzloupe/readers/*.py mzloupe/services/*.py \
  mzloupe/storage/*.py mzloupe/routers/*.py
pyright --pythonpath .venv/bin/python mzloupe
pytest
```


## Frontend checks

The frontend workflow runs on pull requests to `main` and pushes to `main`.
From `web/`, run `npm test` to execute unit tests, build the dashboard, and run
all browser tests. For a focused run, use `npm run test:unit` or
`npm run test:browser`; the browser suite needs an existing frontend build.

Both suites use Node's test runner and `.test.mjs` filenames. Unit tests live in
`test/web/unit/`, browser tests in `test/web/browser/`, and shared fixtures and
browser helpers stay outside those directories.

Install Chromium with `npx playwright install chromium` before running browser
tests. The PSM browser test also needs mzLoupe's Python development dependencies;
set `MZLOUPE_TEST_PYTHON` if they are installed in a different Python environment.
Browser tests run sequentially and require no running dashboard server.

Screenshots use the system temporary directory locally. Set
`MZLOUPE_TEST_ARTIFACTS` to choose another output directory; CI uses
`test-results/frontend` and uploads screenshots when the test job fails.


## Project lifecycle checks

Use temporary registries and caches in tests. `test/python/conftest.py` isolates the
user's project library, and the browser workers supply explicit temporary registry
paths. The project-library browser test uses the real API over pipes, without
starting a dashboard server.

## Release versions

`pyproject.toml` is the source of truth for the application version. The
**Prepare new release** workflow uses the lab's release tools to bump that
version, synchronize the frontend manifest and lockfile, and include all changes
in one release PR. The first release is created manually. Subsequent releases
can use `major`, `minor`, or `patch`.

Regular PRs should not bump package versions. Check that the package metadata
agrees with:

```sh
python .github/scripts/sync_versions.py --check
```

After intentionally changing `project.version`, synchronize the frontend with:

```sh
python .github/scripts/sync_versions.py
```

The script preserves JSON formatting and dependency versions. It needs only
Python 3.11 or newer; Node and an installed mzLoupe package are not required.
The database/cache format version is independent of the release version.

## API organization

HTTP endpoints live in `mzloupe/routers/`. Each route group is a class with public
handler methods and an `APIRouter`. Its constructor receives the runtime or assets
it needs; `register(app)` declares its endpoints and includes the router.
`mzloupe/app.py` composes these groups and manages application lifetime. Keep
preparation, signal processing, and storage logic in their existing services.
