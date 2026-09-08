"""Docker and Compose probes, in both their optional and required forms.

The two forms differ only in CONSEQUENCE. ``docker-optional`` reports what is
missing and exits 0, because most of this repository's work needs no container
at all; ``docker`` exits 1, because the stack recipes cannot proceed without
one. Sharing the probe between them is what stops the two from disagreeing
about what "Docker is available" means, which is exactly what four separate
shell bodies could not guarantee.
"""

from __future__ import annotations

import sys

from dev.doctor._probe import capture, fail, report, warn

DOCKER_INSTALL_WINDOWS = (
    "https://docs.docker.com/desktop/setup/install/windows-install/"
)
DOCKER_INSTALL_LINUX = "https://docs.docker.com/engine/install/"
COMPOSE_INSTALL = "https://docs.docker.com/compose/install/"


def _install_hint() -> str:
    """Return the install URL appropriate to the running platform."""
    if sys.platform == "win32":
        return DOCKER_INSTALL_WINDOWS
    return DOCKER_INSTALL_LINUX


def _diagnose() -> str | None:
    """Probe Docker and Compose and return the first problem found.

    Returns:
        A human-readable description of what is missing or broken, or ``None``
        when both Docker and Compose are present and working.
    """
    hint = _install_hint()
    code, banner = capture(["docker", "--version"])
    if code == 127:
        return f"Docker is not installed. Install it from {hint}"
    if code != 0:
        return (
            f"Docker is unavailable. Install or repair Docker from {hint}\n  {banner}"
        )
    report(banner)

    compose_code, compose_banner = capture(["docker", "compose", "version"])
    if compose_code != 0:
        return (
            f"Docker Compose is unavailable. Install the Compose plugin: "
            f"{COMPOSE_INSTALL}\n  {compose_banner}"
        )
    report(compose_banner)
    return None


def docker_optional() -> int:
    """Report Docker support without failing non-container workflows.

    Returns:
        Always 0. A missing container runtime is information here, not a
        verdict - it matters only to the build and stack recipes.
    """
    problem = _diagnose()
    if problem is None:
        return 0
    return warn(
        f"{problem}\n  It is required only for container build and stack recipes.",
    )


def docker_required() -> int:
    """Require Docker and Compose for container-specific recipes.

    Returns:
        0 when both are present and working, otherwise 1.
    """
    problem = _diagnose()
    if problem is None:
        return 0
    return fail(f"{problem}\n  This recipe cannot run without Docker and Compose.")
