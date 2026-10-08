"""Probes for the host tools used by repository workflows.

``just`` and ``uv`` are required for Python setup. Node.js and npm are required
for the Claude ACP runtime. Each probe reports the resolved version so a
green ``doctor`` run is evidence of what was checked rather than silence.

The probing is :func:`dev.init.probe.check`, the same engine ``init`` asks,
and every tool ``init`` also requires is taken from its plan rather than
declared a second time here.
"""

from __future__ import annotations

from dev.doctor._probe import fail, report
from dev.exit_codes import OK, TOOL_BROKEN
from dev.init.plan import REQUIREMENTS
from dev.init.probe import Requirement, check
from dev.process import (
    ToolMissingError,
    ToolUnavailableError,
    combined_output,
    run_captured,
)

__all__ = ["node", "required"]

#: ``just`` itself, which ``init`` never probes: it is what runs ``init``. The
#: minimum is the oldest release with stable native modules, which this
#: repository's ``mod dev`` declaration depends on.
JUST = Requirement(
    command="just",
    purpose="Its stable native modules back this repository's `mod dev`.",
    install_url="https://just.systems/man/en/packages.html",
    minimum="1.31.0",
)

#: The host tools ``init`` requires, by command.
HOST_TOOLS = {requirement.command: requirement for requirement in REQUIREMENTS}

#: The Node version pin lives at the repository root, where the version
#: managers that read it look, and is compared by this script.
NODE_CHECK = "dev/node/check_node_version.mjs"


def _verify(requirement: Requirement) -> int:
    """Probe one requirement and report the verdict.

    Args:
        requirement: The tool to probe.

    Returns:
        :data:`OK` when it is present, working, and new enough, otherwise the
        gating code :func:`fail` reports.
    """
    finding = check(requirement)
    if not finding.ok:
        return fail(finding.message)
    report(finding.message)
    return OK


def node() -> int:
    """Verify Node.js against the repository pin, then verify npm."""
    try:
        completed = run_captured(["node", NODE_CHECK], timeout=None)
    except ToolMissingError:
        return fail(
            "Node.js is required for the project-pinned ACP runtime. Install the "
            f"version declared in .node-version from {HOST_TOOLS['node'].install_url}",
        )
    except ToolUnavailableError as exc:
        report(str(exc))
        return TOOL_BROKEN
    output = combined_output(completed)
    if output:
        report(output)
    if completed.returncode != 0:
        return completed.returncode
    return _verify(HOST_TOOLS["npm"])


def required() -> int:
    """Verify Just and uv and report their resolved versions.

    Every check runs even after one fails, so a single invocation reports the
    complete state of the toolchain rather than only the first thing missing.

    Returns:
        :data:`OK` when every required tool is present and new enough,
        otherwise the gating code.
    """
    worst = OK
    for requirement in (JUST, HOST_TOOLS["uv"]):
        code = _verify(requirement)
        if code != OK:
            worst = code
    return worst
