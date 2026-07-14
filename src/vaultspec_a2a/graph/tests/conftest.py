"""Fixtures and hooks for graph-layer tests."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ..protocols import ProviderFactoryProtocol

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


_MIDDLEWARE_FILES = frozenset({"test_worker_integration.py"})
# Layer-1 tests that still perform real I/O (a live SQLite checkpointer here) —
# they keep ``core`` but are NOT pure, so the orthogonal ``unit`` marker is withheld.
_IMPURE_CORE_FILES = frozenset({"test_compiler.py"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark graph tests: ``middleware`` for L2 imports, else ``core`` (+ ``unit``)."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        if item.path.name in _MIDDLEWARE_FILES:
            item.add_marker(pytest.mark.middleware)
        else:
            item.add_marker(pytest.mark.core)
            if item.path.name not in _IMPURE_CORE_FILES:
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
        _kwargs: dict[str, Any] = {"responses": ["stub response"]}
        return FakeChatModel(**_kwargs)


@pytest.fixture
def pf() -> ProviderFactoryProtocol:
    """Stub provider factory for graph compilation tests (Layer 1 only)."""
    factory = _StubProviderFactory()
    assert isinstance(factory, ProviderFactoryProtocol)
    return factory
