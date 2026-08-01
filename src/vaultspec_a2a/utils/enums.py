"""Utility enums and constants for the vaultspec-a2a library."""

from enum import IntEnum, StrEnum

__all__ = [
    "AcpRequestId",
    "CodexWebSearchMode",
    "Environment",
    "LogLevel",
]


class LogLevel(StrEnum):
    """Standard logging levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Environment(StrEnum):
    """Deployment environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class CodexWebSearchMode(StrEnum):
    """The four values Codex's top-level ``web_search`` config key accepts.

    Not a local vocabulary: these are the CLI's own variants, and it validates
    them itself - an unrecognised value is refused at config load with
    ``unknown variant ... expected one of `disabled`, `cached`, `indexed`,
    `live` in `web_search```. The names are a served contract asserted against
    the installed CLI rather than pinned by a version constraint (the house
    no-pinning rule); the Codex config-home entrypoint test is what detects
    upstream drift.

    ``CACHED`` reaches a provider-maintained index and makes NO outbound request
    from the agent host; ``INDEXED`` permits external access only through
    index-gated results; ``LIVE`` is unrestricted retrieval; ``DISABLED`` is off.

    It lives here, beside :class:`AcpRequestId`, rather than beside the renderer
    that emits it, because settings validation needs the type at import time and
    the reverse edge - configuration importing a provider - is the dependency the
    providers package breaks with a lazy import.
    """

    DISABLED = "disabled"
    CACHED = "cached"
    INDEXED = "indexed"
    LIVE = "live"


class AcpRequestId(IntEnum):
    """Reserved JSON-RPC identifiers for ACP Control Plane operations."""

    INITIALIZE = 1000
    SESSION_SETUP = 1001  # Handles session/new and session/load
    SESSION_PROMPT = 1002
    AUTHENTICATE = 1003
    SESSION_FORK = 1004
    SESSION_LIST = 1005
    SESSION_SET_MODE = 1006
    SESSION_SET_MODEL = 1007
    SESSION_SET_CONFIG_OPTION = 1008
    SESSION_CANCEL = 1009
