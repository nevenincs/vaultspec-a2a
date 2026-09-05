"""Live proof that a provider lane executes real work inside the run's project.

Everything else in this repository proves a piece of the path: the control plane
is certified end to end by the acceptance harness, the native read floor is
proven deterministically against a real ACP subprocess, and the harness pin is
proven against the real search binary. None of those executes a model turn, so
none of them answers the only question that matters to a user - can this system
actually do work?

This module answers it, mock-free: the production provider factory builds the
real chat model, the real adapter spawns the real CLI, and the agent is asked
for a fact that exists ONLY inside the project it was sited in. A lane that
answered from its own knowledge, or that ran somewhere else, cannot produce the
marker; reproducing it proves the turn completed AND that it happened inside the
run's active project.

It is ``service``-marked and skips when the lane carries no credential, because
a proof that silently passes without executing is worse than no proof.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ..graph.enums import Provider
from ..providers.factory import ProviderFactory
from ..providers.lane_admission import PROVEN_TURN_LANES
from ._provider_catalog_live import declared_lane_model_value

if TYPE_CHECKING:
    from ..conftest import ExternalPrerequisiteRule

pytestmark = [pytest.mark.service, pytest.mark.asyncio]


async def test_the_claude_lane_completes_a_turn_inside_the_runs_project(
    external_prerequisite: ExternalPrerequisiteRule,
) -> None:
    """A real turn reads a project-only fact and reproduces it.

    The marker is minted per run, so no cache, no prior transcript, and no
    training data can supply it. The only way to answer is to read the file in
    the workspace the run was sited in.
    """
    if Provider.CLAUDE.value not in {str(lane) for lane in PROVEN_TURN_LANES}:
        pytest.skip("the claude lane is not declared turn-proven")
    external_prerequisite("claude-credential")

    marker = f"ORBITAL-{uuid.uuid4().hex[:12].upper()}"
    workspace = Path(tempfile.mkdtemp(prefix="live-execution-project-"))
    (workspace / "FACTS.md").write_text(
        f"# Project facts\n\nThe project's calibration code is {marker}.\n",
        encoding="utf-8",
    )

    served, reason = await declared_lane_model_value(Provider.CLAUDE.value, workspace)
    if served is None:
        external_prerequisite.absent("provider-catalog-live-selection", reason)
    model = ProviderFactory().create(
        Provider.CLAUDE, model=served, workspace_root=workspace
    )
    response = await model.ainvoke(
        [
            HumanMessage(
                content=(
                    "Read the file FACTS.md in your working directory and reply "
                    "with ONLY the calibration code it contains. No other words."
                )
            )
        ]
    )

    answer = str(response.content)
    assert marker in answer, (
        "the lane did not reproduce the project-only marker, so either the turn "
        f"did not complete or it did not run inside the run's project: {answer!r}"
    )
