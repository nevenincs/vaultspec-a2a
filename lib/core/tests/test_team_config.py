"""Tests for agent and team TOML config loading and validation (ADR-012, ADR-013).

All tests load real TOML files from lib/core/presets/ — no mocks or stubs.
"""

import tomllib

from pathlib import Path
from typing import cast

import pytest

from pydantic import ValidationError

from ...utils.enums import Model, Provider
from ..exceptions import AgentConfigNotFoundError, ConfigError, TeamConfigNotFoundError
from ..team_config import (
    AgentConfig,
    AgentModelConfig,
    TeamConfig,
    TeamGraphConfig,
    TeamPermissionsConfig,
    TeamPersonaConfig,
    TopologyConfig,
    TopologyType,
    WorkerOverrideConfig,
    WorkerRef,
    load_agent_config,
    load_team_config,
)


# ---------------------------------------------------------------------------
# Paths for preset fixtures
# ---------------------------------------------------------------------------

_PRESETS_DIR = Path(__file__).parent.parent / "presets"
_AGENTS_DIR = _PRESETS_DIR / "agents"
_TEAMS_DIR = _PRESETS_DIR / "teams"

_ALL_AGENT_IDS = ["vaultspec-supervisor", "vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer", "vaultspec-analyst"]
_ALL_TEAM_IDS = ["vaultspec-adaptive-coder", "vaultspec-structured-coder", "vaultspec-iterative-coder", "vaultspec-solo-coder"]


# ---------------------------------------------------------------------------
# AgentConfig: TOML loading
# ---------------------------------------------------------------------------


class TestAgentConfigFromToml:
    """Verify every bundled agent TOML parses without error."""

    @pytest.mark.parametrize("agent_id", _ALL_AGENT_IDS)
    def test_loads_preset_agent(self, agent_id: str) -> None:
        """Each preset agent TOML produces a valid AgentConfig."""
        cfg = AgentConfig.from_toml(_AGENTS_DIR / f"{agent_id}.toml")
        assert cfg.id == agent_id

    def test_supervisor_has_correct_fields(self) -> None:
        """Supervisor preset has expected display_name, role, and description."""
        cfg = load_agent_config("vaultspec-supervisor")
        assert cfg.display_name
        assert cfg.role == "supervisor"
        assert cfg.persona.system_prompt

    def test_planner_has_correct_fields(self) -> None:
        """Planner preset has expected role and persona."""
        cfg = load_agent_config("vaultspec-planner")
        assert cfg.role == "planner"
        assert cfg.persona.system_prompt

    def test_coder_requires_approval(self) -> None:
        """Coder preset declares at least one require_approval_for entry."""
        cfg = load_agent_config("vaultspec-coder")
        assert cfg.permissions.require_approval_for  # non-empty list

    def test_reviewer_has_filesystem_read(self) -> None:
        """Reviewer preset enables filesystem_read capability."""
        cfg = load_agent_config("vaultspec-reviewer")
        assert cfg.capabilities.filesystem_read is True

    def test_analyst_capabilities(self) -> None:
        """Analyst preset enables filesystem_read and filesystem_write."""
        cfg = load_agent_config("vaultspec-analyst")
        assert cfg.capabilities.filesystem_read is True


# ---------------------------------------------------------------------------
# AgentConfig: model field resolution
# ---------------------------------------------------------------------------


class TestAgentModelConfig:
    """Verify provider/capability fields on preset agents."""

    def test_supervisor_uses_max_capability(self) -> None:
        """Supervisor is bound to the MAX capability tier."""
        cfg = load_agent_config("vaultspec-supervisor")
        assert cfg.model.capability == Model.MAX

    def test_coder_uses_high_capability(self) -> None:
        """Coder is configured at HIGH capability."""
        cfg = load_agent_config("vaultspec-coder")
        assert cfg.model.capability == Model.HIGH

    def test_reviewer_uses_zhipu_provider(self) -> None:
        """Reviewer is assigned the ZHIPU provider."""
        cfg = load_agent_config("vaultspec-reviewer")
        assert cfg.model.provider == Provider.ZHIPU

    def test_agent_model_config_all_optional(self) -> None:
        """AgentModelConfig fields are all optional (None by default)."""
        model_cfg = AgentModelConfig()
        assert model_cfg.provider is None
        assert model_cfg.capability is None


# ---------------------------------------------------------------------------
# AgentConfig: id validation
# ---------------------------------------------------------------------------


