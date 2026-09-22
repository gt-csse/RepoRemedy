"""Shared repository snapshots and file-read fixtures."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from remedy_fixtures import make_snapshot


@pytest.fixture
def snapshot():
    return make_snapshot()


@pytest.fixture
def track_file_reads(monkeypatch):
    """Observe reads from an actual file descriptor, preserving open/close behavior."""
    original = Path.open

    def track(path):
        stream = original(path, "rb")
        tracked = MagicMock(wraps=stream)
        tracked.__enter__.return_value = tracked
        tracked.__exit__.side_effect = lambda *args: stream.close()
        monkeypatch.setattr(
            Path,
            "open",
            lambda self, *args, **kwargs: tracked if self == path else original(self, *args, **kwargs),
        )
        return tracked

    return track
