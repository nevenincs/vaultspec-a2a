"""LLM provider abstractions and ACP chat model.

Facade re-exporting all public types from the ``vaultspec_a2a.providers`` subpackage.
Consumers should import from this module rather than reaching into
sub-modules directly::

    from vaultspec_a2a.providers import AcpChatModel, ProviderFactory
"""

import importlib

from .acp_exceptions import AcpAuthError as AcpAuthError
from .acp_exceptions import AcpError as AcpError
from .acp_exceptions import AcpErrorCode as AcpErrorCode
from .acp_exceptions import AcpPromptError as AcpPromptError
from .acp_exceptions import AcpProtocolError as AcpProtocolError
from .acp_exceptions import AcpSessionError as AcpSessionError


# Lazy imports to break circular dependency:
#   providers.acp_chat_model -> core.team_config -> core.__init__
#   -> core.graph -> providers.factory -> providers.acp_chat_model
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