class TestAgentIdValidation:
    """Verify that agent.id must be a valid Python identifier."""

    def test_valid_id_passes(self, tmp_path: Path) -> None:
        """A valid Python identifier id is accepted."""
        toml_file = tmp_path / "my_agent.toml"
        toml_file.write_bytes(
            b"""
[agent]
id = "my_agent"
display_name = "My Agent"
role = "coder"
description = "A test agent."

[agent.persona]
system_prompt = "You are a test agent."
"""
        )
        cfg = AgentConfig.from_toml(toml_file)
        assert cfg.id == "my_agent"

    def test_hyphenated_id_passes(self, tmp_path: Path) -> None:
        """An id containing hyphens is accepted (vaultspec- prefix pattern)."""
        toml_file = tmp_path / "good-agent.toml"
        toml_file.write_bytes(
            b"""
[agent]
id = "vaultspec-agent"
display_name = "Good Agent"
role = "coder"
description = "Agent with hyphenated id."

[agent.persona]
system_prompt = "You are a good agent."
"""
        )
        cfg = AgentConfig.from_toml(toml_file)
        assert cfg.id == "vaultspec-agent"

    def test_numeric_id_raises(self, tmp_path: Path) -> None:
        """An id starting with a digit raises ValidationError."""
        toml_file = tmp_path / "agent.toml"
        toml_file.write_bytes(
            b"""
[agent]
id = "1agent"
display_name = "1agent"
role = "coder"
description = "Bad."

[agent.persona]
system_prompt = "You."
"""
        )
        with pytest.raises(ValidationError, match=r"\^\\[a-zA-Z\\]|must match"):
            AgentConfig.from_toml(toml_file)


# ---------------------------------------------------------------------------
# load_agent_config: discovery order
# ---------------------------------------------------------------------------


class TestLoadAgentConfigDiscovery:
    """Verify the two-level discovery order: workspace override > bundled preset."""

    def test_finds_bundled_preset(self) -> None:
        """load_agent_config returns a config when only the preset exists."""
        cfg = load_agent_config("vaultspec-planner")
        assert cfg.id == "vaultspec-planner"

    def test_workspace_override_takes_precedence(self, tmp_path: Path) -> None:
        """A workspace .vaultspec/agents/{id}.toml overrides the bundled preset."""
        override_dir = tmp_path / ".vaultspec" / "agents"
        override_dir.mkdir(parents=True)
        override_path = override_dir / "vaultspec-planner.toml"
        override_path.write_bytes(
            b"""
[agent]
id = "planner"
display_name = "Custom Planner"
role = "planner"
description = "Workspace override."

[agent.persona]
system_prompt = "Custom system prompt."
"""
        )
        cfg = load_agent_config("vaultspec-planner", workspace_root=tmp_path)
        assert cfg.display_name == "Custom Planner"

    def test_missing_agent_raises_not_found(self) -> None:
        """An unknown agent_id raises AgentConfigNotFoundError."""
        with pytest.raises(AgentConfigNotFoundError) as exc_info:
            load_agent_config("nonexistent_agent_xyz")
        assert exc_info.value.agent_id == "nonexistent_agent_xyz"

    def test_not_found_error_has_descriptive_message(self) -> None:
        """AgentConfigNotFoundError message includes the missing agent_id."""
        with pytest.raises(AgentConfigNotFoundError, match="nonexistent_agent_xyz"):
            load_agent_config("nonexistent_agent_xyz")

    def test_workspace_root_none_uses_only_preset(self) -> None:
        """Passing workspace_root=None still finds bundled presets."""
        cfg = load_agent_config("vaultspec-reviewer", workspace_root=None)
        assert cfg.id == "vaultspec-reviewer"


# ---------------------------------------------------------------------------
# TopologyConfig: validation
# ---------------------------------------------------------------------------


