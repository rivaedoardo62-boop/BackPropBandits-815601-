"""Shared fixtures."""

from __future__ import annotations

import pytest

from fakes import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
