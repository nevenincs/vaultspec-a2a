"""Agent and Team configuration schema.

Provides Pydantic models for loading agent and team definitions from TOML
files. Config is validated eagerly at startup; invalid TOML raises
``pydantic.ValidationError`` or a config-specific error before any graph is
compiled.

Discovery order for agent configs:
    1. {workspace_root}/.vaultspec/agents/{agent_id}.toml   (workspace override)
    2. vaultspec_a2a.team/presets/agents/{agent_id}.toml    (bundled resource)
    3. Raise AgentConfigNotFoundError

Discovery order for team configs:
    1. {workspace_root}/.vaultspec/teams/{team_id}.toml     (workspace override)
    2. vaultspec_a2a.team/presets/teams/{team_id}.toml      (bundled resource)
    3. Raise TeamConfigNotFoundError
"""

import re
import tomllib
from enum import StrEnum
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from vaultspec_a2a.authoring.contract import is_document_authoring_topology
from vaultspec_a2a.graph.enums import Model, Provider
from vaultspec_a2a.thread.errors import (
    AgentConfigNotFoundError,
    ConfigError,
    TeamConfigNotFoundError,
)

# Safe agent_id pattern — alphanumeric, underscores, hyphens only.
# Prevents path traversal attacks via crafted agent_id values (e.g. "../../etc").
# Must be a valid Python identifier (validated in
# AgentConfig.validate_id_is_identifier), but this pattern adds an explicit
# safeguard for use in load_agent_config.
_SAFE_AGENT_ID_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\-]{0,62}$")


__all__ = [
    "DEFAULT_AUTHORING_SURFACES",
    "DEFAULT_PROFILE_DESCRIPTION",
    "DEFAULT_PROFILE_DISPLAY_NAME",
    "DEFAULT_PROFILE_ID",
    "AgentCapabilitiesConfig",
    "AgentConfig",
    "AgentConfigNotFoundError",
    "AgentModelConfig",
    "AgentPermissionsConfig",
    "AgentPersonaConfig",
    "ResearchThreadSpec",
    "SupervisorConfig",
    "TeamConfig",
    "TeamConfigNotFoundError",
    "TeamDefaultsConfig",
    "TeamGraphConfig",
    "TeamHarnessConfig",
    "TeamPermissionsConfig",
    "TeamPersonaConfig",
    "TeamProfileConfig",
    "TeamProfileRoleConfig",
    "TopologyConfig",
    "TopologyType",
    "WorkerOverrideConfig",
    "WorkerRef",
    "authoring_capability",
    "discover_team_preset_ids",
    "is_mock_preset",
    "load_agent_config",
    "load_team_config",
    "supported_capabilities",
]

# The implicit, always-present profile: the empty overlay that runs the team's
# normal resolution chain with no profile layer. It is every team's
# default profile.
DEFAULT_PROFILE_ID = "team-defaults"
DEFAULT_PROFILE_DISPLAY_NAME = "Team defaults"
DEFAULT_PROFILE_DESCRIPTION = (
    "Use the team's normal model resolution chain with no profile overlays."
)

# The five agent-harness surfaces a document-authoring run's workspace must
# carry: personas (runtime + workspace depth),
# rules (the compiled + on-disk corpus), skills (procedure documents), templates
# (canonical placeholder shapes), and tools (the vaultspec-core CLI, MCP servers,
# provider web tooling). Absence of a ``[team.harness]`` block means all five are
# required for an authoring preset's writer roles.
DEFAULT_AUTHORING_SURFACES: tuple[str, ...] = (
    "personas",
    "rules",
    "skills",
    "templates",
    "tools",
)


class TopologyType(StrEnum):
    """Supported graph topology types.

    Uses enum membership instead of string comparison.
    """

    STAR = "star"
    PIPELINE = "pipeline"
    PIPELINE_LOOP = "pipeline_loop"
    RESEARCH_ADR = "research_adr"


# Bundled preset directories, resolved from the installed ``vaultspec_a2a.team``
# package rather than a checkout-relative ``__file__`` path, so preset discovery
# works from a clean installed wheel. Wheels install unzipped, so the resource
# traversable is a real directory these ``Path`` operations can read.
_PRESET_ROOT = Path(str(resources.files("vaultspec_a2a.team"))) / "presets"
_PRESET_AGENTS_DIR = _PRESET_ROOT / "agents"
_PRESET_TEAMS_DIR = _PRESET_ROOT / "teams"


