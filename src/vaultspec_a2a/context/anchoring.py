"""Per-invocation contextual anchoring for supervisor and worker nodes.

Builds a structured summary of active SDD feature context from TeamState.
This summary is injected as a SystemMessage at position [1] (after persona,
before history) on every node invocation when an active_feature is set.

ADR-022: Contextual Anchoring in Graph Lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

from vaultspec_a2a.domain_config import domain_config

__all__ = ["build_anchoring_context"]


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

    approval_status = state.get("approval_status")
    if approval_status:
        lines.append(f"- **Approval Status:** {approval_status}")

    routing_error = state.get("routing_error")
    if routing_error:
        lines.append(f"- **Routing Note:** {routing_error}")

    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    if vault_index:
        lines.append("\n### Available Vault Documents")
        lines.append(
            "CONSULT these documents as PRIMARY references before acting. "
            "Read their content using your filesystem capabilities."
        )
        for doc_type, paths in vault_index.items():
            lines.append(f"\n**{doc_type.upper()}**")
            visible = paths[: domain_config.anchor_path_cap]
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

    return "\n".join(lines)
