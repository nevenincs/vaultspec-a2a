"""The Codex lane's MCP tool-approval rung.

``codex app-server`` gates every MCP tool call behind a server-initiated
``mcpServer/elicitation/request``. Its params carry ``serverName`` and a
``_meta.codex_approval_kind`` discriminator, and the client answers with the MCP
elicitation contract ``{"action": "accept" | "decline" | "cancel"}``. A client
that does not answer it - including one that answers ``-32601`` - has the call
resolved as not granted, and the model is handed the synthesized tool result
``user rejected MCP tool call`` while the turn still settles ``completed``. That
is a silent, total loss of every write an agent was asked to make.

The approval payload does NOT name the tool. It carries the server, a prose
``message`` ("Allow the X MCP server to run tool \"Y\"?") and the call's
arguments, but no tool-name field. The exact name is recovered instead from the
``item/started`` ``mcpToolCall`` notification codex emits immediately before the
elicitation, which carries ``server`` and ``tool`` verbatim - so identity comes
from a typed field rather than from parsing prose, which the ACP lane's
:mod:`_acp_rpc_handlers` refuses for good reason: a title matched by its leading
word lets an agent-chosen string canonicalise itself into an approval.

The autonomous rule is the ACP lane's rule, re-expressed for this transport:
accept EXACTLY the composed surface - the servers and tools this run itself
declared - and decline everything else, including any approval whose tool cannot
be named. Blanket approval is not available here.
"""

import logging
from dataclasses import dataclass, field
from typing import Final

from langgraph.errors import GraphBubbleUp

from ._acp_types import PermissionCallback
from ._json_contract import JsonObject, lenient_json_object

logger = logging.getLogger(__name__)

__all__ = [
    "ACCEPT_ACTION",
    "DECLINE_ACTION",
    "ELICITATION_METHOD",
    "CodexPermissionRung",
    "CodexToolCall",
    "elicitation_response",
]

ELICITATION_METHOD: Final = "mcpServer/elicitation/request"
"""Server-initiated request codex raises to have an MCP tool call approved."""

MCP_TOOL_CALL_APPROVAL_KIND: Final = "mcp_tool_call"
"""``_meta.codex_approval_kind`` marking an elicitation as a tool-call approval."""

ACCEPT_ACTION: Final = "accept"
DECLINE_ACTION: Final = "decline"

# The two decisions this rung can reach, in the ACP lane's option shape so a
# supervised run's human rung is handed the same structure on both lanes and the
# id it returns IS the action codex expects.
_APPROVAL_OPTIONS: Final[tuple[JsonObject, ...]] = (
    {
        "optionId": ACCEPT_ACTION,
        "kind": "allow_once",
        "name": "Allow this tool call once",
    },
    {
        "optionId": DECLINE_ACTION,
        "kind": "reject_once",
        "name": "Decline this tool call",
    },
)


@dataclass(frozen=True, slots=True)
class CodexToolCall:
    """One MCP tool call codex announced before asking for its approval."""

    server: str
    tool: str
    arguments: JsonObject = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        """Return the call in the ``mcp__<server>__<tool>`` spelling.

        The composed-allowlist spelling the rest of this project uses, so a
        supervised rung sees the same tool identity on the Codex lane that it
        sees on the ACP one.
        """
        return f"mcp__{self.server}__{self.tool}"


def elicitation_response(rpc_id: int, action: str) -> JsonObject:
    """Build the JSON-RPC response frame for one elicitation decision.

    ``content`` is sent only alongside an acceptance: the protocol types it as
    nullable precisely because a decline carries no user input, and the
    requested schema for a bare tool-call approval is an empty object.
    """
    result: JsonObject = {"action": action}
    if action == ACCEPT_ACTION:
        result["content"] = {}
    return {"id": rpc_id, "result": result}


