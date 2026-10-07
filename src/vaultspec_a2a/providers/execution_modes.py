"""The exact execution mode each external provider lane is served under.

The external counterpart to the in-process declaration in
:mod:`.in_process_catalog`. Catalog identity is execution-mode specific by
decision, so these strings are lane identity, not labels: the catalog
registrations, the frozen-lane validator, each model's construction, and the
completed-turn proof declaration all name a lane by them, and changing one renames
the lane everywhere it is admitted, frozen, and replayed.

The two Claude-backed lanes run on a selectable ACP backend and carry it as a
``:<backend>`` suffix. :func:`external_execution_mode` is the one place that
suffix is rendered.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from ..graph.enums import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ACP_BACKEND_LANES",
    "EXTERNAL_EXECUTION_MODES",
    "external_execution_mode",
]


EXTERNAL_EXECUTION_MODES: Mapping[Provider, str] = MappingProxyType(
    {
        Provider.ANTIGRAVITY: "antigravity-cli",
        Provider.CLAUDE: "claude-agent-acp",
        Provider.CODEX: "codex-app-server",
        Provider.KIMI: "kimi-code-acp",
        Provider.OPENAI: "openai-api",
        Provider.ZAI: "zai-claude-agent-acp",
        Provider.ZHIPU: "zhipu-openai-compatible-api",
    }
)

# The lanes whose mode names the ACP backend they execute on.
ACP_BACKEND_LANES: frozenset[Provider] = frozenset({Provider.CLAUDE, Provider.ZAI})


def external_execution_mode(provider: Provider, acp_backend: str) -> str:
    """Return the exact mode *provider* executes under on *acp_backend*.

    Raises:
        KeyError: If *provider* is not an external lane.
    """
    mode = EXTERNAL_EXECUTION_MODES[provider]
    return f"{mode}:{acp_backend}" if provider in ACP_BACKEND_LANES else mode
