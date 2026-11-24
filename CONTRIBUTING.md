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
  mzloupe/storage/*.py
pyright --pythonpath .venv/bin/python mzloupe
pytest
```


## Release versions

`pyproject.toml` is the source of truth for the application version. The
**Prepare new release** workflow uses the lab's release tools to bump that
version, synchronize the frontend manifest and lockfile, and include all changes
in one release PR. The first release is created manually. Subsequent releases
can use `major`, `minor`, or `patch`.

Regular PRs should not bump package versions. Check that the package metadata
agrees with:

```sh
python scripts/sync_versions.py --check
```

After intentionally changing `project.version`, synchronize the frontend with:

```sh
python scripts/sync_versions.py
```

The script preserves JSON formatting and dependency versions. It needs only
Python 3.11 or newer; Node and an installed mzLoupe package are not required.
The database/cache format version is independent of the release version.
