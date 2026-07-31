"""Repository-health guards: checks whose subject is this checkout itself.

These have no production module to cohabit with, because what they assert is a
property of the repository - its import convention, its configuration - rather
than of anything the package does at runtime. They are invoked by name from
:mod:`dev.toolchain` and carry no third-party dependency, so a guard runs even
in a bare interpreter with nothing installed.
"""

from __future__ import annotations

__all__ = ["__doc__"]
