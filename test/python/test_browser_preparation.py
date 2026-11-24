"""Browser test startup waits for slow preparation and reports failures clearly."""

from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from .psm_fixtures import wait_for_project


class PreparationClock:
    """Advance preparation time without slowing down the regression tests."""

    def __init__(self) -> None:
        """Start the simulated clock at zero seconds."""
        self.seconds = 0.0

    def monotonic(self) -> float:
        """Return the current simulated elapsed time."""
        return self.seconds

    def sleep(self, duration: float) -> None:
        """Advance time by the requested polling delay."""
        self.seconds += duration


@pytest.fixture(name="clock")
def preparation_clock(monkeypatch: pytest.MonkeyPatch) -> PreparationClock:
    """Replace only the fixture helper's clock, leaving application timing untouched."""
    clock = PreparationClock()
    monkeypatch.setattr("test.python.psm_fixtures.monotonic", clock.monotonic)
    monkeypatch.setattr("test.python.psm_fixtures.sleep", clock.sleep)
    return clock


def test_preparation_can_finish_after_two_seconds(clock: PreparationClock) -> None:
    """A project taking three seconds must not fail the browser helper's readiness check."""
    client = Mock(spec=TestClient)

    def project_status() -> dict[str, str]:
        """Publish readiness after the previous two-second cutoff has passed."""
        if clock.seconds < 3:
            return {"state": "preparing", "message": "Reading sources"}
        return {"state": "ready", "message": "Synthetic project"}

    client.get.return_value.json.side_effect = project_status
    wait_for_project(client)
    assert 3 <= clock.seconds < 3.1


def test_preparation_failure_is_reported_immediately(clock: PreparationClock) -> None:
    """Surface the original preparation error without waiting for the timeout."""
    client = Mock(spec=TestClient)
    client.get.return_value.json.return_value = {
        "state": "error",
        "message": "Cannot read synthetic mzML",
    }
    with pytest.raises(RuntimeError, match="Cannot read synthetic mzML"):
        wait_for_project(client)
    assert clock.seconds == 0


def test_preparation_timeout_includes_last_status(clock: PreparationClock) -> None:
    """Stop stalled preparation at the deadline and retain its last progress message."""
    client = Mock(spec=TestClient)
    client.get.return_value.json.return_value = {
        "state": "preparing",
        "message": "Reading sources",
    }
    with pytest.raises(TimeoutError, match="0.2 seconds.*Reading sources"):
        wait_for_project(client, timeout_seconds=0.2)
    assert clock.seconds == pytest.approx(0.2)
