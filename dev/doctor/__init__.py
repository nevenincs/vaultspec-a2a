"""Environment diagnosis: the tools this harness needs, and their versions.

Every probe here replaced a pair of `[windows]`/`[unix]` recipe bodies in
``dev/just/doctor.just`` that re-implemented the same check in two shell
dialects - including two independent semver comparators, one written in
PowerShell's ``[Version]`` type and one in ``awk``. Two implementations of one
rule is one implementation too many: they had already drifted in what they
accepted, and only the platform you happened to be on decided which answer you
got.

This module imports the standard library only, so a single implementation
answers identically on every platform.
"""

from __future__ import annotations

from dev.doctor._docker import docker_optional, docker_required
from dev.doctor._tools import required

__all__ = ["docker_optional", "docker_required", "required"]