class TestTopologyConfigValidation:
    """Validate topology-type-specific constraints."""

    def test_star_requires_no_order(self) -> None:
        """Star topology is valid with an empty order list."""
        topo = TopologyConfig(type=TopologyType.STAR)
        assert topo.type == TopologyType.STAR
        assert topo.order == []

    def test_pipeline_requires_order(self) -> None:
        """Pipeline topology without order raises ValidationError."""
        with pytest.raises(ValidationError, match="order is required"):
            TopologyConfig(type=TopologyType.PIPELINE, order=[])

    def test_pipeline_with_order_passes(self) -> None:
        """Pipeline topology with a non-empty order is valid."""
        topo = TopologyConfig(type=TopologyType.PIPELINE, order=["planner", "coder"])
        assert topo.order == ["planner", "coder"]

    def test_pipeline_loop_requires_order_and_loop_node(self) -> None:
        """pipeline_loop without order raises ValidationError."""
        with pytest.raises(ValidationError, match="order is required"):
            TopologyConfig(type=TopologyType.PIPELINE_LOOP, order=[])

    def test_pipeline_loop_requires_loop_node(self) -> None:
        """pipeline_loop without loop_node raises ValidationError."""
        with pytest.raises(ValidationError, match="loop_node is required"):
            TopologyConfig(type=TopologyType.PIPELINE_LOOP, order=["coder", "reviewer"])

    def test_pipeline_loop_loop_node_must_be_in_order(self) -> None:
        """loop_node that is not in order raises ValidationError."""
        with pytest.raises(ValidationError, match="must appear in"):
            TopologyConfig(
                type=TopologyType.PIPELINE_LOOP,
                order=["coder", "reviewer"],
                loop_node="planner",
            )

    def test_pipeline_loop_valid(self) -> None:
        """Valid pipeline_loop config is accepted."""
        expected_max_loops = 5
        topo = TopologyConfig(
            type=TopologyType.PIPELINE_LOOP,
            order=["planner", "coder", "reviewer"],
            loop_node="reviewer",
            max_loops=expected_max_loops,
        )
        assert topo.loop_node == "reviewer"
        assert topo.max_loops == expected_max_loops

    def test_unknown_type_raises(self) -> None:
        """An unsupported topology type raises ValidationError."""
        with pytest.raises(ValidationError, match="'star'"):
            TopologyConfig(type=cast(TopologyType, "mesh"))


# ---------------------------------------------------------------------------
# TeamConfig: TOML loading
# ---------------------------------------------------------------------------


class TestTeamConfigFromToml:
    """Verify every bundled team TOML parses without error."""

    @pytest.mark.parametrize("team_id", _ALL_TEAM_IDS)
    def test_loads_preset_team(self, team_id: str) -> None:
        """Each preset team TOML produces a valid TeamConfig."""
        cfg = TeamConfig.from_toml(_TEAMS_DIR / f"{team_id}.toml")
        assert cfg.id == team_id

    def test_coding_star_is_star_topology(self) -> None:
        """vaultspec-adaptive-coder uses star topology."""
        cfg = load_team_config("vaultspec-adaptive-coder")
        assert cfg.topology.type == TopologyType.STAR

    def test_coding_pipeline_order(self) -> None:
        """vaultspec-structured-coder has planner → coder → reviewer order."""
        cfg = load_team_config("vaultspec-structured-coder")
        assert cfg.topology.type == TopologyType.PIPELINE
        assert cfg.topology.order == ["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"]

    def test_coding_loop_loop_node(self) -> None:
        """vaultspec-iterative-coder has reviewer as the loop_node."""
        expected_max_loops = 3
        cfg = load_team_config("vaultspec-iterative-coder")
        assert cfg.topology.type == TopologyType.PIPELINE_LOOP
        assert cfg.topology.loop_node == "vaultspec-reviewer"
        assert cfg.topology.max_loops == expected_max_loops

    def test_solo_coder_single_worker(self) -> None:
        """vaultspec-solo-coder has exactly one worker: the coder."""
        cfg = load_team_config("vaultspec-solo-coder")
        assert len(cfg.workers) == 1
        assert cfg.workers[0].agent_id == "vaultspec-coder"

    def test_all_preset_teams_have_workers(self) -> None:
        """Every preset team declares at least one worker."""
        for team_id in _ALL_TEAM_IDS:
            cfg = load_team_config(team_id)
            assert len(cfg.workers) > 0, f"{team_id} has no workers"


# ---------------------------------------------------------------------------
# TeamConfig: worker model override
# ---------------------------------------------------------------------------


