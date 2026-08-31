"""Actions this repository performs on its own checkout.

Where :mod:`dev.guards` asserts properties of the tree and :mod:`dev.health`
measures it, these modules CHANGE it: they install the Git hook shim and remove
generated build output. Both anchor to the working directory or to ``git
rev-parse`` on purpose - a checkout is exactly what they operate on - which is
the anchoring the shipped package is forbidden to do and
:mod:`dev.guards.repo_anchors` enforces.

Standard library only, like the dispatch core above them: ``just dev build
clean`` runs without any development group installed.
"""

from __future__ import annotations

__all__ = ["__doc__"]
