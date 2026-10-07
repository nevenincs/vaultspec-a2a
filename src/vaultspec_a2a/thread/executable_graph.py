"""Immutable executable graph authority resolved at run admission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_validator

from ..team.team_config import AgentConfig, TeamConfig, load_agent_config
from .action_receipts import canonical_json, sha256_hex
from .constants import DEFAULT_SUPERVISOR_ID

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["FrozenGraphDefinition", "freeze_graph_definition"]


class FrozenGraphDefinition(BaseModel):
    """Complete resolved compiler inputs; partial persisted models are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["executable-graph-v1"]
    team: dict[str, object]
    agents: dict[str, dict[str, object]]
    supervisor: dict[str, object] | None

    # The parsed configs, kept from the one validation that admits the
    # definition, so no read of a field below parses the persisted dicts again.
    _team_config: TeamConfig = PrivateAttr()
    _agent_configs: dict[str, AgentConfig] = PrivateAttr()
    _supervisor_config: AgentConfig | None = PrivateAttr()

    @model_validator(mode="after")
    def validate_complete_definition(self) -> Self:
        team = self._validated_team()
        self._team_config = team
        self._agent_configs = self._validated_agents(team)
        self._supervisor_config = self._validated_supervisor(team)
        return self

    def _validated_team(self) -> TeamConfig:
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
        if (
            team.graph.run_timeout_seconds is None
            or team.graph.run_timeout_seconds <= 0
        ):
            raise ValueError("graph execution requires a declared positive run timeout")
        return team

    def _validated_agents(self, team: TeamConfig) -> dict[str, AgentConfig]:
        expected_agents = {worker.agent_id for worker in team.workers}
        if set(self.agents) != expected_agents:
            raise ValueError(
                "graph definition does not contain the exact worker roster"
            )
        agents: dict[str, AgentConfig] = {}
        for key, raw in self.agents.items():
            agent = AgentConfig.model_validate(raw)
            if agent.id != key or agent.model_dump(mode="json") != raw:
                raise ValueError("graph definition contains an incomplete agent")
            agents[key] = agent
        return agents

    def _validated_supervisor(self, team: TeamConfig) -> AgentConfig | None:
        if team.topology.type.requires_supervisor != (self.supervisor is not None):
            raise ValueError("graph definition has incompatible supervisor authority")
        if self.supervisor is None:
            return None
        supervisor = AgentConfig.model_validate(self.supervisor)
        if (
            supervisor.id != DEFAULT_SUPERVISOR_ID
            or supervisor.model_dump(mode="json") != self.supervisor
        ):
            raise ValueError("graph definition contains an incomplete supervisor")
        return supervisor

    def digest(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(mode="json")).encode())

    @property
    def team_id(self) -> str:
        return self._team_config.id

    @property
    def step_timeout_seconds(self) -> int:
        timeout = self._team_config.graph.step_timeout_seconds
        if timeout is None or timeout <= 0:
            raise ValueError("accepted graph has no positive step timeout")
        return timeout

    @property
    def recursion_limit(self) -> int:
        """The superstep budget the accepted preset declares for one invocation."""
        return self._team_config.graph.recursion_limit

    @property
    def run_timeout_seconds(self) -> int:
        timeout = self._team_config.graph.run_timeout_seconds
        if timeout is None or timeout <= 0:
            raise ValueError("accepted graph has no positive run timeout")
        return timeout

    def compiler_inputs(
        self,
    ) -> tuple[TeamConfig, dict[str, AgentConfig], AgentConfig | None]:
        return (
            self._team_config,
            dict(self._agent_configs),
            self._supervisor_config,
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
        if team.topology.type.requires_supervisor
        else None
    )
    return FrozenGraphDefinition(
        schema_version="executable-graph-v1",
        team=team.model_dump(mode="json"),
        agents=agents,
        supervisor=supervisor,
    )
