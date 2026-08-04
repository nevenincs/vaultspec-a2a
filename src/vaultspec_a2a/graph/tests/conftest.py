"""Fixtures and hooks for graph-layer tests."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeChatModel

from ..enums import Model, Provider
from ..protocols import ProviderFactoryProtocol

_PACKAGE_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)


_MIDDLEWARE_FILES = frozenset(
    {"test_worker_integration.py", "test_worker_authoring_wiring.py"}
)
# Layer-1 tests that still perform real I/O — a live SQLite checkpointer, or real
# ACP subprocesses driven through a compiled graph. They keep ``core`` but are NOT
# pure, so the orthogonal ``unit`` marker is withheld.
_IMPURE_CORE_FILES = frozenset({"test_compiler.py", "test_harness_topology_reach.py"})


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


def deterministic_model_assignment(team_config: Any) -> dict[str, dict[str, Any]]:
    """Build the frozen assignment a compile needs now that presets name no lane.

    Bundled presets no longer declare a provider or capability: a run chooses
    both at start from the catalog its execution lane serves, and freezes the
    result per role. A compile therefore has nothing to resolve from
    configuration alone and refuses, which is correct and is what the
    served-catalog retirement intends.

    Built through the CANONICAL producer rather than by hand. `FrozenAssignment`
    already declares itself the complete frozen execution assignment the compiler
    consumes, so re-deriving that shape here would be a second declaration of one
    concept - and this helper was exactly that until the canonical-homes sweep
    caught it.

    The deterministic pinning stays an explicit POLICY of this helper, not a
    default hidden inside the producer. Structural tests - node sets, edges,
    timeouts, retry policy - must never acquire a served lane to assert a graph
    shape, because that spends money to prove something about topology.
    """
    from ...providers.model_profiles import (
        AssignmentSource,
        ProfileAssignment,
        RoleAssignment,
        freeze_assignment,
    )

    roles = [
        RoleAssignment(
            role_id=ref.agent_id,
            agent_id=ref.agent_id,
            provider=Provider.DETERMINISTIC,
            capability=Model.MID,
            model_name="deterministic",
            fallback_providers=[],
            provider_source=AssignmentSource.TEAM_DEFAULT,
            capability_source=AssignmentSource.TEAM_DEFAULT,
        )
        for ref in team_config.workers
    ]
    frozen = freeze_assignment(
        ProfileAssignment(profile_id="team-defaults", roles=roles)
    )
    return frozen.compiler_map()
