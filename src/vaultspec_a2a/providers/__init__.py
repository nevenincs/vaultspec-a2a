"""Expose chat-model providers and provider construction.

Agent Client Protocol (ACP) exceptions load eagerly.
:class:`vaultspec_a2a.providers.acp_chat_model.AcpChatModel`,
:class:`vaultspec_a2a.providers.factory.ProviderFactory`, and the in-process
lane-plugin seam of :mod:`vaultspec_a2a.providers.lane_registry` load lazily.

The lazy boundary breaks the providers, team, and graph import cycle. It also
keeps heavyweight implementation modules unloaded until a caller requests
them. Provider configuration resolves the applicable configuration home.

Providers implement :mod:`vaultspec_a2a.graph.protocols` for
:mod:`vaultspec_a2a.team` graphs and :mod:`vaultspec_a2a.worker` execution.
"""

import importlib
from typing import TYPE_CHECKING

from ._json_contract import JsonObject as JsonObject
from ._json_contract import JsonValue as JsonValue
from .acp_exceptions import AcpAuthError as AcpAuthError
from .acp_exceptions import AcpError as AcpError
from .acp_exceptions import AcpErrorCode as AcpErrorCode
from .acp_exceptions import AcpPromptCancelledError as AcpPromptCancelledError
from .acp_exceptions import AcpPromptError as AcpPromptError
from .acp_exceptions import AcpSessionError as AcpSessionError
from .warmup import warm_model_imports as warm_model_imports

if TYPE_CHECKING:
    from .acp_chat_model import AcpChatModel as AcpChatModel
    from .cli_resolution import SYSTEM_CLI_LANES as SYSTEM_CLI_LANES
    from .cli_resolution import proof_cli_name as proof_cli_name
    from .factory import ProviderFactory as ProviderFactory
    from .lane_registry import LanePluginError as LanePluginError
    from .lane_registry import LaneRegistration as LaneRegistration
    from .lane_registry import LaneRegistry as LaneRegistry

# Lazy imports to break circular dependency:
#   providers.acp_chat_model -> team.team_config -> graph.compiler
#   -> providers.factory -> providers.acp_chat_model
_LAZY_IMPORTS = {
    "AcpChatModel": ".acp_chat_model",
    "LanePluginError": ".lane_registry",
    "LaneRegistration": ".lane_registry",
    "LaneRegistry": ".lane_registry",
    "ProviderFactory": ".factory",
    "SYSTEM_CLI_LANES": ".cli_resolution",
    "proof_cli_name": ".cli_resolution",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "SYSTEM_CLI_LANES",
    "AcpAuthError",
    "AcpChatModel",
    "AcpError",
    "AcpErrorCode",
    "AcpPromptCancelledError",
    "AcpPromptError",
    "AcpSessionError",
    "JsonObject",
    "JsonValue",
    "LanePluginError",
    "LaneRegistration",
    "LaneRegistry",
    "ProviderFactory",
    "proof_cli_name",
    "warm_model_imports",
]
