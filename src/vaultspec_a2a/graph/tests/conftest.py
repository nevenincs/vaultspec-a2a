"""Fixtures and hooks for graph-layer tests.

Provides the ``requires_vidaimock`` fail-fast marker: tests so marked
hard-fail (not skip) when a VidaiMock tape-replay server is unreachable.

The base URL is read from ``MOCK_API_BASE`` (same env var used by
``MockChatModel``) and falls back to ``http://localhost:8100``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

if TYPE_CHECKING:
    from ..protocols import ProviderFactoryProtocol

__all__: list[str] = []


_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)

_INFRA_MARKERS = frozenset(
    {
        "live",
        "requires_vidaimock",
        "requires_jaeger",
        "requires_postgres",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark pure Layer 1 tests in this directory as ``core``.

    Tests that carry infrastructure markers (live, requires_vidaimock, etc.)
    are NOT marked ``core`` — they depend on Layer 2 services.
    """
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if any(item.get_closest_marker(m) for m in _INFRA_MARKERS):
            continue
        item.add_marker(pytest.mark.core)
        item.add_marker(pytest.mark.unit)


# ---------------------------------------------------------------------------
# Layer 1 test stub — avoids importing the Layer 2 ProviderFactory
# ---------------------------------------------------------------------------


class _StubProviderFactory:
    """Returns a ``FakeChatModel`` for any provider."""

    def create(
        self,
        provider: Any,
        *,
        model: Any | None = None,
        agent_config: Any | None = None,
        workspace_root: Any | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        return FakeChatModel(responses=["stub response"])  # type: ignore[call-arg]


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """Stub provider factory for graph compilation tests (Layer 1 only)."""
    return _StubProviderFactory()


_DEFAULT_VIDAIMOCK_URL = "http://localhost:8100"


def resolve_vidaimock_base_url() -> str:
    """Return the VidaiMock base URL from env or the default fallback."""
    raw = os.environ.get("MOCK_API_BASE", "").rstrip("/").removesuffix("/v1")
    return raw if raw else _DEFAULT_VIDAIMOCK_URL


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail (not skip) any ``requires_vidaimock`` test when VidaiMock is unreachable.

    Probes ``GET /v1/models`` -- the OpenAI-compatible discovery endpoint that
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
