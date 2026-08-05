"""F17: a completed run's REST snapshot must show terminal tool-call status.

The live incident: run 866679f3 served 15 tool_calls, every one
``status: pending`` with empty ``locations``/``content``, on a run whose
transcript proves they were not pending - the model narrated their results,
and one was actively policy-rejected. ``enrich_snapshot_from_state``'s
checkpoint reconstruction assumed every tool call was a genuine
``ToolNode``-dispatched ``BaseTool`` (cross-referenced against a
``ToolMessage``); a provider-internal action (Codex's
``commandExecution``/``fileChange``/``mcpToolCall``) never produces one, so
every one fell to the ``else PENDING`` branch permanently, regardless of what
it actually did.

These tests drive the real production seam: ``codex_chat_model``'s own
``_completed_action_chunk`` builds the tool-call chunk exactly as a live turn
would, LangChain's own ``AIMessageChunk.__add__`` merges it into a final
message the way graph execution does, and ``MinimalState`` (the same adapter
``thread_state_service.py`` uses to call this function from a real checkpoint
projection) hands it to ``enrich_snapshot_from_state``. No field is set by
hand on the reconstructed snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AIMessageChunk, BaseMessageChunk

from ...graph.enums import ToolCallStatus
from ...providers.codex_chat_model import _completed_action_chunk
from ...thread.snapshots import ThreadStateData
from ..snapshot import MinimalState, enrich_snapshot_from_state

if TYPE_CHECKING:
    from ...providers._json_contract import JsonObject


def _checkpointed_action_message(item: JsonObject) -> BaseMessageChunk:
    """Build the checkpointed message a completed action item merges into.

    Mirrors ``codex_chat_model.tests`` exactly: the item goes through the
    model's own ``_completed_action_chunk``, then through LangChain's real
    ``AIMessageChunk.__add__`` accumulation - the same path a live graph
    turn's message reducer uses to arrive at the final checkpointed message.
    """
    chunk = _completed_action_chunk({"threadId": "t-1", "item": item})
    assert chunk is not None, f"{item.get('type')} produced no chunk"
    return AIMessageChunk(content="") + chunk.message


def _state_with_messages(*messages: object) -> MinimalState:
    return MinimalState(values={"messages": list(messages)})


def _snapshot(thread_id: str = "thread-1") -> ThreadStateData:
    return ThreadStateData(thread_id=thread_id, status="completed", last_sequence=1)


class TestSettledSnapshotReachesTerminalToolCallStatus:
    """Reconstructing a completed run's snapshot from its checkpoint alone."""

    def test_a_completed_command_reaches_completed_not_pending(self) -> None:
        """Fails on unfixed code: every provider action stayed PENDING forever.

        On the current (pre-fix) reconstruction this call has no ToolMessage
        to correlate against, so it falls to the else-PENDING branch and
        never advances - the exact defect F17 measured.
        """
        message = _checkpointed_action_message(
            {
                "id": "call_1",
                "type": "commandExecution",
                "command": "certutil -hashfile x sha256",
                "cwd": "C:\\work",
                "status": "completed",
                "exitCode": 0,
            }
        )
        state = _state_with_messages(message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.tool_call_id == "call_1"
        assert call.status == str(ToolCallStatus.COMPLETED)
        assert call.status != str(ToolCallStatus.PENDING)
        assert call.content, "expected the command/exit-code detail as content"

    def test_a_policy_rejected_command_reaches_failed_not_completed(self) -> None:
        """The exact live incident: a rejected command must not read as success.

        The reference run's transcript: "The hash check hit a policy
        rejection because I wrapped PowerShell inside PowerShell." That
        rejection appeared nowhere in the served tool-call record. A status
        this repo does not recognise as success (here, an app-server
        "failed") must resolve FAILED, never a silent COMPLETED nor the
        permanent-PENDING the unfixed code produces.
        """
        message = _checkpointed_action_message(
            {
                "id": "call_2",
                "type": "commandExecution",
                "command": "powershell -Command 'certutil ...'",
                "cwd": "C:\\work",
                "status": "failed",
                "exitCode": None,
            }
        )
        state = _state_with_messages(message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.status == str(ToolCallStatus.FAILED)
        assert call.status != str(ToolCallStatus.COMPLETED)
        assert call.status != str(ToolCallStatus.PENDING)

    def test_an_mcp_tool_call_denial_reaches_failed_not_completed(self) -> None:
        """An MCP tool-call item whose status is not a recognised success.

        Ties F16/F17: an MCP auto-denial (``codex-permission``'s area) must
        not silently read as a successful mcpToolCall in the served
        snapshot, whatever exact status string codex reports for it. This
        repo's own status vocabulary is the only one honoured as success;
        anything else is FAILED.
        """
        message = _checkpointed_action_message(
            {
                "id": "call_3",
                "type": "mcpToolCall",
                "server": "vaultspec-authoring",
                "tool": "propose_changeset",
                "arguments": {"text": "hello"},
                "status": "declined",
            }
        )
        state = _state_with_messages(message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.status == str(ToolCallStatus.FAILED)
        assert call.status != str(ToolCallStatus.COMPLETED)

    def test_a_file_change_action_populates_locations_in_the_snapshot(self) -> None:
        """A completed fileChange reports the paths it touched, not empty locations."""
        message = _checkpointed_action_message(
            {
                "id": "call_4",
                "type": "fileChange",
                "changes": [{"path": "src/module.py"}, {"path": "README.md"}],
                "status": "completed",
            }
        )
        state = _state_with_messages(message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.status == str(ToolCallStatus.COMPLETED)
        assert call.locations, "expected the changed file paths as locations"
        paths = {loc["path"] for loc in call.locations}
        assert paths == {"src/module.py", "README.md"}

    def test_a_genuine_tool_node_call_still_correlates_against_tool_message(
        self,
    ) -> None:
        """The ToolMessage-correlation path is preserved for real BaseTool calls.

        Regression guard: a provider action item's own-status path must not
        swallow the pre-existing, still-correct behaviour for a genuine
        LangGraph ToolNode dispatch, whose only record of completion is the
        ToolMessage it produced.
        """
        from langchain_core.messages import AIMessage, ToolMessage

        ai_message = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_5", "name": "mark_task_complete", "args": {}},
            ],
        )
        tool_message = ToolMessage(content="done", tool_call_id="call_5")
        state = _state_with_messages(ai_message, tool_message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.tool_call_id == "call_5"
        assert call.status == str(ToolCallStatus.COMPLETED)

    def test_a_genuine_tool_node_call_with_no_response_stays_pending(self) -> None:
        """A real BaseTool call with no ToolMessage yet is legitimately pending.

        Distinguishes the two PENDING causes: this one is honest (the call
        has not resolved), unlike a provider action item that was never
        going to produce a ToolMessage at all.
        """
        from langchain_core.messages import AIMessage

        ai_message = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_6", "name": "mark_task_complete", "args": {}},
            ],
        )
        state = _state_with_messages(ai_message)
        result = enrich_snapshot_from_state(_snapshot(), state)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].status == str(ToolCallStatus.PENDING)