def discover_team_preset_ids(workspace_root: Path | None = None) -> frozenset[str]:
    """Discover team preset IDs from the workspace and the bundled directory.

    Returns the union of TOML file stems from
    ``{workspace_root}/.vaultspec/teams/*.toml`` (when a workspace is given and
    the directory exists) and the installed
    ``vaultspec_a2a.team/presets/teams`` package resource. Discovery is a superset of
    what ``load_team_config`` can resolve, so a workspace-local preset is listed
    even though it shadows or extends the bundled set. Returns an empty frozenset
    when no directory exists.
    """
    ids: set[str] = set()
    if workspace_root is not None:
        workspace_teams_dir = workspace_root / ".vaultspec" / "teams"
        if workspace_teams_dir.is_dir():
            ids.update(p.stem for p in workspace_teams_dir.glob("*.toml"))
    if _PRESET_TEAMS_DIR.is_dir():
        ids.update(p.stem for p in _PRESET_TEAMS_DIR.glob("*.toml"))
    return frozenset(ids)


def is_mock_preset(preset_id: str) -> bool:
    """Return whether a preset id follows the source-side mock convention.

    Source and Compose discovery may include these certification presets. The
    desktop product wheel excludes them at packaging time; this helper remains
    useful to source-side callers that need to label the wider inventory.
    """
    return preset_id.startswith("mock-")


def authoring_capability(topology_type: TopologyType) -> str:
    """Return the coarse authoring capability a topology delivers.

    ``document_authoring`` for the research_adr document phase machine; ``coding``
    for the coder topologies. This is diagnostic truth for the Rust backend, not
    product curation text.
    """
    if topology_type == TopologyType.RESEARCH_ADR:
        return "document_authoring"
    return "coding"


def supported_capabilities(topology_type: TopologyType) -> list[str]:
    """Return the concrete document outputs a topology can produce.

    The research_adr phase machine authors a research document and an
    architecture decision; coder topologies produce no vault-document capability
    under this mission surface. Diagnostic truth for the Rust backend, not
    product curation text.
    """
    if topology_type == TopologyType.RESEARCH_ADR:
        return ["research_document", "architecture_decision"]
    return []


# ---------------------------------------------------------------------------
# Agent config models
# ---------------------------------------------------------------------------


class AgentCapabilitiesConfig(BaseModel):
    """ACP clientCapabilities flags for an agent."""

    filesystem_read: bool = False
    filesystem_write: bool = False
    terminal: bool = False


class AgentPermissionsConfig(BaseModel):
    """Per-agent approval requirements for ACP method calls.

    Note: ``require_approval_for`` entries are ACP method names
    (e.g. ``"fs.writeTextFile"``) that must match the method names sent by the
    ACP subprocess at runtime.  Because the full set of ACP tool names is
    determined by the agent binary — not by a static schema known at config-load
    time — pre-validation against a fixed allowlist is not practical.  Invalid
    entries are silently ignored by the runtime dispatch layer; operators should
    consult the agent's ACP capability documentation to confirm valid names.

    Note: ``interrupt_before`` is no longer used. The graph always compiles
    with ``interrupt_before=[]``; approval gating is handled by the
    ``permission_callback`` closure wired into each worker node at compile
    time (see ``src/vaultspec_a2a/graph/compiler.py``).
    """

    require_approval_for: list[str] = Field(default_factory=list)


class AgentModelConfig(BaseModel):
    """Optional per-agent provider/capability override."""

    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class AgentPersonaConfig(BaseModel):
    """System prompt definition for an agent."""

    system_prompt: str


class AgentConfig(BaseModel):
    """Full configuration for a single agent role.

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
        """Ensure agent.id matches _SAFE_AGENT_ID_RE."""
        if not _SAFE_AGENT_ID_RE.match(self.id):
            raise ValueError(
                f"Invalid agent.id {self.id!r}: must match pattern "
                f"{_SAFE_AGENT_ID_RE.pattern!r} (alphanumeric, underscores, hyphens)."
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
            ConfigError: If the file is not valid TOML (domain exception).
            pydantic.ValidationError: If the TOML data fails schema validation.
        """
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in agent config {path}: {exc}") from exc
        try:
            agent_data = data["agent"]
        except KeyError as exc:
            raise ConfigError(f"Missing [agent] section in {path}") from exc
        return cls.model_validate(agent_data)


