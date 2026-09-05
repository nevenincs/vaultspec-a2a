"""Live proof that the vaultspec-core read surface does real work in a run.

The registry admits `vaultspec-core` on the strength of an upstream restricted
launch, and the contract check proves the launched server serves exactly the
declared four. Neither proves a MODEL ever reaches them. The served-profile rule
is explicit that a capability counts only when a live test has completed a real
turn using it - construction coverage, config-parse coverage and handshake
coverage do not qualify - so this drives a real turn that answers only if the
agent actually called a core tool.

The question asked has no answer in the model's own knowledge: it names a feature
whose documents exist in this checkout's records and nowhere else, so a
reproduced document stem is evidence of a tool call against the pinned project
rather than recall.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ..control.config import settings
from ..graph.enums import Provider
from ..providers._acp_mcp import (
    compose_harness_mcp_servers,
    declared_harness_tools,
    harness_allowed_tool_names,
)
from ..providers.factory import ProviderFactory
from ..providers.lane_admission import PROVEN_TURN_LANES
from ._provider_catalog_live import declared_lane_model_value

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule

pytestmark = [pytest.mark.service, pytest.mark.asyncio]

_CORE = "vaultspec-core"
# A feature whose records live in this checkout. The agent cannot know it.
_FEATURE = "current-project-binding"
_EXPECTED_STEM = "2026-08-03-current-project-binding-adr"


async def test_an_agent_completes_a_turn_through_the_core_read_surface(
    tmp_path_factory: pytest.TempPathFactory,
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """A real turn calls a declared core tool and reports what it returned."""
    if Provider.CLAUDE.value not in {str(lane) for lane in PROVEN_TURN_LANES}:
        pytest.skip("the claude lane is not declared turn-proven")
    external_prerequisite("claude-credential")

    # The run's project is this checkout: it is a real vaultspec workspace, which
    # is what the core server requires, and its records are what the answer must
    # come from. The server is pinned to it through the declared root-pin axis.
    project = settings.project_root

    served, reason = await declared_lane_model_value(Provider.CLAUDE.value, project)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    model = ProviderFactory().create(
        Provider.CLAUDE, model=served, workspace_root=project
    )
    grounded = compose_harness_mcp_servers(
        model,
        [_CORE],
        allowed_tools=harness_allowed_tool_names([_CORE]),
        project_root=str(project),
    )

    response = await grounded.ainvoke(
        [
            HumanMessage(
                content=(
                    f"Use your {_CORE} MCP tools - do not read files directly - "
                    f"to find the documents recorded for the feature "
                    f"{_FEATURE!r}. Reply with ONLY the full stem of the "
                    f"architecture decision record you find. No other words."
                )
            )
        ]
    )

    answer = str(response.content)
    assert _EXPECTED_STEM in answer, (
        "the agent did not reproduce a document stem that exists only in this "
        f"project's records, so the core read surface was not exercised: {answer!r}"
    )


def test_the_declared_core_surface_is_the_read_set() -> None:
    """The allowlist a run auto-permits is exactly the restricted launch's tools.

    Cheap, credential-free, and load-bearing: it fails the moment somebody adds a
    mutating verb to the declaration, which is the change the restricted launch
    exists to make impossible.
    """
    assert set(declared_harness_tools(_CORE)) == {
        "status",
        "find",
        "check",
        "discover",
    }
