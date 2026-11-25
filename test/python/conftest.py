"""Isolate project libraries from the user's saved projects during tests."""

from pathlib import Path

import pytest

from mzloupe.storage.registry import ProjectRegistry


@pytest.fixture(autouse=True)
def isolated_project_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep registry persistence inside the test workspace, outside each cache directory."""
    monkeypatch.setattr(
        ProjectRegistry, "default_path", staticmethod(lambda: tmp_path / "projects.sqlite")
    )
