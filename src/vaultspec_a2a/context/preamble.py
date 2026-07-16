"""Context preamble builder.

Constructs a ``SystemMessage`` containing project context (workspace,
feature tag, branch, available documents) that is prepended to the
graph input message list at thread creation time.
"""

from langchain_core.messages import SystemMessage

from .metadata import ThreadMetadata

__all__ = ["build_context_preamble"]


def build_context_preamble(metadata: ThreadMetadata) -> SystemMessage:
    """Build a context preamble SystemMessage from thread metadata.

    The preamble provides every agent in the graph with awareness of the
    project context without modifying system prompts or graph compilation.

    Args:
        metadata: The thread's provenance and context metadata.

    Returns:
        A ``SystemMessage`` containing the formatted context preamble.
    """
    parts: list[str] = [
        "## Project Context",
        f"- **Workspace:** {metadata.workspace_root}",
    ]

    if metadata.feature_tag:
        parts.append(f"- **Feature:** {metadata.feature_tag}")
    if metadata.source_repo:
        parts.append(f"- **Repository:** {metadata.source_repo}")
    if metadata.source_branch:
        parts.append(f"- **Branch:** {metadata.source_branch}")

    if metadata.context_refs:
        parts.append("\n## Available Context Documents")
        parts.append(
            "The following documents are available in the workspace. "
            "Read them as needed using your filesystem capabilities."
        )
        for ref in metadata.context_refs:
            line = f"- **[{ref.stage}]** `{ref.path}`"
            if ref.summary:
                line += f" — {ref.summary}"
            parts.append(line)

    preamble = "\n".join(parts)
    return SystemMessage(content=preamble)
