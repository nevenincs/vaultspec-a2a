"""Per-invocation contextual anchoring for supervisor and worker nodes.

Builds a structured summary of active SDD feature context from TeamState.
This summary is injected as a SystemMessage at position [1] (after persona,
before history) on every node invocation when an active_feature is set.

ADR-022: Contextual Anchoring in Graph Lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .state import TeamState

__all__ = ["build_anchoring_context"]

_ANCHOR_PATH_CAP = 10  # max vault paths per doc-type in the summary


def build_anchoring_context(state: TeamState) -> str | None:
    """Produce a per-invocation anchoring summary from TeamState.

    Returns None when active_feature is None or missing (no feature bound).
    Does NOT read any files. Operates on state["vault_index"] (paths only).
    """
    feature = state.get("active_feature")
    if not feature:
        return None

    lines: list[str] = [
        "## Active Feature Context",
        f"- **Feature:** {feature}",
    ]

    phase = state.get("pipeline_phase")
    if phase:
        lines.append(f"- **Phase:** {phase}")

    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    if vault_index:
        lines.append("\n### Available Vault Documents")
        lines.append(
            "CONSULT these documents as PRIMARY references before acting. "
            "Read their content using your filesystem capabilities."
        )
        for doc_type, paths in vault_index.items():
            lines.append(f"\n**{doc_type.upper()}**")
            visible = paths[:_ANCHOR_PATH_CAP]
            for p in visible:
                lines.append(f"  - `{p}`")
            remainder = len(paths) - len(visible)
            if remainder > 0:
                lines.append(f"  - (+ {remainder} more)")

    errors: list[str] = state.get("validation_errors") or []
    if errors:
        lines.append(f"\n### Validation Errors ({len(errors)} active)")
        for err in errors:
            lines.append(f"  - {err}")

    # ADR-028: Universal Rule Propagation
    # Inject project-level mandates (e.g. .vaultspec/rules/rules/*.md)
    from .config import settings
    from .rules import RuleManager

    # Note: Using root from settings. In Docker this is usually /app.
    # ADR-028: Universal Rule Propagation
    from .config import settings
    from .rules import RuleManager

    rule_manager = RuleManager(settings.workspace_root)
    compiled_rules = rule_manager.compile()
    if compiled_rules:
        from logging import getLogger
        getLogger("vaultspec_a2a.core.anchoring").info("Injecting %d chars of project rules", len(compiled_rules))
        lines.append("\n## Project Coding Rules & Guidelines")
        lines.append(
            "The following mandates are ABSOLUTE and must be followed "
            "strictly across all generated code and configurations."
        )
        lines.append(compiled_rules)

    return "\n".join(lines)
