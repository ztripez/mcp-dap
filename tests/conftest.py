"""Pytest configuration and fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_breakpoints() -> list[dict[str, int]]:
    """Sample breakpoint specifications."""
    return [
        {"line": 10},
        {"line": 20},
        {"line": 30, "condition": "x > 5"},
    ]
