"""Save project configurations on the machine running mzLoupe."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from mzloupe.models import ProjectInput


class ProjectFiles:
    """Validate destinations and publish complete project JSON files."""

    @staticmethod
    def destination(directory: str, filename: str) -> Path:
        """Resolve an existing directory and require a plain JSON filename."""
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).suffix.lower() != ".json"
        ):
            raise ValueError("Enter a .json filename without directory separators")
        folder = Path(directory).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"Directory does not exist: {folder}")
        destination = folder / filename
        if destination.is_dir():
            raise ValueError(f"The destination is a directory: {destination}")
        return destination

    @classmethod
    def save(
        cls,
        project: ProjectInput,
        *,
        directory: str,
        filename: str,
        overwrite: bool = False,
    ) -> Path:
        """Save a draft without activating it or reading mzML/idXML contents.

        Resolve source paths against the server's working directory, matching
        the editor's Open project behavior. Saved manifests remain usable when
        written into another directory, including drafts with missing sources.
        """
        try:
            destination = cls.destination(directory, filename)
            normalized = project.model_copy(deep=True).resolve_paths(
                Path.cwd(),
                validate_files=False,
            )
            cls.write(
                path=destination,
                content=normalized.model_dump_json(indent=2) + "\n",
                overwrite=overwrite,
            )
        except FileExistsError:
            raise
        except OSError as error:
            raise ValueError(f"Could not save project JSON: {error}") from error
        return destination

    @staticmethod
    def write(path: Path, content: str, overwrite: bool) -> None:
        """Publish a complete file atomically and remove temporary files on failure."""
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".mzloupe-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # A hard link publishes the completed file without overwriting a
                # destination created by another process during this save.
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