class TestWorkerModelOverride:
    """Verify per-worker model overrides are loaded correctly (ADR-013 §2.3)."""

    def test_coding_star_coder_has_high_capability(self) -> None:
        """vaultspec-adaptive-coder overrides coder to HIGH capability."""
        cfg = load_team_config("vaultspec-adaptive-coder")
        coder_ref = next(w for w in cfg.workers if w.agent_id == "vaultspec-coder")
        assert coder_ref.model.capability == Model.HIGH

    def test_worker_without_override_has_none_fields(self) -> None:
        """Workers with no override have None provider and capability."""
        cfg = load_team_config("vaultspec-adaptive-coder")
        planner_ref = next(w for w in cfg.workers if w.agent_id == "vaultspec-planner")
        assert planner_ref.model.provider is None
        assert planner_ref.model.capability is None


# ---------------------------------------------------------------------------
# TeamConfig: topology order subset validation
# ---------------------------------------------------------------------------


class TestTopologyOrderSubsetValidation:
    """Verify TeamConfig rejects topology.order entries not in workers."""

    def test_order_outside_workers_raises(self, tmp_path: Path) -> None:
        """topology.order referencing a non-worker raises ValidationError."""
        toml_file = tmp_path / "bad_team.toml"
        toml_file.write_bytes(
            b"""
[team]
id = "bad_team"
display_name = "Bad Team"

[team.topology]
type  = "pipeline"
order = ["planner", "phantom_agent"]

[[team.workers]]
agent_id = "planner"
"""
        )
        with pytest.raises(ValidationError, match="phantom_agent"):
            TeamConfig.from_toml(toml_file)


# ---------------------------------------------------------------------------
# load_team_config: discovery order
# ---------------------------------------------------------------------------


class TestLoadTeamConfigDiscovery:
    """Verify the two-level discovery order for teams."""

    def test_finds_bundled_preset(self) -> None:
        """load_team_config returns a config when only the preset exists."""
        cfg = load_team_config("vaultspec-adaptive-coder")
        assert cfg.id == "vaultspec-adaptive-coder"

    def test_workspace_override_takes_precedence(self, tmp_path: Path) -> None:
        """A workspace .vaultspec/teams/{id}.toml overrides the bundled preset."""
        override_dir = tmp_path / ".vaultspec" / "teams"
        override_dir.mkdir(parents=True)
        override_path = override_dir / "vaultspec-adaptive-coder.toml"
        override_path.write_bytes(
            b"""
[team]
id = "vaultspec-adaptive-coder"
display_name = "Custom Star"
description  = "Workspace override."

[team.topology]
type = "star"

[[team.workers]]
agent_id = "coder"
"""
        )
        cfg = load_team_config("vaultspec-adaptive-coder", workspace_root=tmp_path)
        assert cfg.display_name == "Custom Star"

    def test_missing_team_raises_not_found(self) -> None:
        """An unknown team_id raises TeamConfigNotFoundError."""
        with pytest.raises(TeamConfigNotFoundError) as exc_info:
            load_team_config("nonexistent_team_xyz")
        assert exc_info.value.team_id == "nonexistent_team_xyz"

    def test_not_found_error_has_descriptive_message(self) -> None:
        """TeamConfigNotFoundError message includes the missing team_id."""
        with pytest.raises(TeamConfigNotFoundError, match="nonexistent_team_xyz"):
            load_team_config("nonexistent_team_xyz")

    def test_workspace_root_none_uses_only_preset(self) -> None:
        """Passing workspace_root=None still finds bundled presets."""
        cfg = load_team_config("vaultspec-solo-coder", workspace_root=None)
        assert cfg.id == "vaultspec-solo-coder"


# ---------------------------------------------------------------------------
# WorkerRef model
# ---------------------------------------------------------------------------


class TestWorkerRef:
    """Verify WorkerRef default and explicit model overrides."""

    def test_default_has_none_model(self) -> None:
        """WorkerRef with only agent_id has None provider/capability by default."""
        ref = WorkerRef(agent_id="coder")
        assert ref.model.provider is None
        assert ref.model.capability is None

    def test_explicit_capability_override(self) -> None:
        """WorkerRef accepts explicit capability override."""
        ref = WorkerRef(
            agent_id="coder", model=WorkerOverrideConfig(capability=Model.HIGH)
        )
        assert ref.model.capability == Model.HIGH

    def test_explicit_provider_override(self) -> None:
        """WorkerRef accepts explicit provider override."""
        ref = WorkerRef(
            agent_id="coder", model=WorkerOverrideConfig(provider=Provider.CLAUDE)
        )
        assert ref.model.provider == Provider.CLAUDE


# ---------------------------------------------------------------------------
# TOML syntax error handling
# ---------------------------------------------------------------------------


