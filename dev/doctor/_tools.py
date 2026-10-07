"""Probes for the host tools used by repository workflows.

``just`` and ``uv`` are required for Python setup. Node.js and npm are required
for the Claude ACP runtime. Each probe reports the resolved version so a
green ``doctor`` run is evidence of what was checked rather than silence.
"""

from __future__ import annotations

from dev.doctor._probe import fail, format_version, parse_version, report
from dev.exit_codes import TOOL_MISSING
from dev.process import ToolMissingError, ToolUnavailableError, run_captured

#: The oldest ``just`` that supports stable native modules, which this
#: repository's ``mod dev`` declaration depends on.
JUST_MINIMUM = (1, 31, 0)

JUST_INSTALL = "https://just.systems/man/en/packages.html"
UV_INSTALL = "https://docs.astral.sh/uv/getting-started/installation/"
NODE_INSTALL = "https://nodejs.org/"

#: The Node version pin lives at the repository root, where the version
#: managers that read it look, and is compared by this script.
NODE_CHECK = "dev/node/check_node_version.mjs"


def _check_just() -> int:
    """Verify that ``just`` is present and new enough for native modules."""
    try:
        completed = run_captured(["just", "--version"], timeout=None)
    except ToolUnavailableError as exc:
        return fail(f"just is required. Install from {JUST_INSTALL}\n  {exc}")
    banner = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return fail(
            f"just is required. Install from {JUST_INSTALL}\n  {banner}",
        )
    current = parse_version(banner)
    if current is None:
        return fail(
            "Could not parse the installed Just version. Required: just >= "
            f"{format_version(JUST_MINIMUM)}. Install from {JUST_INSTALL}",
        )
    if current < JUST_MINIMUM:
        return fail(
            f"just {format_version(current)} is too old. Required: just >= "
            f"{format_version(JUST_MINIMUM)} for native modules. "
            f"Install from {JUST_INSTALL}",
        )
    report(
        f"{banner} (requirement satisfied: >= {format_version(JUST_MINIMUM)})",
    )
    return 0


def _check_uv() -> int:
    """Verify that ``uv`` is present and report its version."""
    try:
        completed = run_captured(["uv", "--version"], timeout=None)
    except ToolMissingError:
        return fail(f"uv is required. Install it from {UV_INSTALL}")
    except ToolUnavailableError as exc:
        return fail(f"uv could not be run. Install it from {UV_INSTALL}\n  {exc}")
    banner = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return fail(f"uv could not be run. Install it from {UV_INSTALL}\n  {banner}")
    report(banner)
    return 0


def node() -> int:
    """Verify Node.js against the repository pin, then verify npm."""
    try:
        completed = run_captured(["node", NODE_CHECK], timeout=None)
    except ToolMissingError:
        return fail(
            "Node.js is required for the project-pinned ACP runtime. Install the "
            f"version declared in .node-version from {NODE_INSTALL}",
        )
    except ToolUnavailableError as exc:
        report(str(exc))
        return TOOL_MISSING
    output = (completed.stdout + completed.stderr).strip()
    if output:
        report(output)
    if completed.returncode != 0:
        return completed.returncode
    try:
        npm = run_captured(["npm", "--version"], timeout=None)
    except ToolMissingError:
        return fail("npm is required to restore package-lock.json.")
    except ToolUnavailableError as exc:
        return fail(f"npm could not be run.\n  {exc}")
    npm_banner = (npm.stdout + npm.stderr).strip()
    if npm.returncode != 0:
        return fail(f"npm could not be run.\n  {npm_banner}")
    report(f"npm {npm_banner}")
    return 0


def required() -> int:
    """Verify Just and uv and report their resolved versions.

    Every check runs even after one fails, so a single invocation reports the
    complete state of the toolchain rather than only the first thing missing.

    Returns:
        0 when every required tool is present and new enough, otherwise 1.
    """
    worst = 0
    for check in (_check_just, _check_uv):
        code = check()
        if code != 0:
            worst = code
    return worst
