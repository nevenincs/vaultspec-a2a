"""Fixtures and hooks for core-layer tests.

Provides the ``requires_vidaimock`` fail-fast marker: tests so marked
hard-fail (not skip) when a VidaiMock tape-replay server is unreachable.

The base URL is read from ``MOCK_API_BASE`` (same env var used by
``MockChatModel``) and falls back to ``http://localhost:8100``.
"""

from __future__ import annotations

import os

import httpx
import pytest


__all__: list[str] = []

_DEFAULT_VIDAIMOCK_URL = "http://localhost:8100"


def resolve_vidaimock_base_url() -> str:
    """Return the VidaiMock base URL from env or the default fallback."""
    raw = os.environ.get("MOCK_API_BASE", "").rstrip("/").removesuffix("/v1")
    return raw if raw else _DEFAULT_VIDAIMOCK_URL


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail (not skip) any ``requires_vidaimock`` test when VidaiMock is unreachable.

    Probes ``GET /v1/models`` — the OpenAI-compatible discovery endpoint that
    VidaiMock exposes as its health check.  ``pytest.fail()`` produces a hard
    ERROR, not a silent SKIP.
    """
    if item.get_closest_marker("requires_vidaimock"):
        url = resolve_vidaimock_base_url()
        try:
            resp = httpx.get(f"{url}/v1/models", timeout=2.0)
            resp.raise_for_status()
        except Exception as exc:
            pytest.fail(
                f"VidaiMock is not reachable at {url!r}: {exc}. "
                "Start it with: just vidaimock-up",
                pytrace=False,
            )