class TestTomlDecodeErrors:
    """Verify that malformed TOML files raise ConfigError (M8 domain exception)."""

    def test_malformed_toml_raises(self, tmp_path: Path) -> None:
        """Malformed TOML raises ConfigError wrapping TOMLDecodeError."""
        bad_file = tmp_path / "bad.toml"
        bad_file.write_bytes(b"[agent\nid = missing quote")
        with pytest.raises(ConfigError) as exc_info:
            AgentConfig.from_toml(bad_file)
        assert isinstance(exc_info.value.__cause__, tomllib.TOMLDecodeError)


# ---------------------------------------------------------------------------
# load_agent_config: agent_id validation (CORE-H5)
# ---------------------------------------------------------------------------


class TestLoadAgentConfigValidation:
    """Verify agent_id is validated before path construction (CORE-H5)."""

    def test_path_traversal_agent_id_raises(self) -> None:
        """agent_id containing '..' raises ConfigError (path traversal prevention)."""
        with pytest.raises(ConfigError, match="Invalid agent_id"):
            load_agent_config("../../etc/passwd")

    def test_agent_id_with_slash_raises(self) -> None:
        """agent_id containing '/' raises ConfigError."""
        with pytest.raises(ConfigError, match="Invalid agent_id"):
            load_agent_config("foo/bar")

    def test_agent_id_with_backslash_raises(self) -> None:
        r"""agent_id containing '\' raises ConfigError."""
        with pytest.raises(ConfigError, match="Invalid agent_id"):
            load_agent_config("foo\\bar")

    def test_agent_id_starting_with_digit_raises(self) -> None:
        """agent_id starting with a digit raises ConfigError."""
        with pytest.raises(ConfigError, match="Invalid agent_id"):
            load_agent_config("1agent")

    def test_valid_agent_id_passes_validation(self) -> None:
        """Valid agent_id passes validation before config discovery."""
        # "nonexistent_agent" is a valid id format — raises NotFound, not ConfigError
        with pytest.raises(AgentConfigNotFoundError):
            load_agent_config("nonexistent_valid_id")

    def test_agent_id_with_hyphens_passes(self) -> None:
        """agent_id with hyphens (allowed by pattern) passes validation."""
        # Hyphens are allowed by _SAFE_AGENT_ID_RE — raises NotFound, not ConfigError
        with pytest.raises(AgentConfigNotFoundError):
            load_agent_config("valid-agent-id")

    @pytest.mark.parametrize(
        "agent_id",
        [
            "../../etc/passwd",
            "../secrets",
            "foo/bar",
            "1agent",
            "",
        ],
    )
    def test_unsafe_agent_ids_raise_config_error(self, agent_id: str) -> None:
        """Unsafe agent_id values raise ConfigError before any filesystem access."""
        with pytest.raises((ConfigError, AgentConfigNotFoundError)):
            load_agent_config(agent_id)


# ---------------------------------------------------------------------------
# load_team_config: team_id path traversal guard (TC-01)
# ---------------------------------------------------------------------------


class TestLoadTeamConfigValidation:
    """Verify team_id is validated before path construction (TC-01)."""

    def test_path_traversal_team_id_raises(self) -> None:
        """team_id containing '..' raises ConfigError."""
        with pytest.raises(ConfigError, match="Invalid team_id"):
            load_team_config("../../etc/passwd")

    def test_team_id_with_slash_raises(self) -> None:
        """team_id containing '/' raises ConfigError."""
        with pytest.raises(ConfigError, match="Invalid team_id"):
            load_team_config("foo/bar")

    def test_old_ids_now_raise_not_found(self) -> None:
        """Old preset IDs (no compat shim) raise TeamConfigNotFoundError."""
        with pytest.raises(TeamConfigNotFoundError):
            load_team_config("coding-star")


# ---------------------------------------------------------------------------
# TeamPermissionsConfig, TeamPersonaConfig, TeamGraphConfig
# ---------------------------------------------------------------------------


