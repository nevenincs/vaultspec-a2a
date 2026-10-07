"""Collect narrow utilities shared across runtime packages.

Utilities cover enum handling, bearer-token headers and verification, logging,
secret redaction, contained process spawn and reap, link and regular-file
refusals, and process termination. Some helpers support public integration
points, while others remain internal implementation tools.

Consumers import the names exported here from this package root, never from the
owning utility module, so that module layout stays free to change. Primary
consumers include :mod:`vaultspec_a2a.api`, :mod:`vaultspec_a2a.control`,
:mod:`vaultspec_a2a.providers`, and :mod:`vaultspec_a2a.worker`.
"""

from ._file_checks import is_real_directory as is_real_directory
from ._file_checks import is_single_regular_file as is_single_regular_file
from ._file_checks import path_is_link_like as path_is_link_like
from ._process_tree import kill_pid_tree_async as kill_pid_tree_async
from .enums import AcpRequestId as AcpRequestId
from .enums import Environment as Environment
from .enums import LogLevel as LogLevel
from .ipc_auth import BearerVerdict as BearerVerdict
from .ipc_auth import bearer_header as bearer_header
from .ipc_auth import bearer_matches as bearer_matches
from .ipc_auth import verify_internal_bearer as verify_internal_bearer
from .logging import active_trace_ids as active_trace_ids
from .logging import configure_logging as configure_logging
from .logging import reconfigure_console_utf8 as reconfigure_console_utf8
from .process import ProcessContainment as ProcessContainment
from .process import ProcessContainmentError as ProcessContainmentError
from .process import reap_contained as reap_contained
from .process import spawn_contained as spawn_contained
from .process import spawn_contained_async as spawn_contained_async
from .redaction import is_secret_name as is_secret_name
from .redaction import redact_text as redact_text
from .redaction import redact_url as redact_url
from .version import package_version as package_version

__all__ = [
    "AcpRequestId",
    "BearerVerdict",
    "Environment",
    "LogLevel",
    "ProcessContainment",
    "ProcessContainmentError",
    "active_trace_ids",
    "bearer_header",
    "bearer_matches",
    "configure_logging",
    "is_real_directory",
    "is_secret_name",
    "is_single_regular_file",
    "kill_pid_tree_async",
    "package_version",
    "path_is_link_like",
    "reap_contained",
    "reconfigure_console_utf8",
    "redact_text",
    "redact_url",
    "spawn_contained",
    "spawn_contained_async",
    "verify_internal_bearer",
]
