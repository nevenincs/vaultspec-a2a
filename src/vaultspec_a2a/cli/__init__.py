"""The ``vaultspec-a2a`` operator CLI package (ADR R9).

Thin client of the five-verb gateway surface. The public entry point is
:func:`main`, wired as the ``vaultspec-a2a`` console script.
"""

from .main import main as main

__all__ = ["main"]
