"""The Claude lane's own permission posture: settings, denies, and mode.

The spawned Claude CLI decides tool permissions itself. Three things therefore
have to be stated on the session rather than assumed: which settings the CLI is
allowed to read, which of its built-in tools a persona may not use at all, and
which permission mode an unattended run may run in. Each value here names a
surface of the pinned adapter and its SDK, so it is a contract with an installed
artefact rather than a preference.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..team.team_config import AgentConfig

__all__ = [
    "AUTONOMOUS_PERMISSION_MODE",
    "CLAUDE_DENIED_READ_PATHS",
    "CLAUDE_FILE_WRITE_TOOLS",
    "CLAUDE_PATH_RULE_TOOLS",
    "CLAUDE_TERMINAL_TOOLS",
    "MODE_CONFIG_OPTION_ID",
    "claude_disallowed_tools",
    "workspace_scoped_tool_rule",
]

# The CLI's own file-mutating built-ins. Read from the installed agent SDK's
# rule vocabulary (`filePatternTools`), minus the read-only members: these are
# the names a permission rule may carry, so they are also the names a deny rule
# has to carry to be enforced. A persona whose capabilities say it does not
# write the filesystem gets them denied outright, because clearing the ACP
# client capability alone denies nothing - the CLI's built-ins never travel over
# the client filesystem RPC the capability governs.
CLAUDE_FILE_WRITE_TOOLS: tuple[str, ...] = (
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
)

# The CLI's command-execution built-in and the background-task verbs that
# observe and stop what it started. `Bash` is the SDK's only bash-prefix rule
# tool; the others are the installed CLI's own aliases for reading and killing a
# background shell, denied with it so a terminal-less persona cannot reach the
# output of a command by another name.
CLAUDE_TERMINAL_TOOLS: tuple[str, ...] = (
    "Bash",
    "BashOutput",
    "KillShell",
    "KillBash",
)

# Absolute paths no run has business reading, denied as path rules on the read
# built-in. These are not a substitute for scoping reads to the workspace (see
# :func:`workspace_scoped_tool_rule`) - a blocklist never is - but they are the
# places where one mistake hands over the credentials the run itself spends, or
# the environment of a live process, so they are named rather than left to the
# scope rule alone. Written in the pinned SDK's rule syntax: the read tool takes
# a file pattern, and ``~`` is expanded by the CLI against the operator's home.
CLAUDE_DENIED_READ_PATHS: tuple[str, ...] = (
    "/proc/**",
    "~/.ssh/**",
    "~/.aws/**",
    "~/.gnupg/**",
    "~/.config/gcloud/**",
    "~/.claude/**",
    "~/.claude.json",
    "~/.codex/**",
)

# The mode an unattended run must be PINNED to. It is pinned at all because the
# adapter otherwise adopts the operator's own `permissions.defaultMode`, so an
# ambient `acceptEdits` or `bypassPermissions` would approve tools before this
# project's rung was consulted.
#
# The value is the adapter's "Manual" mode - "standard behavior, prompts for
# dangerous operations" - and not the tempting "Don't Ask", which the CLI
# describes as "don't prompt for permissions, deny if not pre-approved". That
# description is exactly the problem: this lane's permission decision IS the
# prompt. An uncovered call is what reaches `session/request_permission`, where
# the run's exact-name allowlist answers it and a call naming another project is
# refused. A mode that denies without asking would take that rung out of the
# path - the run would be bounded by the CLI's static pre-approval alone, the
# cross-project guard would never run, and every declared grounding tool that is
# deliberately NOT pre-approved would die silently. Deny-by-default is served
# here by refusing at the rung, not by never asking it.
AUTONOMOUS_PERMISSION_MODE = "default"

# The adapter's configuration-option id for the session permission mode. Setting
# the mode through the configuration surface rather than `session/set_mode` is
# deliberate: that call answers with an empty result, while this one answers
# with the option list the adapter now holds, so the mode can be verified in the
# same exchange that sets it.
MODE_CONFIG_OPTION_ID = "mode"


# The built-ins whose permission rule accepts a file pattern, read from the
# installed agent SDK's own rule vocabulary (`filePatternTools`), which is what
# decides whether a scoped rule is a scope or an unmatchable string. `Grep` is
# deliberately absent from it upstream, so no path pattern can be written for
# that tool at all; a run with a workspace therefore does not pre-approve it
# (see ``native_read_floor_rules``).
CLAUDE_PATH_RULE_TOOLS: frozenset[str] = frozenset(
    {"Read", "Write", "Edit", "Glob", "NotebookRead", "NotebookEdit", "Cd"}
)


def workspace_scoped_tool_rule(tool_name: str, workspace_root: str | None) -> str:
    """Return the rule that permits *tool_name* inside the run's workspace only.

    A bare tool name in the pre-approved set permits the tool ANYWHERE. For a
    read built-in that is the whole host: the operator's credentials, another
    project's source, the environment of a running process. The run already has
    a project, so the permission it needs is that project - expressed as an
    absolute pattern, which the CLI resolves without reference to any base
    directory, unlike a relative one.

    A tool whose rule syntax takes no path, or a run with no workspace to name,
    keeps the bare name: an unmatchable rule would read as a scope while
    permitting nothing, which is worse than the honest bare name.
    """
    if tool_name not in CLAUDE_PATH_RULE_TOOLS or not workspace_root:
        return tool_name
    root = PurePath(workspace_root).as_posix().rstrip("/")
    return f"{tool_name}({root}/**)"


def claude_disallowed_tools(agent_config: AgentConfig | None) -> tuple[str, ...]:
    """Return the deny rules one claude session runs under.

    Two sources. The credential and process trees above are denied on every
    session, whoever is running: no persona has a reason to read them and one of
    them holds the token the run itself spends. The rest is the persona's own
    declaration, which before this only cleared ACP client capabilities - flags
    the CLI ignores for its own built-in tools, so an author role with
    ``filesystem_write = false`` still held Write and Edit. An absent persona
    still gets the unconditional denies.
    """
    denied: list[str] = [f"Read({path})" for path in CLAUDE_DENIED_READ_PATHS]
    if agent_config is None:
        return tuple(denied)
    capabilities = agent_config.capabilities
    if not capabilities.filesystem_write:
        denied.extend(CLAUDE_FILE_WRITE_TOOLS)
    if not capabilities.terminal:
        denied.extend(CLAUDE_TERMINAL_TOOLS)
    return tuple(denied)