# ---------------------------------------------------------------------------
# Team config models
# ---------------------------------------------------------------------------


class WorkerOverrideConfig(BaseModel):
    """Per-worker model override in a team TOML."""

    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class WorkerRef(BaseModel):
    """Reference to an agent within a team, with optional model override."""

    agent_id: str
    model: WorkerOverrideConfig = Field(default_factory=WorkerOverrideConfig)


class TeamProfileRoleConfig(BaseModel):
    """Per-role assignment overlay inside a model profile.

    Keyed by worker ``agent_id`` in the profile's ``roles`` map; carries the same
    provider/capability/fallback overlay shape as a ``[[team.workers]]`` override.
    A field left unset falls through the normal precedence chain unchanged,
    so a partial overlay only redirects the fields it names.
    """

    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class TeamProfileConfig(BaseModel):
    """A named whole-team model profile.

    Declared as ``[team.profiles.<id>]`` in team TOML. ``roles`` maps a worker
    ``agent_id`` to its overlay; roles absent from the profile fall through the
    normal precedence chain unchanged, so an empty ``roles`` map is exactly the
    implicit ``team-defaults`` profile. A selected profile is the topmost
    precedence layer (profile > worker override > agent TOML > team defaults).
    """

    display_name: str = ""
    description: str = ""
    roles: dict[str, TeamProfileRoleConfig] = Field(default_factory=dict)


class TeamHarnessConfig(BaseModel):
    """Declared agent-harness composition for a team preset.

    Declared as ``[team.harness]`` in team TOML. ``required_surfaces`` names the
    harness surfaces a run's workspace must carry (a subset of
    :data:`DEFAULT_AUTHORING_SURFACES`); ``role_skills`` maps a worker
    ``agent_id`` to the skills that role must have provisioned; ``mcp_servers``
    names the MCP servers injected into the run's agent sessions. An omitted
    ``required_surfaces`` defaults to all five surfaces, so a bare
    ``[team.harness]`` block is the full authoring harness plus any declared
    skills and MCP servers. Absence of the block entirely is handled by
    :meth:`TeamConfig.effective_harness`.
    """

    required_surfaces: list[str] = Field(
        default_factory=lambda: list(DEFAULT_AUTHORING_SURFACES)
    )
    role_skills: dict[str, list[str]] = Field(default_factory=dict)
    mcp_servers: list[str] = Field(default_factory=list)
    authoring_bridge: bool = False
    """Arm the per-run engine authoring bridge for this preset's CLI-coder agents.

    When ``true`` the run builds an :class:`AuthoringToolBinding` per worker and
    surfaces the engine's propose/read tools through the same isolated config
    home the declared ``mcp_servers`` ride (S18 admission channel). It is the
    agent-INITIATED authoring path for CLI-coder presets; document-authoring
    topologies (``research_adr``) author through the in-process graph submitter
    and must NOT set it — that contradiction is rejected in
    :meth:`TeamConfig` validation.
    """

    @model_validator(mode="after")
    def validate_surfaces(self) -> "TeamHarnessConfig":
        """Reject any surface name outside the known five (typo-proofing)."""
        unknown = [
            s for s in self.required_surfaces if s not in DEFAULT_AUTHORING_SURFACES
        ]
        if unknown:
            raise ConfigError(
                f"Unknown harness surface(s) {sorted(unknown)!r}; valid surfaces "
                f"are {list(DEFAULT_AUTHORING_SURFACES)!r}."
            )
        return self

    def skills_for(self, agent_id: str) -> list[str]:
        """Return the skills declared for one worker role (empty when none)."""
        return list(self.role_skills.get(agent_id, ()))

    def all_required_skills(self) -> list[str]:
        """Return every declared role skill, de-duplicated in first-seen order."""
        seen: dict[str, None] = {}
        for skills in self.role_skills.values():
            for skill in skills:
                seen.setdefault(skill, None)
        return list(seen)


class ResearchThreadSpec(BaseModel):
    """A single research thread for the ``research_adr`` diverge stage.

    Each spec becomes one parallel researcher branch in the Send-based fan-out.
    ``thread_id`` names the branch and is recorded on every finding it produces;
    ``topic`` and ``instructions`` scope the branch's research assignment.
    """

    thread_id: str
    topic: str = ""
    instructions: str = ""


