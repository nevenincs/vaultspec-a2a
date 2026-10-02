"""The Claude lane's own permission posture: settings, denies, and mode.

The spawned Claude CLI decides tool permissions itself. Three things therefore
have to be stated on the session rather than assumed: which settings the CLI is
allowed to read, which of its built-in tools a persona may not use at all, and
which permission mode an unattended run may run in. Each value here names a
surface of the pinned adapter and its SDK, so it is a contract with an installed
artefact rather than a preference.

The adapter also resolves the organisation's managed-policy tier before a
session exists and copies its environment entries into the CLI child's
environment. Session ``settingSources=[]`` does not remove that tier. Its
presence is host policy, not a permission this module grants or denies.
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..team.team_config import AgentConfig
    from ._json_contract import JsonObject

__all__ = [
    "AUTONOMOUS_PERMISSION_MODE",
    "BYPASS_CAPABILITY_OPTION",
    "CLAUDE_DENIED_READ_PATHS",
    "CLAUDE_FILE_WRITE_TOOLS",
    "CLAUDE_PATH_RULE_TOOLS",
    "CLAUDE_TERMINAL_TOOLS",
    "MODE_CONFIG_OPTION_ID",
    "claude_bypass_declined_meta",
    "claude_disallowed_tools",
    "claude_rule_path",
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

# The CLI's command-execution built-ins and the background-task verbs that
# observe and stop what they started. `Bash` is the SDK's only bash-prefix rule
# tool; the others are the installed CLI's own aliases for reading and killing a
# background shell, denied with it so a terminal-less persona cannot reach the
# output of a command by another name.
#
# `PowerShell` is the CLI's SECOND shell, and denying it is not hypothetical
# housekeeping: it is Windows-only and opt-in through
# `CLAUDE_CODE_USE_POWERSHELL_TOOL`, but on a Windows host without Git Bash the
# CLI requires a shell tool and this is the one it uses. A deny list naming only
# the bash family would therefore leave a persona that declares no terminal
# capability running commands on exactly the hosts where bash is absent. The
# rule is the bare name because PowerShell is in neither of the SDK's
# pattern-taking rule families, so no path pattern can narrow it.
CLAUDE_TERMINAL_TOOLS: tuple[str, ...] = (
    "Bash",
    "BashOutput",
    "KillShell",
    "KillBash",
    "PowerShell",
)

# Absolute paths no run has business reading, denied as path rules on the read
# built-in. These are not a substitute for scoping reads to the workspace (see
# :func:`workspace_scoped_tool_rule`) - a blocklist never is - but they are the
# places where one mistake hands over the credentials the run itself spends, or
# the environment of a live process, so they are named rather than left to the
# scope rule alone.
#
# Written as ordinary filesystem paths and rendered into the CLI's rule grammar
# by :func:`claude_rule_path`, which is also what anchors the workspace scope
# rule - one spelling of "this exact path", shared, because a deny rule and a
# scope rule that disagreed about what an absolute path looks like would be a
# deny that misses and a scope that matches nothing.
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

# The session option that declines the permission-bypass CAPABILITY, as opposed
# to the mode pin above, which only chooses among the capabilities a session
# already has. The adapter grants bypass to any session that does not decline
# it here - it asks only whether the option is explicitly `false` - and one
# granted bypass arms two things at once: `bypassPermissions` joins the mode
# catalog, and the spawned CLI is handed the skip-permissions flag. Neither
# belongs on a lane whose permission decision IS the rung.
#
# Declining it is also what keeps the lane launchable where the adapter and the
# CLI disagree about bypass. The adapter allows it for a root process that
# declares a sandbox; the CLI refuses the flag for root regardless, and the
# session dies at creation with the CLI's own message. A served turn and a
# catalog probe both open sessions, so both decline it.
BYPASS_CAPABILITY_OPTION = "allowDangerouslySkipPermissions"


def claude_bypass_declined_meta() -> JsonObject:
    """Return the ``session/new`` ``_meta`` that declines the bypass capability.

    The smallest complete claude-family meta block, for a caller that opens a
    session without composing a full option set - the catalog probe, which has
    no persona, no tool allowlist and no model to name, but still has to open
    the session under the posture the lane it is qualifying will run under.
    """
    return {"claudeCode": {"options": {BYPASS_CAPABILITY_OPTION: False}}}


# The built-ins whose permission rule accepts a file pattern, read from the
# installed agent SDK's own rule vocabulary (`filePatternTools`), which is what
# decides whether a scoped rule is a scope or an unmatchable string. `Grep` is
# deliberately absent from it upstream, so no path pattern can be written for
# that tool at all; a run with a workspace therefore does not pre-approve it
# (see ``native_read_floor_rules``).
CLAUDE_PATH_RULE_TOOLS: frozenset[str] = frozenset(
    {"Read", "Write", "Edit", "Glob", "NotebookRead", "NotebookEdit", "Cd"}
)


# A drive-letter prefix, matched independently of the host this process runs on
# so a rule written for a Windows workspace renders the same on either. The
# separator is part of the match because ``C:file`` is drive-RELATIVE, which is
# not an absolute path and must not be anchored as one.
_WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


def claude_rule_path(path: str) -> str:
    """Return one path in the spelling the CLI's permission rules resolve.

    The CLI reads a rule path by its leading anchor, and the anchors are not
    the filesystem's. A single leading ``/`` anchors at the session's primary
    working directory, ``//`` is the filesystem root, and ``~/`` is the
    operator's home; a Windows path is normalised to POSIX first with the drive
    as the first lower-case segment, so ``C:\\Users\\alice`` is written
    ``//c/Users/alice``.

    So an absolute path cannot be written the way it is spelled on disk, and
    writing it that way fails in the direction that is hardest to notice: a
    deny of ``/proc/**`` denies ``<workspace>/proc/**``, a directory that does
    not exist, and a scope rule naming the workspace with one slash matches
    nothing at all. Both read as the protection they are not.

    A path that already carries an anchor of its own - ``~``-relative, or a
    deliberately working-directory-relative pattern - is returned unchanged:
    those spellings are already in the grammar and mean what they say.
    """
    if match := _WINDOWS_DRIVE.match(path):
        tail = path[match.end() :].replace("\\", "/")
        posix = f"/{match.group(1).lower()}/{tail}"
    else:
        posix = PurePath(path).as_posix()
    return f"/{posix}" if posix.startswith("/") else posix


def workspace_scoped_tool_rule(tool_name: str, workspace_root: str | None) -> str:
    """Return the rule that permits *tool_name* inside the run's workspace only.

    A bare tool name in the pre-approved set permits the tool ANYWHERE. For a
    read built-in that is the whole host: the operator's credentials, another
    project's source, the environment of a running process. The run already has
    a project, so the permission it needs is that project - expressed as an
    absolute pattern, which the CLI resolves without reference to any base
    directory, unlike a relative one. Absolute means the CLI's own absolute
    anchor (:func:`claude_rule_path`), not merely a path that starts at the
    filesystem root.

    A tool whose rule syntax takes no path, or a run with no workspace to name,
    keeps the bare name: an unmatchable rule would read as a scope while
    permitting nothing, which is worse than the honest bare name.
    """
    if tool_name not in CLAUDE_PATH_RULE_TOOLS or not workspace_root:
        return tool_name
    # A drive root renders with its own trailing separator ("//c/"), so the
    # pattern is appended to the anchor rather than concatenated after it.
    anchor = claude_rule_path(workspace_root).rstrip("/") or "/"
    return f"{tool_name}({anchor}/**)"


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
    denied: list[str] = [
        f"Read({claude_rule_path(path)})" for path in CLAUDE_DENIED_READ_PATHS
    ]
    if agent_config is None:
        return tuple(denied)
    capabilities = agent_config.capabilities
    if not capabilities.filesystem_write:
        denied.extend(CLAUDE_FILE_WRITE_TOOLS)
    if not capabilities.terminal:
        denied.extend(CLAUDE_TERMINAL_TOOLS)
    return tuple(denied)
