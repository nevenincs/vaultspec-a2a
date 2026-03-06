"""Pipeline phase inference from vault index."""

from __future__ import annotations


__all__ = ["PHASE_ORDER", "infer_phase_from_vault_index"]

PHASE_ORDER: list[str] = ["research", "reference", "adr", "plan", "exec", "audit"]

_PHASE_ORDER = PHASE_ORDER


def infer_phase_from_vault_index(vault_index: dict[str, list[str]]) -> str:
    """Return the highest phase that has at least one entry in vault_index.

    Iterates phases in reverse order (audit -> research). Returns "research"
    when vault_index is empty or no phase has entries.
    """
    for phase in reversed(_PHASE_ORDER):
        if vault_index.get(phase):
            return phase
    return "research"
