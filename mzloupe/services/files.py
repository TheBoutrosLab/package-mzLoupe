"""Browse source files on the machine running the local application."""

from pathlib import Path
from typing import Any


class FileBrowser:
    """List supported source files and navigable directories for project setup."""

    extensions = {
        "mzml": (".mzml", ".mzml.gz"),
        "idxml": (".idxml",),
        "json": (".json",),
        "directory": (),
    }

    def list_directory(self, path: str | None, kind: str) -> dict[str, Any]:
        """Return up to 1000 visible entries, filtering files by the requested kind."""
        if kind not in self.extensions:
            raise ValueError("Choose mzml, idxml, json, or directory entries")
        directory = Path(path).expanduser().resolve() if path else Path.home()
        if not directory.is_dir():
            raise ValueError(f"Directory does not exist: {directory}")
        try:
            sorted_entries = sorted(
                directory.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
            entries = [
                {"name": entry.name, "path": str(entry), "directory": entry.is_dir()}
                for entry in sorted_entries
                if not entry.name.startswith(".")
                and (entry.is_dir() or entry.name.lower().endswith(self.extensions[kind]))
            ]
        except PermissionError as error:
            raise ValueError(f"Cannot read directory: {directory}") from error
        return {
            "directory": str(directory),
            "parent": str(directory.parent),
            "entries": entries[:1000],
            "truncated": len(entries) > 1000,
        }
