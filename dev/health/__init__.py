"""Code-health measurement over the production package.

MEASUREMENT ONLY. Every entry point here exits 0 whatever it finds: a health
report is a ranking that tells you where to spend the next hour, not a verdict
that stops a build. The verdicts live in ``just dev lint``.

The thresholds this package ranks against are the same industry defaults the
gates enforce - they are stated once in :mod:`dev.health.report` and imported
by anything that needs them, so the report and the gate cannot disagree about
a number.
"""

from __future__ import annotations

__all__ = ["__doc__"]
