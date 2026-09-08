"""Probes for the tools every workflow in this repository needs.

``just``, ``uv``, Node.js, and npm are required: without any one of them there
is no harness to run. Each probe reports the resolved version on success so a
green ``doctor`` run is evidence of what was checked rather than silence.
"""

from __future__ import annotations

from dev.doctor._probe import (
    capture,
    fail,
    format_version,
    parse_version,
    report,
    which,
)

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
    code, banner = capture(["just", "--version"])
    if code != 0:
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
    if which("uv") is None:
        return fail(f"uv is required. Install it from {UV_INSTALL}")
    code, banner = capture(["uv", "--version"])
    if code != 0:
        return fail(f"uv could not be run. Install it from {UV_INSTALL}\n  {banner}")
    report(banner)
    return 0


def _check_node() -> int:
    """Verify Node.js against the repository pin, then verify npm."""
    if which("node") is None:
        return fail(
            "Node.js is required for the project-pinned ACP runtime. Install the "
            f"version declared in .node-version from {NODE_INSTALL}",
        )
    code, output = capture(["node", NODE_CHECK])
    if output:
        report(output)
    if code != 0:
        return code
    if which("npm") is None:
        return fail("npm is required to restore package-lock.json.")
    npm_code, npm_banner = capture(["npm", "--version"])
    if npm_code != 0:
        return fail(f"npm could not be run.\n  {npm_banner}")
    report(f"npm {npm_banner}")
    return 0


def required() -> int:
    """Verify Just, uv, Node.js, and npm and report their resolved versions.

    Every check runs even after one fails, so a single invocation reports the
    complete state of the toolchain rather than only the first thing missing.

    Returns:
        0 when every required tool is present and new enough, otherwise 1.
    """
    worst = 0
    for check in (_check_just, _check_uv, _check_node):
        code = check()
        if code != 0:
            worst = code
    return worst
