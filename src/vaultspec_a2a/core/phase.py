"""Backwards-compatibility shim — canonical source: vaultspec_a2a.context.stage"""

from vaultspec_a2a.context.stage import (
    PHASE_ORDER as PHASE_ORDER,
)
from vaultspec_a2a.context.stage import (
    infer_phase_from_vault_index as infer_phase_from_vault_index,
)

__all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]
