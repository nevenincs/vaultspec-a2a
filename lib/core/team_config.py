"""Agent and Team configuration schema (ADR-012, ADR-013).

Provides Pydantic models for loading agent and team definitions from TOML
files. Config is validated eagerly at startup; invalid TOML raises
``pydantic.ValidationError`` or a config-specific error before any graph is
compiled.

Discovery order for agent configs:
    1. {workspace_root}/.vaultspec/agents/{agent_id}.toml   (workspace override)
    2. lib/core/presets/agents/{agent_id}.toml              (bundled default)
    3. Raise AgentConfigNotFoundError

Discovery order for team configs:
    1. {workspace_root}/.vaultspec/teams/{team_id}.toml     (workspace override)
    2. lib/core/presets/teams/{team_id}.toml                (bundled default)
    3. Raise TeamConfigNotFoundError
"""

import tomllib

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from ..utils.enums import Model, Provider
from .exceptions import AgentConfigNotFoundError, TeamConfigNotFoundError


__all__ = [
    "AgentCapabilitiesConfig",
    "AgentConfig",
    "AgentConfigNotFoundError",
    "AgentModelConfig",
    "AgentPermissionsConfig",
    "AgentPersonaConfig",
    "SupervisorConfig",
    "TeamConfig",
    "TeamConfigNotFoundError",
    "TeamDefaultsConfig",
    "TopologyConfig",
    "WorkerOverrideConfig",
    "WorkerRef",
    "load_agent_config",
    "load_team_config",
]

# Bundled preset directories, relative to this file.
_PRESET_AGENTS_DIR = Path(__file__).parent / "presets" / "agents"
_PRESET_TEAMS_DIR = Path(__file__).parent / "presets" / "teams"


# ---------------------------------------------------------------------------
# Agent config models (ADR-012 §2.3)
# ---------------------------------------------------------------------------


class AgentCapabilitiesConfig(BaseModel):
    """ACP clientCapabilities flags for an agent (ADR-012 §2.6)."""

    filesystem_read: bool = False
    filesystem_write: bool = False
    terminal: bool = False


class AgentPermissionsConfig(BaseModel):
    """LangGraph interrupt_before configuration for an agent (ADR-013 §2.7)."""

    require_approval_for: list[str] = Field(default_factory=list)


class AgentModelConfig(BaseModel):
    """Optional per-agent provider/capability override (ADR-012 §2.2)."""

    provider: Provider | None = None
    capability: Model | None = None


class AgentPersonaConfig(BaseModel):
    """System prompt definition for an agent."""

    system_prompt: str


class AgentConfig(BaseModel):
    """Full configuration for a single agent role (ADR-012 §2.3).

    Loaded from a TOML file whose ``[agent]`` section is validated here.
    ``agent.id`` must be a valid Python identifier (it becomes a LangGraph
    node name).
    """

    id: str
    display_name: str
    role: str
    description: str
    persona: AgentPersonaConfig
    model: AgentModelConfig = Field(default_factory=AgentModelConfig)
    capabilities: AgentCapabilitiesConfig = Field(
        default_factory=AgentCapabilitiesConfig
    )
    permissions: AgentPermissionsConfig = Field(default_factory=AgentPermissionsConfig)

    @model_validator(mode="after")
    def validate_id_is_identifier(self) -> "AgentConfig":
        """Ensure agent.id is a valid Python identifier (LangGraph node name)."""
        if not self.id.isidentifier():
            raise ValueError(
                f"agent.id must be a valid Python identifier, got: {self.id!r}"
            )
        return self

    @classmethod
    def from_toml(cls, path: Path) -> "AgentConfig":
        """Load and validate an AgentConfig from a TOML file.

        Args:
            path: Path to the ``.toml`` file containing an ``[agent]`` section.

        Returns:
            Validated ``AgentConfig`` instance.

        Raises:
            pydantic.ValidationError: If the TOML data fails schema validation.
            tomllib.TOMLDecodeError: If the file is not valid TOML.
        """
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data["agent"])


# ---------------------------------------------------------------------------
# Team config models (ADR-013 §2.4)
# ---------------------------------------------------------------------------


class WorkerOverrideConfig(BaseModel):
    """Per-worker model override in a team TOML (ADR-013 §2.3)."""

    provider: Provider | None = None
    capability: Model | None = None


class WorkerRef(BaseModel):
    """Reference to an agent within a team, with optional model override."""

    agent_id: str
    model: WorkerOverrideConfig = Field(default_factory=WorkerOverrideConfig)


