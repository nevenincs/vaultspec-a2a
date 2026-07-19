"""Single target-compatibility authority for desktop CPython wheels."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from .contract import TargetTriple

if TYPE_CHECKING:
    from packaging.tags import Tag

__all__ = ["wheel_filename_supports_target"]

_MANYLINUX_PLATFORM: Final = re.compile(
    r"^manylinux(?P<floor>1|2010|2014|_(?P<major>\d+)_(?P<minor>\d+))_"
    r"(?P<arch>aarch64|x86_64)$"
)
_MACOS_PLATFORM: Final = re.compile(
    r"^macosx_(?P<major>\d+)_(?P<minor>\d+)_"
    r"(?P<arch>arm64|universal2|x86_64)$"
)
_MAX_GLIBC_BASELINE: Final = (2, 28)
_MAX_MACOS_BASELINE: Final = (13, 0)


def wheel_filename_supports_target(filename: str, target: TargetTriple) -> bool:
    """Return whether a wheel tag can run on target-native CPython 3.13."""
    if not isinstance(filename, str) or not isinstance(target, TargetTriple):
        return False
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return any(_tag_supports_target(tag, target) for tag in tags)


def _tag_supports_target(tag: Tag, target: TargetTriple) -> bool:
    interpreter = tag.interpreter
    abi = tag.abi
    if interpreter in {"py3", "py313"}:
        interpreter_supported = abi == "none"
    elif interpreter == "cp313":
        interpreter_supported = abi in {"none", "abi3", "cp313"}
    elif interpreter.startswith("cp") and interpreter[2:].isdigit() and abi == "abi3":
        encoded = interpreter[2:]
        interpreter_supported = len(encoded) in {2, 3}
        if interpreter_supported:
            major = int(encoded[0])
            minor = int(encoded[1:])
            interpreter_supported = major == 3 and 2 <= minor <= 13
    else:
        interpreter_supported = False
    if not interpreter_supported:
        return False
    platform = tag.platform
    if platform == "any":
        return abi == "none"
    if target is TargetTriple.WINDOWS_X86_64:
        return platform == "win_amd64"
    if target is TargetTriple.LINUX_X86_64:
        return _manylinux_supports(platform, arch="x86_64")
    if target is TargetTriple.LINUX_ARM64:
        return _manylinux_supports(platform, arch="aarch64")
    match = _MACOS_PLATFORM.fullmatch(platform)
    if match is None:
        return False
    floor = (int(match.group("major")), int(match.group("minor")))
    if floor > _MAX_MACOS_BASELINE:
        return False
    arch = match.group("arch")
    if target is TargetTriple.MACOS_ARM64:
        return arch in {"arm64", "universal2"}
    return arch in {"x86_64", "universal2"}


def _manylinux_supports(platform: str, *, arch: str) -> bool:
    match = _MANYLINUX_PLATFORM.fullmatch(platform)
    if match is None or match.group("arch") != arch:
        return False
    if match.group("floor") in {"1", "2010", "2014"}:
        return True
    floor = (int(match.group("major")), int(match.group("minor")))
    return floor <= _MAX_GLIBC_BASELINE
