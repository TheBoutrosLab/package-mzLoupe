"""Guard project cache writes and cleanup against path traversal and symlink escapes."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from mzloupe.services.project_cache import ProjectCache


@pytest.mark.parametrize("component", ["projects", "project"])
@pytest.mark.parametrize("operation", ["acquire", "stage", "clear", "prune"])
def test_cache_operations_reject_symlinked_directories(
    tmp_path: Path, component: str, operation: str
) -> None:
    """Every mutation rejects directory links and preserves an external sentinel file."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    protected = tmp_path / "protected"
    protected.mkdir()
    sentinel = protected / "keep.txt"
    sentinel.write_text("Original data")
    link = cache.root.parent if component == "projects" else cache.root
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(protected, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        getattr(cache, operation)()
    assert sentinel.read_text() == "Original data"
    assert link.is_symlink()


def test_cache_cannot_alias_another_project_inside_the_same_root(tmp_path: Path) -> None:
    """A project must not clear another project's cache even when both are inside the root."""
    cache = ProjectCache(tmp_path, str(uuid4()), 6)
    other = ProjectCache(tmp_path, str(uuid4()), 6)
    other.root.mkdir(parents=True)
    sentinel = other.root / "keep.txt"
    sentinel.write_text("Other project")
    cache.root.symlink_to(other.root, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        cache.clear()
    assert sentinel.read_text() == "Other project"


def test_cached_lease_does_not_bypass_later_path_checks(tmp_path: Path) -> None:
    """Replacing a project directory after acquiring its lease cannot redirect cleanup."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    cache.acquire()
    protected = tmp_path / "protected"
    protected.mkdir()
    try:
        cache.root.symlink_to(protected, target_is_directory=True)
        with pytest.raises(ValueError, match="without symlinks"):
            cache.clear()
        assert protected.is_dir()
    finally:
        cache.release()


@pytest.mark.parametrize("operation", ["publish", "discard"])
def test_revision_operations_reject_foreign_workspaces(tmp_path: Path, operation: str) -> None:
    """Preparation never publishes into or removes an unrelated revision directory."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    protected = tmp_path / "revision-unrelated"
    protected.mkdir()
    sentinel = protected / "keep.txt"
    sentinel.write_text("Original data")
    with pytest.raises(ValueError, match="revision directory"):
        if operation == "publish":
            cache.publish(protected, {})
        else:
            cache.discard(protected)
    assert list(protected.iterdir()) == [sentinel]


def test_pruning_rejects_a_symlinked_revision(tmp_path: Path) -> None:
    """Snapshot cleanup cannot follow a revision link outside the project directory."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    cache.root.mkdir(parents=True)
    protected = tmp_path / "protected"
    protected.mkdir()
    sentinel = protected / "keep.txt"
    sentinel.write_text("Original data")
    link = cache.root / "revision-redirected"
    link.symlink_to(protected, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        cache.prune()
    assert sentinel.read_text() == "Original data"
    assert link.is_symlink()


@pytest.mark.parametrize("filename", ["current.pending", "prepared.pending"])
def test_publishing_rejects_symlinked_control_files(tmp_path: Path, filename: str) -> None:
    """Writing completion manifests must not overwrite a symlink's external target."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    workspace = cache.stage()
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("Original data")
    parent = cache.root if filename == "current.pending" else workspace
    (parent / filename).symlink_to(sentinel)
    with pytest.raises(ValueError, match="without symlinks"):
        cache.publish(workspace, {})
    assert sentinel.read_text() == "Original data"


def test_lock_file_cannot_redirect_to_an_external_file(tmp_path: Path) -> None:
    """Opening the cache lease must not follow an external file symlink."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    cache.root.parent.mkdir(parents=True)
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("Original data")
    (cache.root.parent / ("." + cache.root.name + ".lock")).symlink_to(sentinel)
    with pytest.raises(ValueError, match="lock must not follow"):
        cache.acquire()
    assert sentinel.read_text() == "Original data"


@pytest.mark.parametrize("identifier", ["..", "../outside", "/tmp/outside", "-" * 36])
def test_project_identity_cannot_be_used_as_a_path(tmp_path: Path, identifier: str) -> None:
    """Reject invalid registry identities before creating or deleting directories."""
    with pytest.raises(ValueError):
        ProjectCache(tmp_path, identifier, 6)
    assert not list(tmp_path.iterdir())


def test_current_revision_does_not_follow_an_external_snapshot(tmp_path: Path) -> None:
    """External revision links cannot advertise a usable cache in the library."""
    cache = ProjectCache(tmp_path / "cache", str(uuid4()), 6)
    cache.root.mkdir(parents=True)
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "catalog.sqlite").touch()
    (protected / "prepared.json").write_text(json.dumps({"version": 6}))
    (cache.root / "revision-external").symlink_to(protected, target_is_directory=True)
    (cache.root / "current.json").write_text(
        json.dumps(
            {"workspace": "revision-external", "outputs": ["catalog.sqlite", "prepared.json"]}
        )
    )
    assert cache.current() is None