class TopologyConfig(BaseModel):
    """LangGraph graph structure declaration.

    ``type`` selects the compilation strategy:
    - ``star``: supervisor routes dynamically to any worker.
    - ``pipeline``: fixed sequential chain, no supervisor needed.
    - ``pipeline_loop``: sequential chain where the loop_node's output
      triggers a conditional back-edge.
    - ``research_adr``: the document phase machine -- a Send-based research
      diverge stage joins into synthesis, each document phase guarded by a human
      approval gate.
    """

    # Use TopologyType enum for membership validation instead of string comparison
    type: TopologyType
    order: list[str] = Field(default_factory=list)
    loop_node: str | None = None
    # max_loops range validated; must be between 1 and 100 inclusive
    max_loops: int = Field(default=3, ge=1, le=100)
    # research_adr fan-out: one researcher branch per spec. Empty is permitted
    # and compiles to a single default branch; declare specs for real N-way
    # parallel research.
    research_threads: list[ResearchThreadSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self) -> "TopologyConfig":
        """Validate topology-specific required fields."""
        if (
            self.type in (TopologyType.PIPELINE, TopologyType.PIPELINE_LOOP)
            and not self.order
        ):
            raise ValueError(f"topology.order is required for type={self.type!r}")
        if self.type == TopologyType.PIPELINE_LOOP and self.loop_node is None:
            raise ValueError("topology.loop_node is required for type='pipeline_loop'")
        if (
            self.type == TopologyType.PIPELINE_LOOP
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
    """Team-wide fallback model binding (model resolution)."""

    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class TeamPermissionsConfig(BaseModel):
    """Team-level permission defaults."""

    auto_approve: bool = False


class TeamPersonaConfig(BaseModel):
    """Team-level supervisor persona overrides."""

    directive: str | None = None
    supervisor_display_name: str | None = None


class TeamGraphConfig(BaseModel):
    """Team-level graph execution settings."""

    step_timeout_seconds: int | None = None
    recursion_limit: int = Field(default=25, ge=1, le=500)


class TeamConfig(BaseModel):
    """Full configuration for a team preset.

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
    permissions: TeamPermissionsConfig = Field(default_factory=TeamPermissionsConfig)
    persona: TeamPersonaConfig = Field(default_factory=TeamPersonaConfig)
    graph: TeamGraphConfig = Field(default_factory=TeamGraphConfig)
    profiles: dict[str, TeamProfileConfig] = Field(default_factory=dict)
    harness: TeamHarnessConfig | None = None

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

    @model_validator(mode="after")
    def validate_profiles(self) -> "TeamConfig":
        """Eagerly validate profile ids and per-role overlay keys.

        Raises ``ConfigError`` (not a plain ``ValueError``) so an unknown role
        in a profile is a first-class configuration failure at load time: every
        overlay key must name a declared ``[[team.workers]]`` agent id, profile
        ids must be safe slugs, and the reserved ``team-defaults`` id may not
        carry role overlays (it is the implicit empty overlay).
        """
        worker_ids = {w.agent_id for w in self.workers}
        for profile_id, profile in self.profiles.items():
            if not _SAFE_AGENT_ID_RE.match(profile_id):
                raise ConfigError(
                    f"Invalid profile id {profile_id!r} in team {self.id!r}: must "
                    f"match pattern {_SAFE_AGENT_ID_RE.pattern!r}."
                )
            if profile_id == DEFAULT_PROFILE_ID and profile.roles:
                raise ConfigError(
                    f"The reserved {DEFAULT_PROFILE_ID!r} profile in team "
                    f"{self.id!r} must not declare role overlays; it is the "
                    "implicit empty overlay."
                )
            for role_key in profile.roles:
                if role_key not in worker_ids:
                    raise ConfigError(
                        f"Profile {profile_id!r} in team {self.id!r} overlays "
                        f"unknown role {role_key!r}; declared team workers are "
                        f"{sorted(worker_ids)!r}."
                    )
        return self

    @model_validator(mode="after")
    def validate_harness(self) -> "TeamConfig":
        """Every ``[team.harness].role_skills`` key must be a declared worker.

        Mirrors ``validate_profiles``: a role-skills key naming an agent the team
        does not run is a first-class config failure, not a silently ignored map
        entry (declared composition is enforced).
        """
        if self.harness is None:
            return self
        worker_ids = {w.agent_id for w in self.workers}
        for role_key in self.harness.role_skills:
            if role_key not in worker_ids:
                raise ConfigError(
                    f"Harness in team {self.id!r} declares skills for unknown "
                    f"role {role_key!r}; declared team workers are "
                    f"{sorted(worker_ids)!r}."
                )
        if self.harness.authoring_bridge and self.is_document_authoring:
            raise ConfigError(
                f"Harness in team {self.id!r} sets authoring_bridge=true on a "
                f"document-authoring topology ({self.topology.type.value!r}); the "
                "engine authoring bridge is the agent-initiated path for CLI-coder "
                "presets, while document-authoring topologies author through the "
                "in-process graph submitter. Remove authoring_bridge or use a "
                "coding topology."
            )
        return self

    @property
    def default_profile_id(self) -> str:
        """The default model profile id (always the implicit team-defaults)."""
        return DEFAULT_PROFILE_ID

    @property
    def is_document_authoring(self) -> bool:
        """Whether this preset authors vault documents through engine proposals.

        The document-authoring topologies are defined once in the authoring
        contract; the agent-harness contract applies to their writer roles.
        """
        return is_document_authoring_topology(self.topology.type)

    def effective_harness(self) -> TeamHarnessConfig | None:
        """Return the run's agent harness, defaulting authoring presets when absent.

        A declared ``[team.harness]`` block is returned verbatim. When no block is
        declared, a document-authoring preset gets the DEFAULT authoring harness
        (all five surfaces required, no extra skills or MCP servers), while a
        non-authoring preset has no harness requirement and returns ``None``
        (absence means the default authoring harness for writer roles).
        """
        if self.harness is not None:
            return self.harness
        if self.is_document_authoring:
            return TeamHarnessConfig()
        return None

    def effective_profiles(self) -> dict[str, TeamProfileConfig]:
        """Return declared profiles plus the implicit ``team-defaults`` profile.

        The implicit team-defaults profile is always present as the empty
        overlay; a team that declares its own ``team-defaults`` block (for a
        custom display name or description) overrides the injected default.
        """
        profiles: dict[str, TeamProfileConfig] = {
            DEFAULT_PROFILE_ID: TeamProfileConfig(
                display_name=DEFAULT_PROFILE_DISPLAY_NAME,
                description=DEFAULT_PROFILE_DESCRIPTION,
            )
        }
        profiles.update(self.profiles)
        return profiles

    @classmethod
    def from_toml(cls, path: Path) -> "TeamConfig":
        """Load and validate a TeamConfig from a TOML file.

        Args:
            path: Path to the ``.toml`` file containing a ``[team]`` section.

        Returns:
            Validated ``TeamConfig`` instance.

        Raises:
            ConfigError: If the file is not valid TOML (domain exception).
            pydantic.ValidationError: If the TOML data fails schema validation.
        """
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in team config {path}: {exc}") from exc
        try:
            team_data = data["team"]
        except KeyError as exc:
            raise ConfigError(f"Missing [team] section in {path}") from exc
        return cls.model_validate(team_data)


# ---------------------------------------------------------------------------
# Config discovery helpers
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
    # Validate agent_id before using it in path construction to prevent
    # path traversal attacks (e.g. agent_id="../../etc/passwd").
    if not _SAFE_AGENT_ID_RE.match(agent_id):
        raise ConfigError(
            f"Invalid agent_id {agent_id!r}: must match pattern "
            r"[a-zA-Z_][a-zA-Z0-9_\-]{{0,62}} (alphanumeric, underscores, hyphens)."
        )

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
    if not _SAFE_AGENT_ID_RE.match(team_id):
        raise ConfigError(
            f"Invalid team_id {team_id!r}: must match pattern "
            r"[a-zA-Z_][a-zA-Z0-9_\-]{{0,62}}."
        )

    candidates: list[Path] = []
    if workspace_root is not None:
        candidates.append(workspace_root / ".vaultspec" / "teams" / f"{team_id}.toml")
    candidates.append(_PRESET_TEAMS_DIR / f"{team_id}.toml")

    for path in candidates:
        if path.is_file():
            return TeamConfig.from_toml(path)

    raise TeamConfigNotFoundError(team_id)
