"""The Claude lane's own permission posture: settings, denies, and mode.

The spawned Claude CLI decides tool permissions itself. Three things therefore
have to be stated on the session rather than assumed: which settings the CLI is
allowed to read, which of its built-in tools a persona may not use at all, and
which permission mode an unattended run may run in. Each value here names a
surface of the pinned adapter and its SDK, so it is a contract with an installed
artefact rather than a preference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..team.team_config import AgentConfig

__all__ = [
    "AUTONOMOUS_PERMISSION_MODE",
    "CLAUDE_FILE_WRITE_TOOLS",
    "CLAUDE_TERMINAL_TOOLS",
    "MODE_CONFIG_OPTION_ID",
    "claude_disallowed_tools",
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

# The mode an unattended run must be in: the adapter advertises it as "Don't
# Ask - don't prompt for permissions, deny if not pre-approved", which is the
# only advertised mode whose meaning matches a run with no human at the prompt.
AUTONOMOUS_PERMISSION_MODE = "dontAsk"

# The adapter's configuration-option id for the session permission mode. Setting
# the mode through the configuration surface rather than `session/set_mode` is
# deliberate: that call answers with an empty result, while this one answers
# with the option list the adapter now holds, so the mode can be verified in the
# same exchange that sets it.
MODE_CONFIG_OPTION_ID = "mode"


def claude_disallowed_tools(agent_config: AgentConfig | None) -> tuple[str, ...]:
    """Return the CLI built-ins a persona's capabilities forbid.

    A persona declares what it may do; before this the declaration only cleared
    ACP client capabilities, which the CLI ignores for its own built-in tools -
    so an author role with ``filesystem_write = false`` still held Write and
    Edit. An absent persona denies nothing extra: the caller's other bounds
    (the exact-name allowlist and the permission rung) still apply.
    """
    if agent_config is None:
        return ()
    capabilities = agent_config.capabilities
    denied: list[str] = []
    if not capabilities.filesystem_write:
        denied.extend(CLAUDE_FILE_WRITE_TOOLS)
    if not capabilities.terminal:
        denied.extend(CLAUDE_TERMINAL_TOOLS)
    return tuple(denied)
