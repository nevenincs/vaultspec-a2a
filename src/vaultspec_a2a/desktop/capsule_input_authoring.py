"""Authoring authority for the capsule's content-addressed release inputs.

This module is the sole production author of capsule inputs.  Its first pass
resolves the target-selective closures, acquires every pinned byte into the
content-addressed cache, derives per-package license identity, and emits the
canonical closure inventories.  It is the only component permitted network
access; every later stage consumes the cache and the pinned descriptor.

Wheel selection lives here.  :mod:`vaultspec_a2a.desktop.wheel_compatibility`
answers whether a wheel *can* run on a target; this module answers which of the
admitted wheels a target *ships*, by ranking against the standard installer
tag-priority model rather than a bespoke ordering.  Closure resolution belongs
to :mod:`vaultspec_a2a.desktop.lock_reconciliation`, whose selection core this
module consumes so a declared closure and a resolved closure stay one
computation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from .contract import TargetTriple
from .wheel_compatibility import (
    _MAX_GLIBC_BASELINE,
    _MAX_MACOS_BASELINE,
    wheel_filename_supports_target,
)

if TYPE_CHECKING:
    from .lock_reconciliation import LockedWheel, PythonPackageSelection

__all__ = [
    "CapsuleInputAuthoringError",
    "select_target_wheel",
    "target_platform_tags",
    "target_supported_tags",
]

_PYTHON_VERSION: Final = (3, 13)
_INTERPRETER: Final = "cp313"
_ABIS: Final = ("cp313",)
# Mirrors the legacy aliases packaging emits immediately after the ``_x_y``
# form they alias; the interleave position is part of the ordering.
_LEGACY_MANYLINUX: Final = {
    (2, 17): "manylinux2014",
    (2, 12): "manylinux2010",
    (2, 5): "manylinux1",
}
# The oldest glibc minor each architecture is defined down to, mirroring
# packaging's per-architecture floor.
_GLIBC_FLOOR: Final = {"x86_64": 5, "aarch64": 17}
_MACOS_ARCH: Final = {"aarch64": "arm64", "x86_64": "x86_64"}


class CapsuleInputAuthoringError(RuntimeError):
    """Raised when capsule inputs cannot be authored from the pinned sources."""


def _manylinux_platforms(architecture: str) -> tuple[str, ...]:
    """Mirror packaging's manylinux descent from the fixed glibc baseline."""
    floor = _GLIBC_FLOOR[architecture]
    major, baseline_minor = _MAX_GLIBC_BASELINE
    platforms: list[str] = []
    for minor in range(baseline_minor, floor - 1, -1):
        platforms.append(f"manylinux_{major}_{minor}_{architecture}")
        legacy = _LEGACY_MANYLINUX.get((major, minor))
        if legacy is not None:
            platforms.append(f"{legacy}_{architecture}")
    return tuple(platforms)


def target_platform_tags(target: TargetTriple) -> tuple[str, ...]:
    """Return one target's platform tags, most specific first.

    The sequence is derived from the triple itself and the fixed compatibility
    baselines, so it neither enumerates nor outlives any particular target set.
    """
    if not isinstance(target, TargetTriple):
        raise CapsuleInputAuthoringError("wheel selection target is invalid")
    architecture, _, remainder = target.value.partition("-")
    if remainder == "pc-windows-msvc" and architecture == "x86_64":
        return ("win_amd64",)
    if remainder == "unknown-linux-gnu" and architecture in _GLIBC_FLOOR:
        return _manylinux_platforms(architecture)
    if remainder == "apple-darwin" and architecture in _MACOS_ARCH:
        return tuple(mac_platforms(_MAX_MACOS_BASELINE, _MACOS_ARCH[architecture]))
    raise CapsuleInputAuthoringError(
        f"no platform tag order is defined for target {target.value}"
    )


def target_supported_tags(target: TargetTriple) -> tuple[Tag, ...]:
    """Return one target's supported tags in installer priority order.

    The order is the reference installer's: version-specific compiled wheels
    first, then descending stable-ABI floors, then pure-Python wheels last.
    """
    platforms = target_platform_tags(target)
    return (
        *cpython_tags(python_version=_PYTHON_VERSION, abis=_ABIS, platforms=platforms),
        *compatible_tags(
            python_version=_PYTHON_VERSION,
            interpreter=_INTERPRETER,
            platforms=platforms,
        ),
    )


def _best_tag_index(filename: str, order: dict[Tag, int]) -> int:
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        raise CapsuleInputAuthoringError(
            f"selected wheel filename is invalid: {filename}"
        ) from None
    ranks = [order[tag] for tag in tags if tag in order]
    if not ranks:
        raise CapsuleInputAuthoringError(
            f"wheel {filename} is admitted for the target but has no supported tag"
        )
    return min(ranks)


def _descending_build_key(filename: str) -> int:
    """Rank a wheel's build tag so a higher present build sorts first.

    A present build number ranks ahead of an absent one; the value is negated
    so the ordinary ascending sort places the higher build earlier.
    """
    _, _, build, _ = parse_wheel_filename(filename)
    return -build[0] if build else 1


def select_target_wheel(
    package: PythonPackageSelection, *, target: TargetTriple
) -> LockedWheel:
    """Choose the one wheel a target ships for a resolved package.

    Ranking is by best supported-tag position; ties break by build tag
    descending, then filename ascending, which is a total order over the lock.
    """
    admitted = tuple(
        wheel
        for wheel in package.compatible_wheels
        if wheel_filename_supports_target(wheel.filename, target)
    )
    if not admitted:
        raise CapsuleInputAuthoringError(
            f"no wheel in the lock supports {target.value} for {package.name}"
        )
    order = {
        tag: position for position, tag in enumerate(target_supported_tags(target))
    }
    return min(
        admitted,
        key=lambda wheel: (
            _best_tag_index(wheel.filename, order),
            _descending_build_key(wheel.filename),
            wheel.filename,
        ),
    )
