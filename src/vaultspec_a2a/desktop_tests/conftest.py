"""Resource declaration shared by installed desktop certification tests."""

from __future__ import annotations

import pytest


def pytest_itemcollected(item: pytest.Item) -> None:
    """Declare isolated desktop process capacity before placement is derived."""

    item.add_marker(pytest.mark.resource("desktop-processes", shared=True))