class CodexPermissionRung:
    """Decides ``mcpServer/elicitation/request`` approvals for one Codex session.

    Holds the run's composed surface and, on a supervised run, the same
    ``permission_callback`` the ACP lane routes to. One instance per session: the
    observed tool calls it correlates against are session state.
    """

    def __init__(
        self,
        *,
        allowed_tools: frozenset[tuple[str, str]],
        permission_callback: PermissionCallback | None = None,
    ) -> None:
        self._allowed_tools = allowed_tools
        self._permission_callback = permission_callback
        # Latest announced call per (threadId, turnId, server). The elicitation
        # carries no call id to join on, so the join is the narrowest identity
        # both frames DO share. ``turnId`` is part of the key rather than
        # ignored: keyed on thread and server alone, a stale announcement from an
        # earlier turn would still match, and the decision would be made against
        # a tool the model is no longer calling. A key that cannot be matched is
        # a miss, and a miss declines.
        self._announced: dict[tuple[str, str, str], CodexToolCall] = {}

    def observe(self, method: str, params: JsonObject) -> None:
        """Record the tool identity carried by an ``mcpToolCall`` item frame.

        Called for every notification, so the identity is already recorded by the
        time the approval for it arrives. Non-tool-call frames are ignored.
        """
        if method not in ("item/started", "item/updated"):
            return
        item = lenient_json_object(params.get("item"))
        if item.get("type") != "mcpToolCall":
            return
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        server = item.get("server")
        tool = item.get("tool")
        if (
            not isinstance(thread_id, str)
            or not isinstance(turn_id, str)
            or not isinstance(server, str)
            or not isinstance(tool, str)
        ):
            return
        self._announced[(thread_id, turn_id, server)] = CodexToolCall(
            server=server,
            tool=tool,
            arguments=lenient_json_object(item.get("arguments")),
        )

    def _announced_call(self, params: JsonObject) -> CodexToolCall | None:
        """Return the call this approval is for, or ``None`` if it cannot be named.

        Correlation is exact on all three identity fields. Anything less is a
        miss - a partially-matched announcement is not weaker evidence of the
        same call, it is evidence of a DIFFERENT one, and approving on it would
        decide against a tool the elicitation is not about.
        """
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        server = params.get("serverName")
        if (
            not isinstance(thread_id, str)
            or not isinstance(turn_id, str)
            or not isinstance(server, str)
        ):
            return None
        return self._announced.get((thread_id, turn_id, server))

    async def decide(self, params: JsonObject) -> str:
        """Return the elicitation action for one approval request.

        Every path that cannot establish an approval on the run's own terms
        returns a decline: an elicitation that is not a tool-call approval, one
        whose tool cannot be named, and one naming a tool outside the composed
        surface. A decline is a refused tool call, never a stalled turn.
        """
        meta = lenient_json_object(params.get("_meta"))
        kind = meta.get("codex_approval_kind")
        if kind != MCP_TOOL_CALL_APPROVAL_KIND:
            logger.warning(
                "Declining a Codex elicitation that is not an MCP tool-call "
                "approval: kind=%r server=%r",
                kind,
                params.get("serverName"),
            )
            return DECLINE_ACTION

        call = self._announced_call(params)
        if call is None:
            # Fail closed rather than approve something unnameable: the payload
            # names the tool only in prose, and this project does not turn prose
            # into an approval.
            logger.warning(
                "Declining a Codex MCP tool-call approval: no announced tool "
                "call correlates to it (thread=%r turn=%r server=%r), so the "
                "tool cannot be named and is refused rather than guessed at",
                params.get("threadId"),
                params.get("turnId"),
                params.get("serverName"),
            )
            return DECLINE_ACTION

        if self._permission_callback is not None:
            return await self._supervised_action(call)
        return self._autonomous_action(call)

    def _autonomous_action(self, call: CodexToolCall) -> str:
        """Decide with no human rung: accept exactly the composed surface."""
        if (call.server, call.tool) in self._allowed_tools:
            logger.info(
                "Codex permission decision: server=%s tool=%s action=%s",
                call.server,
                call.tool,
                ACCEPT_ACTION,
            )
            return ACCEPT_ACTION
        logger.warning(
            "Declining an undeclared Codex MCP tool call: server=%s tool=%s "
            "is outside the run's composed surface",
            call.server,
            call.tool,
        )
        return DECLINE_ACTION

    async def _supervised_action(self, call: CodexToolCall) -> str:
        """Route the decision to the run's human rung.

        The callback is handed the two offered actions in the ACP option shape,
        so the id it returns is already the action codex expects. A callback that
        raises is not permitted to become an approval, and an id that was never
        offered is refused rather than guessed at.

        ``GraphBubbleUp`` propagates rather than being caught: it is how a
        supervised rung suspends the graph to ask a human, so swallowing it here
        would turn a pending question into a silent refusal - the same class of
        defect this module exists to close. The session records it and answers
        the still-open request with a decline, exactly as the ACP lane does.
        """
        callback = self._permission_callback
        if callback is None:
            return self._autonomous_action(call)
        try:
            chosen = await callback(
                call.qualified_name,
                dict(call.arguments),
                [dict(option) for option in _APPROVAL_OPTIONS],
            )
        except GraphBubbleUp:
            raise
        except Exception:
            logger.exception(
                "Codex permission callback raised; declining (fail-closed)"
            )
            return DECLINE_ACTION
        if chosen == ACCEPT_ACTION:
            logger.info(
                "Codex permission decision: server=%s tool=%s action=%s",
                call.server,
                call.tool,
                ACCEPT_ACTION,
            )
            return ACCEPT_ACTION
        if chosen != DECLINE_ACTION:
            logger.warning(
                "Codex permission callback returned %r, which is not an offered "
                "action; declining",
                chosen,
            )
        return DECLINE_ACTION
