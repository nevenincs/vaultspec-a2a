"""Installed-distribution version resolution — standard library only."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["package_version"]

_DISTRIBUTION = "vaultspec-a2a"
# Reported when the distribution metadata is absent — e.g. a source tree run
# that was never installed. A resolvable install always yields the real string.
_UNKNOWN_VERSION = "0.0.0"


def package_version() -> str:
    """Return the installed ``vaultspec-a2a`` distribution version.

    Reads the version from the distribution metadata so every surface reports
    the one string the package was built with, rather than a hand-maintained
    literal that drifts from ``pyproject.toml``.
    """
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:
        return _UNKNOWN_VERSION
