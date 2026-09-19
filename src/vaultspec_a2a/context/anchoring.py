"""Per-invocation contextual anchoring for supervisor and worker nodes.

Builds a structured summary of active SDD feature context from TeamState.
This summary is injected as a SystemMessage at position [1] (after persona,
before history) on every node invocation when an active_feature is set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..thread.state import TeamState

from ..domain_config import domain_config

__all__ = ["build_anchoring_context"]


def _vault_document_lines(vault_index: dict[str, list[str]]) -> list[str]:
    if not vault_index:
        return []
    lines = [
        "\n### Available Vault Documents",
        "CONSULT these documents as PRIMARY references before acting. "
        "Read their content using your filesystem capabilities.",
    ]
    for doc_type, paths in vault_index.items():
        lines.append(f"\n**{doc_type.upper()}**")
        visible = paths[: domain_config.anchor_path_cap]
        for path in visible:
            lines.append(f"  - `{path}`")
        remainder = len(paths) - len(visible)
        if remainder > 0:
            lines.append(f"  - (+ {remainder} more)")
    return lines


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
    lines.extend(_vault_document_lines(vault_index))

    errors: list[str] = state.get("validation_errors") or []
    if errors:
        lines.append(f"\n### Validation Errors ({len(errors)} active)")
        for err in errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)
