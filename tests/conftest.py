"""Shared fixtures for catalog input and resolution tests."""

import pytest

from remedy_fixtures import make_snapshot


@pytest.fixture
def snapshot():
    return make_snapshot()
