"""Check release synchronization without installing Node or touching repository metadata."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_versions.py"


@pytest.fixture(name="checkout")
def metadata_checkout(tmp_path: Path) -> Path:
    """Create package metadata with dependency versions and intentional JSON formatting."""
    (tmp_path / "web").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mzloupe"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "web/package.json").write_text(
        '{\n    "name": "mzloupe-web",\n    "version" : "0.1.0",\n'
        '    "files": [\n        "α",\n        "β"\n    ],\n'
        '    "dependencies": { "example": "0.1.0" }\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "web/package-lock.json").write_bytes(
        b'{\r\n  "version": "0.1.0",\r\n  "lockfileVersion": 3,\r\n'
        b'  "packages": {\r\n    "node_modules/example": { "version": "0.1.0" },\r\n'
        b'    "": { "version": "0.1.0", "name": "mzloupe-web" }\r\n  }\r\n}\r\n'
    )
    return tmp_path


def run_sync(checkout: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the real command from outside its checkout, capturing help and error messages."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(checkout), *arguments],
        cwd=checkout.parent,
        capture_output=True,
        text=True,
        check=False,
    )


def metadata_bytes(checkout: Path) -> dict[str, bytes]:
    """Snapshot all release metadata so read-only checks can prove they changed nothing."""
    return {
        relative: (checkout / relative).read_bytes()
        for relative in ("pyproject.toml", "web/package.json", "web/package-lock.json")
    }


@pytest.mark.parametrize("version", ["0.2.0", "1.0.0-rc.1"])
def test_sync_preserves_dependencies_formatting_and_python_version(
    checkout: Path,
    version: str,
) -> None:
    """Update only the package's three version values, including prerelease strings."""
    project = checkout / "pyproject.toml"
    project.write_text(f'[project]\nname = "mzloupe"\nversion = "{version}"\n')
    original = metadata_bytes(checkout)

    result = run_sync(checkout)

    assert result.returncode == 0, result.stderr
    expected = dict(original)
    expected["web/package.json"] = original["web/package.json"].replace(
        b'"version" : "0.1.0"',
        f'"version" : "{version}"'.encode(),
    )
    expected["web/package-lock.json"] = (
        original["web/package-lock.json"]
        .replace(
            b'  "version": "0.1.0"',
            f'  "version": "{version}"'.encode(),
            1,
        )
        .replace(
            b'"": { "version": "0.1.0"',
            f'"": {{ "version": "{version}"'.encode(),
            1,
        )
    )
    assert metadata_bytes(checkout) == expected
    assert run_sync(checkout, "--check").returncode == 0

    # An already synchronized checkout must not even rewrite metadata files.
    modified_times = {path: path.stat().st_mtime_ns for path in checkout.rglob("*.json")}
    assert run_sync(checkout).returncode == 0
    assert all(path.stat().st_mtime_ns == timestamp for path, timestamp in modified_times.items())


@pytest.mark.parametrize("field", ["manifest", "lockfile", "root_package"])
def test_check_detects_each_version_field_without_writing(checkout: Path, field: str) -> None:
    """Reject an isolated mismatch in any of the three fields checked by release CI."""
    assert run_sync(checkout).returncode == 0
    path = checkout / ("web/package.json" if field == "manifest" else "web/package-lock.json")
    metadata = json.loads(path.read_text())
    target = metadata["packages"][""] if field == "root_package" else metadata
    target["version"] = "0.0.0"
    path.write_text(json.dumps(metadata, indent=4) + "\n", encoding="utf-8")
    original = metadata_bytes(checkout)

    result = run_sync(checkout, "--check")

    assert result.returncode == 1
    assert str(path.relative_to(checkout)) in result.stdout
    assert "0.2.0" in result.stdout
    assert metadata_bytes(checkout) == original


@pytest.mark.parametrize(
    "invalid_lockfile",
    [
        '{"version": "0.1.0", "packages": {}}',
        '{"version": "0.1.0", "packages": {"": {"version": 123}}}',
        '{"version": "0.1.0", "packages": {"": "unexpected string"}}',
        '{"version": "0.1.0", "packages": ',
    ],
)
def test_invalid_lockfile_does_not_partially_update_manifest(
    checkout: Path,
    invalid_lockfile: str,
) -> None:
    """Validate both files before writing so a malformed lockfile leaves metadata intact."""
    (checkout / "web/package-lock.json").write_text(invalid_lockfile, encoding="utf-8")
    original = metadata_bytes(checkout)

    result = run_sync(checkout)

    assert result.returncode == 2
    assert "Version synchronization failed" in result.stderr
    assert metadata_bytes(checkout) == original


def test_cli_help_explains_check_and_checkout_options(checkout: Path) -> None:
    """Keep the release maintenance command discoverable without importing application code."""
    result = run_sync(checkout, "--help")
    assert result.returncode == 0
    assert "pyproject.toml" in result.stdout
    assert "--check" in result.stdout
    assert "--root" in result.stdout
