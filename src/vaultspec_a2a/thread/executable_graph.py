"""Immutable executable graph authority resolved at run admission."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ..team.team_config import AgentConfig, TeamConfig, TopologyType, load_agent_config
from .constants import DEFAULT_SUPERVISOR_ID

if TYPE_CHECKING:
    from pathlib import Path


class FrozenGraphDefinition(BaseModel):
    """Complete resolved compiler inputs; partial persisted models are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["executable-graph-v1"]
    team: dict[str, object]
    agents: dict[str, dict[str, object]]
    supervisor: dict[str, object] | None

    @model_validator(mode="after")
    def validate_complete_definition(self) -> Self:
        team = TeamConfig.model_validate(self.team)
        if team.model_dump(mode="json") != self.team:
            raise ValueError("graph definition contains an incomplete team")
        if (
            team.graph.step_timeout_seconds is None
            or team.graph.step_timeout_seconds <= 0
        ):
            raise ValueError(
                "graph execution requires a declared positive step timeout"
            )
        expected_agents = {worker.agent_id for worker in team.workers}
        if set(self.agents) != expected_agents:
            raise ValueError(
                "graph definition does not contain the exact worker roster"
            )
        for key, raw in self.agents.items():
            agent = AgentConfig.model_validate(raw)
            if agent.id != key or agent.model_dump(mode="json") != raw:
                raise ValueError("graph definition contains an incomplete agent")
        requires_supervisor = team.topology.type in {
            TopologyType.STAR,
            TopologyType.PIPELINE_LOOP,
        }
        if requires_supervisor != (self.supervisor is not None):
            raise ValueError("graph definition has incompatible supervisor authority")
        if self.supervisor is not None:
            supervisor = AgentConfig.model_validate(self.supervisor)
            if (
                supervisor.id != DEFAULT_SUPERVISOR_ID
                or supervisor.model_dump(mode="json") != self.supervisor
            ):
                raise ValueError("graph definition contains an incomplete supervisor")
        return self

    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    @property
    def team_id(self) -> str:
        return TeamConfig.model_validate(self.team).id

    @property
    def step_timeout_seconds(self) -> int:
        timeout = TeamConfig.model_validate(self.team).graph.step_timeout_seconds
        if timeout is None or timeout <= 0:
            raise ValueError("accepted graph has no positive step timeout")
        return timeout

    def compiler_inputs(
        self,
    ) -> tuple[TeamConfig, dict[str, AgentConfig], AgentConfig | None]:
        return (
            TeamConfig.model_validate(self.team),
            {
                key: AgentConfig.model_validate(value)
                for key, value in self.agents.items()
            },
            AgentConfig.model_validate(self.supervisor)
            if self.supervisor is not None
            else None,
        )


def freeze_graph_definition(
    team: TeamConfig, *, workspace_root: Path
) -> FrozenGraphDefinition:
    """Resolve all declared compiler configuration before accepting a run."""
    agents = {
        worker.agent_id: load_agent_config(
            worker.agent_id, workspace_root=workspace_root
        ).model_dump(mode="json")
        for worker in team.workers
    }
    supervisor = (
        load_agent_config(
            DEFAULT_SUPERVISOR_ID, workspace_root=workspace_root
        ).model_dump(mode="json")
        if team.topology.type in {TopologyType.STAR, TopologyType.PIPELINE_LOOP}
        else None
    )
    return FrozenGraphDefinition(
        schema_version="executable-graph-v1",
        team=team.model_dump(mode="json"),
        agents=agents,
        supervisor=supervisor,
    )
