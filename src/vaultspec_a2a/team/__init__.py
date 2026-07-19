"""Expose canonical team, agent, and topology configuration.

Public Pydantic classes in :mod:`vaultspec_a2a.team.team_config` describe
executable teams and their agents. Preset discovery and loading turn stored
definitions into that canonical configuration.

:mod:`vaultspec_a2a.graph` compiles team topology.
:mod:`vaultspec_a2a.providers` supplies agent models.
:mod:`vaultspec_a2a.worker` executes the compiled team.
"""

from .team_config import (
    AgentCapabilitiesConfig as AgentCapabilitiesConfig,
)
from .team_config import (
    AgentConfig as AgentConfig,
)
from .team_config import (
    AgentModelConfig as AgentModelConfig,
)
from .team_config import (
    AgentPermissionsConfig as AgentPermissionsConfig,
)
from .team_config import (
    AgentPersonaConfig as AgentPersonaConfig,
)
from .team_config import (
    SupervisorConfig as SupervisorConfig,
)
from .team_config import (
    TeamConfig as TeamConfig,
)
from .team_config import (
    TeamDefaultsConfig as TeamDefaultsConfig,
)
from .team_config import (
    TeamGraphConfig as TeamGraphConfig,
)
from .team_config import (
    TeamPermissionsConfig as TeamPermissionsConfig,
)
from .team_config import (
    TeamPersonaConfig as TeamPersonaConfig,
)
from .team_config import (
    TopologyConfig as TopologyConfig,
)
from .team_config import (
    TopologyType as TopologyType,
)
from .team_config import (
    WorkerOverrideConfig as WorkerOverrideConfig,
)
from .team_config import (
    WorkerRef as WorkerRef,
)
from .team_config import (
    discover_team_preset_ids as discover_team_preset_ids,
)
from .team_config import (
    load_agent_config as load_agent_config,
)
from .team_config import (
    load_team_config as load_team_config,
)

__all__ = [
    "AgentCapabilitiesConfig",
    "AgentConfig",
    "AgentModelConfig",
    "AgentPermissionsConfig",
    "AgentPersonaConfig",
    "SupervisorConfig",
    "TeamConfig",
    "TeamDefaultsConfig",
    "TeamGraphConfig",
    "TeamPermissionsConfig",
    "TeamPersonaConfig",
    "TopologyConfig",
    "TopologyType",
    "WorkerOverrideConfig",
    "WorkerRef",
    "discover_team_preset_ids",
    "load_agent_config",
    "load_team_config",
]
