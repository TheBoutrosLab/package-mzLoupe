"""In-memory reservations for project mutations and preparation."""

from typing import Literal

ProjectOperation = Literal["preparing", "saving", "clearing", "deleting", "closing"]


class ProjectOperations:
    """Prevent conflicting project operations without holding locks during disk work.

    The runtime holds its state lock while reading or changing these reservations.
    This class performs no filesystem access and does not own cache file leases.
    """

    def __init__(self) -> None:
        """Start with no operations in progress and accept new work."""
        self.projects: dict[str, ProjectOperation] = {}
        self.stopped = False

    def reserve(
        self,
        identifier: str,
        operation: ProjectOperation,
        *,
        active: str | None = None,
    ) -> None:
        """Reserve one project and serialize preparation without blocking other projects."""
        if self.stopped:
            raise ValueError("mzLoupe is shutting down")
        current = self.projects.get(identifier)
        if current is not None:
            raise ValueError(f"Project is currently {current}; wait for it to finish")
        if operation == "preparing" and "preparing" in self.projects.values():
            raise ValueError("Project preparation is already running")
        if operation in {"clearing", "deleting"} and identifier == active:
            raise ValueError("Close the project before clearing its cache or deleting it")
        self.projects[identifier] = operation

    def reassign(self, identifier: str, replacement: str) -> None:
        """Bind an opening manifest to its registered identity before any registry write."""
        if identifier == replacement:
            return
        current = self.projects.get(replacement)
        if current is not None:
            raise ValueError(f"Project is currently {current}; wait for it to finish")
        self.projects[replacement] = self.projects.pop(identifier)

    def release(self, identifier: str) -> None:
        """Allow new operations after success or failure has fully finished."""
        self.projects.pop(identifier, None)

    def action(self, identifier: str) -> ProjectOperation | None:
        """Report whether this project currently has a reserved operation."""
        return self.projects.get(identifier)

    def stop(self) -> None:
        """Reject new operations before the runtime shuts down its preparation worker."""
        self.stopped = True