class TopologyConfig(BaseModel):
    """LangGraph graph structure declaration (ADR-013 §2.5).

    ``type`` selects the compilation strategy:
    - ``star``: supervisor routes dynamically to any worker.
    - ``pipeline``: fixed sequential chain, no supervisor needed.
    - ``pipeline_loop``: sequential chain where the loop_node's output
      triggers a conditional back-edge.
    """

    type: str  # "star" | "pipeline" | "pipeline_loop"
    order: list[str] = Field(default_factory=list)
    loop_node: str | None = None
    max_loops: int = 3

    @model_validator(mode="after")
    def validate_topology(self) -> "TopologyConfig":
        """Validate topology-specific required fields."""
        if self.type not in ("star", "pipeline", "pipeline_loop"):
            raise ValueError(
                f"topology.type must be 'star', 'pipeline', or 'pipeline_loop', "
                f"got: {self.type!r}"
            )
        if self.type in ("pipeline", "pipeline_loop") and not self.order:
            raise ValueError(f"topology.order is required for type={self.type!r}")
        if self.type == "pipeline_loop" and self.loop_node is None:
            raise ValueError("topology.loop_node is required for type='pipeline_loop'")
        if (
            self.type == "pipeline_loop"
            and self.loop_node is not None
            and self.loop_node not in self.order
        ):
            raise ValueError(
                f"topology.loop_node={self.loop_node!r} must appear in "
                f"topology.order={self.order!r}"
            )
        return self


class SupervisorConfig(BaseModel):
    """Supervisor model binding for star/pipeline_loop topologies."""

    provider: Provider | None = None
    capability: Model | None = None


class TeamDefaultsConfig(BaseModel):
    """Team-wide fallback model binding (ADR-013 §2.3 model resolution)."""

    provider: Provider | None = None
    capability: Model | None = None


class TeamConfig(BaseModel):
    """Full configuration for a team preset (ADR-013 §2.4).

    Loaded from a TOML file whose ``[team]`` section is validated here.
    ``team.id`` must match the filename stem.
    """

    id: str
    display_name: str
    description: str = ""
    defaults: TeamDefaultsConfig = Field(default_factory=TeamDefaultsConfig)
    supervisor: SupervisorConfig = Field(default_factory=SupervisorConfig)
    topology: TopologyConfig
    workers: list[WorkerRef]

    @model_validator(mode="after")
    def validate_topology_order_subset(self) -> "TeamConfig":
        """Validate that topology.order agent IDs are a subset of workers."""
        worker_ids = {w.agent_id for w in self.workers}
        for agent_id in self.topology.order:
            if agent_id not in worker_ids:
                raise ValueError(
                    f"topology.order contains '{agent_id}' which is not listed "
                    f"in [[team.workers]]: {sorted(worker_ids)!r}"
                )
        return self

    @classmethod
    def from_toml(cls, path: Path) -> "TeamConfig":
        """Load and validate a TeamConfig from a TOML file.

        Args:
            path: Path to the ``.toml`` file containing a ``[team]`` section.

        Returns:
            Validated ``TeamConfig`` instance.

        Raises:
            pydantic.ValidationError: If the TOML data fails schema validation.
            tomllib.TOMLDecodeError: If the file is not valid TOML.
        """
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data["team"])


# ---------------------------------------------------------------------------
# Config discovery helpers (ADR-012 §2.8, ADR-013 §2.8)
# ---------------------------------------------------------------------------


def load_agent_config(
    agent_id: str,
    workspace_root: Path | None = None,
) -> AgentConfig:
    """Resolve and load an AgentConfig using the two-level discovery order.

    Args:
        agent_id:       The agent identifier (must match the TOML filename stem).
        workspace_root: Optional workspace root; if provided, checks
                        ``{workspace_root}/.vaultspec/agents/{agent_id}.toml``
                        before falling back to the bundled preset.

    Returns:
        Validated ``AgentConfig``.

    Raises:
        AgentConfigNotFoundError: If neither the workspace override nor the
                                   bundled preset exists.
        pydantic.ValidationError: If the TOML data fails schema validation.
    """
    candidates: list[Path] = []
    if workspace_root is not None:
        candidates.append(workspace_root / ".vaultspec" / "agents" / f"{agent_id}.toml")
    candidates.append(_PRESET_AGENTS_DIR / f"{agent_id}.toml")

    for path in candidates:
        if path.is_file():
            return AgentConfig.from_toml(path)

    raise AgentConfigNotFoundError(agent_id)


def load_team_config(
    team_id: str,
    workspace_root: Path | None = None,
) -> TeamConfig:
    """Resolve and load a TeamConfig using the two-level discovery order.

    Args:
        team_id:        The team identifier (must match the TOML filename stem).
        workspace_root: Optional workspace root; if provided, checks
                        ``{workspace_root}/.vaultspec/teams/{team_id}.toml``
                        before falling back to the bundled preset.

    Returns:
        Validated ``TeamConfig``.

    Raises:
        TeamConfigNotFoundError: If neither the workspace override nor the
                                  bundled preset exists.
        pydantic.ValidationError: If the TOML data fails schema validation.
    """
    candidates: list[Path] = []
    if workspace_root is not None:
        candidates.append(workspace_root / ".vaultspec" / "teams" / f"{team_id}.toml")
    candidates.append(_PRESET_TEAMS_DIR / f"{team_id}.toml")

    for path in candidates:
        if path.is_file():
            return TeamConfig.from_toml(path)

    raise TeamConfigNotFoundError(team_id)