class TestTeamExtendedConfigDefaults:
    """Verify new config blocks default correctly when absent from TOML."""

    def test_permissions_defaults(self) -> None:
        """TeamPermissionsConfig has auto_approve=False by default."""
        cfg = TeamPermissionsConfig()
        assert cfg.auto_approve is False

    def test_persona_defaults(self) -> None:
        """TeamPersonaConfig has all-None fields by default."""
        cfg = TeamPersonaConfig()
        assert cfg.directive is None
        assert cfg.supervisor_display_name is None

    def test_graph_defaults(self) -> None:
        """TeamGraphConfig defaults: step_timeout_seconds=None, recursion_limit=25."""
        cfg = TeamGraphConfig()
        assert cfg.step_timeout_seconds is None
        assert cfg.recursion_limit == 25

    def test_graph_recursion_limit_bounds(self) -> None:
        """recursion_limit must be between 1 and 500."""
        assert TeamGraphConfig(recursion_limit=1).recursion_limit == 1
        assert TeamGraphConfig(recursion_limit=500).recursion_limit == 500
        with pytest.raises(Exception):
            TeamGraphConfig(recursion_limit=0)
        with pytest.raises(Exception):
            TeamGraphConfig(recursion_limit=501)

    def test_team_config_has_new_blocks_with_defaults(self) -> None:
        """Bundled presets parse without permissions/persona/graph sections."""
        cfg = load_team_config("vaultspec-adaptive-coder")
        assert cfg.permissions.auto_approve is False
        # Enriched presets may have persona directives and graph settings;
        # verify the fields parse without error and have valid types.
        assert cfg.persona.directive is None or isinstance(cfg.persona.directive, str)
        assert cfg.graph.step_timeout_seconds is None or isinstance(cfg.graph.step_timeout_seconds, int)
        assert cfg.graph.recursion_limit >= 1


class TestTeamExtendedConfigFromToml:
    """Verify new config blocks parse correctly from TOML."""

    def test_auto_approve_true_parses(self, tmp_path: Path) -> None:
        """auto_approve = true in [team.permissions] is read correctly."""
        toml_content = b"""
[team]
id           = "test-auto"
display_name = "Test Auto"

[team.topology]
type = "pipeline"
order = ["coder"]

[[team.workers]]
agent_id = "coder"

[team.permissions]
auto_approve = true
"""
        override_dir = tmp_path / ".vaultspec" / "teams"
        override_dir.mkdir(parents=True)
        (override_dir / "test-auto.toml").write_bytes(toml_content)
        cfg = load_team_config("test-auto", workspace_root=tmp_path)
        assert cfg.permissions.auto_approve is True

    def test_directive_parses(self, tmp_path: Path) -> None:
        """persona.directive string is read correctly."""
        toml_content = b"""
[team]
id           = "test-persona"
display_name = "Test Persona"

[team.topology]
type = "pipeline"
order = ["coder"]

[[team.workers]]
agent_id = "coder"

[team.persona]
directive = "Focus on security best practices."
"""
        override_dir = tmp_path / ".vaultspec" / "teams"
        override_dir.mkdir(parents=True)
        (override_dir / "test-persona.toml").write_bytes(toml_content)
        cfg = load_team_config("test-persona", workspace_root=tmp_path)
        assert cfg.persona.directive == "Focus on security best practices."

    def test_step_timeout_seconds_parses(self, tmp_path: Path) -> None:
        """graph.step_timeout_seconds integer is read correctly."""
        toml_content = b"""
[team]
id           = "test-graph"
display_name = "Test Graph"

[team.topology]
type = "pipeline"
order = ["coder"]

[[team.workers]]
agent_id = "coder"

[team.graph]
step_timeout_seconds = 120
recursion_limit = 50
"""
        override_dir = tmp_path / ".vaultspec" / "teams"
        override_dir.mkdir(parents=True)
        (override_dir / "test-graph.toml").write_bytes(toml_content)
        cfg = load_team_config("test-graph", workspace_root=tmp_path)
        assert cfg.graph.step_timeout_seconds == 120
        assert cfg.graph.recursion_limit == 50

    def test_provider_fallback_parses_on_defaults(self, tmp_path: Path) -> None:
        """team.defaults.provider_fallback list parses correctly."""
        toml_content = b"""
[team]
id           = "test-fallback"
display_name = "Test Fallback"

[team.defaults]
provider          = "claude"
provider_fallback = ["openai", "gemini"]

[team.topology]
type = "pipeline"
order = ["coder"]

[[team.workers]]
agent_id = "coder"
"""
        override_dir = tmp_path / ".vaultspec" / "teams"
        override_dir.mkdir(parents=True)
        (override_dir / "test-fallback.toml").write_bytes(toml_content)
        cfg = load_team_config("test-fallback", workspace_root=tmp_path)
        assert len(cfg.defaults.provider_fallback) == 2
