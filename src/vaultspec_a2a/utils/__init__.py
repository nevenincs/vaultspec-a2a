"""Collect narrow utilities shared across runtime packages.

Utilities cover enum handling, bearer-token verification, logging, and process
termination. Some helpers support public integration points, while others remain
internal implementation tools.

Prefer the owning utility module over broad facade imports. Primary consumers
include :mod:`vaultspec_a2a.api`, :mod:`vaultspec_a2a.control`,
:mod:`vaultspec_a2a.providers`, and :mod:`vaultspec_a2a.worker`.
"""

from .enums import AcpRequestId as AcpRequestId
from .enums import Environment as Environment
from .enums import LogLevel as LogLevel
from .ipc_auth import BearerVerdict as BearerVerdict
from .ipc_auth import verify_internal_bearer as verify_internal_bearer
from .logging import configure_logging as configure_logging
from .logging import reconfigure_console_utf8 as reconfigure_console_utf8
from .process import kill_pid_tree_async as kill_pid_tree_async
from .version import package_version as package_version

__all__ = [
    "AcpRequestId",
    "BearerVerdict",
    "Environment",
    "LogLevel",
    "configure_logging",
    "kill_pid_tree_async",
    "package_version",
    "reconfigure_console_utf8",
    "verify_internal_bearer",
]
