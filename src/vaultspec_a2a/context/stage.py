"""Pipeline phase inference from vault index."""

from __future__ import annotations

__all__ = ["PHASE_ORDER", "VAULT_STAGE_PATTERNS", "infer_phase_from_vault_index"]

PHASE_ORDER: list[str] = ["research", "reference", "adr", "plan", "exec", "audit"]

_PHASE_ORDER = PHASE_ORDER

#: The glob each vault stage is discovered by, DERIVED from the stage order
#: above rather than restated beside it.
#:
#: This map and the order were declared three times between them - once here as
#: the order, and once each in the context-reference scan and the vault-index
#: build, which walked byte-identical six-entry pattern maps of their own. A
#: stage added to one was invisible to the others, and the two scans run for the
#: SAME run: one at thread creation, one at dispatch.
#:
#: `exec` is the one stage whose documents live in a per-feature DIRECTORY
#: rather than as flat files, so it globs one level deeper. That is a real
#: property of the vault layout, which is why it is spelled out here once
#: instead of being rediscovered by every caller.
VAULT_STAGE_PATTERNS: dict[str, str] = {
    stage: (
        f".vault/{stage}/*{{tag}}*/**/*.md"
        if stage == "exec"
        else f".vault/{stage}/*{{tag}}*.md"
    )
    for stage in PHASE_ORDER
}


def infer_phase_from_vault_index(vault_index: dict[str, list[str]]) -> str:
    """Return the highest phase that has at least one entry in vault_index.

    Iterates phases in reverse order (audit -> research). Returns "research"
    when vault_index is empty or no phase has entries.
    """
    for phase in reversed(_PHASE_ORDER):
        if vault_index.get(phase):
            return phase
    return "research"
