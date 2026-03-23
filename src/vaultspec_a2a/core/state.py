"""Compatibility shim — re-exports from vaultspec_a2a.thread.state.

This module exists solely so that ``from ..core.state import TeamState``
continues to work during the core-layer decomposition.  It will be
removed in Phase 7 when all consumers are updated to import from
``vaultspec_a2a.thread.state`` directly.
"""

from vaultspec_a2a.thread.state import (
    TeamState as TeamState,
)
from vaultspec_a2a.thread.state import (
    _append_artifacts as _append_artifacts,
)
from vaultspec_a2a.thread.state import (
    _append_validation_errors as _append_validation_errors,
)
from vaultspec_a2a.thread.state import (
    _merge_token_usage as _merge_token_usage,
)
from vaultspec_a2a.thread.state import (
    _merge_vault_index as _merge_vault_index,
)
from vaultspec_a2a.thread.state import (
    _replace_plan as _replace_plan,
)

__all__ = ["TeamState"]
