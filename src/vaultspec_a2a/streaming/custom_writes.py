"""Node-attributed custom stream writes.

LangGraph strips the writing node's segment from a custom write's namespace
before the frame ever reaches ``astream``, so :mod:`.transformer`'s ``custom``
stream mode cannot recover a node's identity the way every other mode's frame
carries one. A custom write that wants correct attribution must therefore
carry its own identity INSIDE the payload, read here from the same
``RunnableConfig`` every graph node already receives (the metadata LangGraph
stamps onto it names the node BEFORE the write leaves the node, which is not
where the identity is lost).

No shipped node calls this yet; it exists so the first one that streams a
custom event does not repeat the same undocumented gap the audit found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.config import get_stream_writer

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

__all__ = [
    "custom_write_node_name",
    "emit_custom_node_write",
]

#: The payload fields :func:`emit_custom_node_write` stamps and
#: :func:`custom_write_node_name` reads back. Named constants rather than
#: string literals at each end, so the two can never drift onto different
#: keys.
CUSTOM_WRITE_NODE_FIELD = "node"
CUSTOM_WRITE_CONTENT_FIELD = "content"


def _config_node_name(config: RunnableConfig | None) -> str | None:
    """Return the node *config* names, or ``None`` when it names none.

    Reads the exact field every OTHER stream frame already carries in its own
    metadata (``langgraph_node``), so a node's identity is spelled the same
    way whether it survives on the frame or has to be carried in the payload.
    """
    if config is None:
        return None
    metadata = config.get("metadata")
    if not isinstance(metadata, dict):
        return None
    node = metadata.get("langgraph_node")
    return node if isinstance(node, str) and node else None


def emit_custom_node_write(content: str, *, config: RunnableConfig | None) -> None:
    """Push one custom-stream write stamped with the writing node's identity.

    Call from inside a graph node with the SAME ``config`` the node function
    received (or was injected via
    :func:`~vaultspec_a2a.graph.nodes._config_contract.accepting_runnable_config`),
    so the written payload survives to
    :mod:`~vaultspec_a2a.streaming.transformer`'s ``custom`` stream-mode
    projection carrying the node identity the namespace alone cannot.
    """
    writer = get_stream_writer()
    writer(
        {
            CUSTOM_WRITE_NODE_FIELD: _config_node_name(config),
            CUSTOM_WRITE_CONTENT_FIELD: content,
        }
    )


def custom_write_node_name(data: object) -> str | None:
    """Read the writing node's name off a custom-write payload, if present.

    ``data`` is whatever a ``custom`` stream-mode frame carries - a plain
    string or arbitrary mapping for a write this module did not produce, or
    the stamped mapping :func:`emit_custom_node_write` built. Either shape is
    legal; only the second carries a node.
    """
    if isinstance(data, dict):
        node = data.get(CUSTOM_WRITE_NODE_FIELD)
        if isinstance(node, str) and node:
            return node
    return None
