"""Backwards-compatibility shim — delegates to graph.compiler.

All consumers that import from ``vaultspec_a2a.core.graph`` continue to work
unchanged.  New code should import from ``vaultspec_a2a.graph.compiler``
directly.
"""

from vaultspec_a2a.graph.compiler import (
    _build_supervisor_prompt as _build_supervisor_prompt,
)
from vaultspec_a2a.graph.compiler import (
    _resolve_worker_model_preferences as _resolve_worker_model_preferences,
)
from vaultspec_a2a.graph.compiler import _worker_retry_on as _worker_retry_on
from vaultspec_a2a.graph.compiler import (
    build_initial_vault_index as build_initial_vault_index,
)
from vaultspec_a2a.graph.compiler import compile_team_graph as compile_team_graph

__all__ = ["build_initial_vault_index", "compile_team_graph"]
