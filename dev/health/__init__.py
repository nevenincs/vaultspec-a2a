"""Code-health measurement over the production package.

MEASUREMENT ONLY. Every entry point here exits 0 whatever it finds: a health
report is a ranking that tells you where to spend the next hour, not a verdict
that stops a build. The verdicts live in ``just check-all``.

The thresholds this package ranks against are industry defaults, stated once
in :mod:`dev.health.report`.
"""

from __future__ import annotations

__all__ = ["__doc__"]
