"""Expose chat-model providers and provider construction.

Agent Client Protocol (ACP) exceptions load eagerly.
:class:`vaultspec_a2a.providers.acp_chat_model.AcpChatModel`,
:class:`vaultspec_a2a.providers.mock_chat_model.MockChatModel`, and
:class:`vaultspec_a2a.providers.factory.ProviderFactory` load lazily.

The lazy boundary breaks the providers, team, and graph import cycle. It also
keeps heavyweight implementation modules unloaded until a caller requests
them. Provider configuration resolves the applicable configuration home.

Providers implement :mod:`vaultspec_a2a.graph.protocols` for
:mod:`vaultspec_a2a.team` graphs and :mod:`vaultspec_a2a.worker` execution.
"""

import importlib

from .acp_exceptions import AcpAuthError as AcpAuthError
from .acp_exceptions import AcpError as AcpError
from .acp_exceptions import AcpErrorCode as AcpErrorCode
from .acp_exceptions import AcpPromptError as AcpPromptError
from .acp_exceptions import AcpProtocolError as AcpProtocolError
from .acp_exceptions import AcpSessionError as AcpSessionError

# Lazy imports to break circular dependency:
#   providers.acp_chat_model -> team.team_config -> graph.compiler
#   -> providers.factory -> providers.acp_chat_model
_LAZY_IMPORTS = {
    "AcpChatModel": ".acp_chat_model",
    "MockChatModel": ".mock_chat_model",
    "ProviderFactory": ".factory",
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
    "AcpAuthError",
    "AcpChatModel",
    "AcpError",
    "AcpErrorCode",
    "AcpPromptError",
    "AcpProtocolError",
    "AcpSessionError",
    "MockChatModel",
    "ProviderFactory",
]
