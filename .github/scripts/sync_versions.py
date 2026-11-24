"""Synchronize frontend package versions with the Python project's release version."""

import argparse
import json
from pathlib import Path
import tomllib


def skip_whitespace(text: str, position: int) -> int:
    """Return the next non-whitespace position in an already validated JSON document."""
    while text[position].isspace():
        position += 1
    return position


def json_member_span(text: str, keys: tuple[str, ...], start: int = 0) -> tuple[int, int]:
    """Locate a nested object member's value so its surrounding formatting stays intact."""
    start = skip_whitespace(text, start)
    if text[start] != "{":
        raise ValueError(f"Expected a JSON object while locating {keys!r}")

    decoder = json.JSONDecoder()
    cursor = start + 1
    while True:
        cursor = skip_whitespace(text, cursor)
        if text[cursor] == "}":
            raise ValueError(f"Missing JSON version field: {keys!r}")

        key, cursor = decoder.raw_decode(text, cursor)
        colon = skip_whitespace(text, cursor)
        value_start = skip_whitespace(text, colon + 1)
        _, value_stop = decoder.raw_decode(text, value_start)
        if key == keys[0]:
            if len(keys) == 1:
                return value_start, value_stop
            return json_member_span(text, keys[1:], value_start)

        cursor = skip_whitespace(text, value_stop)
        if text[cursor] == ",":
            cursor += 1


class VersionSynchronizer:
    """Plan and apply frontend version updates without changing dependency metadata."""

    version_fields = {
        "web/package.json": (("version",),),
        "web/package-lock.json": (("version",), ("packages", "", "version")),
    }

    def __init__(self, root: Path) -> None:
        """Read the authoritative release version from this checkout's pyproject.toml."""
        self.root = root.resolve()
        with (self.root / "pyproject.toml").open("rb") as source:
            self.version = tomllib.load(source)["project"]["version"]
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("pyproject.toml must define a nonempty project.version string")

    def updated_text(self, text: str, fields: tuple[tuple[str, ...], ...]) -> str:
        """Replace only the declared version strings in a valid JSON document."""
        json.loads(text)
        for keys in fields:
            start, stop = json_member_span(text, keys)
            if not isinstance(json.loads(text[start:stop]), str):
                raise ValueError(f"JSON version field must contain a string: {keys!r}")
            text = text[:start] + json.dumps(self.version) + text[stop:]
        return text

    def changes(self) -> dict[Path, str]:
        """Validate both frontend files and collect their changes before writing either."""
        updates = {}
        for relative_path, fields in self.version_fields.items():
            path = self.root / relative_path
            original = path.read_bytes().decode("utf-8")
            updated = self.updated_text(original, fields)
            if updated != original:
                updates[path] = updated
        return updates

    def synchronize(self, *, check: bool = False) -> list[Path]:
        """Return mismatched files, updating them unless this is a read-only check."""
        updates = self.changes()
        if not check:
            for path, text in updates.items():
                path.write_bytes(text.encode("utf-8"))
        return list(updates)


def main() -> int:
    """Synchronize a checkout or report version mismatches with a nonzero exit status."""
    parser = argparse.ArgumentParser(
        description="Copy project.version from pyproject.toml into frontend package metadata.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Checkout directory containing pyproject.toml (default: this script's checkout).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report mismatches and exit with status 1 without changing any files.",
    )
    args = parser.parse_args()
    try:
        versions = VersionSynchronizer(args.root)
        changed = versions.synchronize(check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Version synchronization failed: {error}\n")

    if not changed:
        print(f"All package versions match {versions.version}.")
        return 0

    action = "Version mismatch" if args.check else "Updated"
    for path in changed:
        print(f"{action}: {path.relative_to(versions.root)} (expected {versions.version})")
    if args.check:
        print("Run python .github/scripts/sync_versions.py to synchronize versions.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
