"""Operations this repository performs on its own ``.vault/`` corpus.

These are development actions on this checkout, not product usage of
``vaultspec-core``. The distinction matters: the CLI and its MCP server are a
finished product with their own interface, and wrapping that interface would
only add a layer that drifts out of step with it. What lives here is the
enrollment logic specific to THIS repository's shared, multi-worktree layout.
"""

from __future__ import annotations

__all__ = ["__doc__"]
