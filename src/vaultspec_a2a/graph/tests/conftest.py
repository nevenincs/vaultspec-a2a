"""Fixtures and hooks for graph-layer tests."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ...testing import apply_layer_markers
from ..enums import Provider
from ..protocols import ProviderFactoryProtocol

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


_MIDDLEWARE_FILES = frozenset(
    {"test_worker_integration.py", "test_worker_authoring_wiring.py"}
)
# Layer-1 tests that still perform real I/O — a live SQLite checkpointer, or real
# ACP subprocesses driven through a compiled graph. They keep ``core`` but are NOT
# pure, so the orthogonal ``unit`` marker is withheld.
#
# ``unit`` is a machine-readable claim, so a wrong one is worse than none: a
# selection that excludes impure tests silently INCLUDES a file listed nowhere
# here, and a run believed hermetic is not. Membership is decided by what the
# file actually drives, not by where it sits.
_IMPURE_CORE_FILES = frozenset(
    {
        "test_compiler.py",
        "test_harness_topology_reach.py",
        # Live AsyncSqliteSaver against a real database file.
        "test_diverge.py",
        "test_persona_web_composition.py",
        "test_research_adr.py",
        "test_research_adr_clarification.py",
        "test_research_web_locators.py",
        # Real async engine and session maker.
        "test_task_queue.py",
        "test_vault_reader.py",
        "test_vault_write_isolation.py",
        # Real HTTP against a live engine. This file declares its own ``service``
        # marker and its docstring says so, but that declaration cannot stop this
        # hook adding a layer mark - so the purity claim had to be withheld here
        # rather than left to the file to refuse.
        "test_feedback_grounding_live.py",
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark graph tests: ``middleware`` for L2 imports, else ``core`` (+ ``unit``)."""
    apply_layer_markers(
        items,
        package_dir=_PACKAGE_DIR,
        middleware_files=_MIDDLEWARE_FILES,
        impure_files=_IMPURE_CORE_FILES,
    )


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


def deterministic_model_assignment(team_config: Any) -> dict[str, dict[str, Any]]:
    """Build exact schema-v1 assignments for topology-only graph tests."""
    assignment = {
        "provider": Provider.DETERMINISTIC.value,
        "execution_mode": "in-process-deterministic",
        "catalog_revision": "test-revision",
        "entry_id": "test-entry",
        "model_name": "deterministic",
        "controls": [],
        "fallbacks": [],
        "provenance": {"selection_source": "team_selection"},
        "schema_version": 1,
    }
    return {
        "__supervisor__": dict(assignment),
        **{ref.agent_id: dict(assignment) for ref in team_config.workers},
    }
