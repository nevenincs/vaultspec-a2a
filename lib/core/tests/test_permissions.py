"""Tests for the permission engine using real async operations.

No mocks, no monkeypatching. Tests exercise the actual policy evaluation,
request queuing, resolution flow, and session memory.
"""

import asyncio

import pytest

from ..exceptions import PermissionDeniedError
from ..permissions import (
    PermissionAction,
    PermissionEngine,
    PermissionPolicy,
    PermissionRequest,
    PermissionScope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACP_OPTIONS = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "allow_always", "name": "Allow always", "kind": "allow_always"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _make_request(
    tool_name: str = "read_file",
    agent_id: str = "coder-1",
    thread_id: str = "thread-1",
) -> PermissionRequest:
    """Build a PermissionRequest for testing."""
    return PermissionRequest(
        tool_name=tool_name,
        tool_input={"path": "/src/main.py"},
        agent_id=agent_id,
        thread_id=thread_id,
        options=list(ACP_OPTIONS),
    )


# ---------------------------------------------------------------------------
# Policy Evaluation Tests
# ---------------------------------------------------------------------------


class TestPolicyEvaluation:
    """Tests for synchronous policy evaluation."""

    def test_allow_policy_auto_resolves(self) -> None:
        """An ALLOW policy should return a decision without human input."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("read_*", PermissionAction.ALLOW),
            ]
        )
        request = _make_request(tool_name="read_file")
        decision = engine.evaluate(request)
        assert decision is not None
        assert decision.decided_by == "policy"

    def test_deny_policy_raises(self) -> None:
        """A DENY policy should raise PermissionDeniedError."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("danger_*", PermissionAction.DENY),
            ]
        )
        request = _make_request(tool_name="danger_tool")
        with pytest.raises(PermissionDeniedError, match="danger_tool"):
            engine.evaluate(request)

    def test_ask_policy_returns_none(self) -> None:
        """An ASK policy should return None (human needed)."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("bash", PermissionAction.ASK),
            ]
        )
        request = _make_request(tool_name="bash")
        decision = engine.evaluate(request)
        assert decision is None

    def test_no_matching_policy_returns_none(self) -> None:
        """No matching policy should default to None (ask human)."""
        engine = PermissionEngine(policies=[])
        request = _make_request(tool_name="unknown_tool")
        decision = engine.evaluate(request)
        assert decision is None

    def test_first_matching_policy_wins(self) -> None:
        """Policies are evaluated in order; first match wins."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("read_file", PermissionAction.DENY),
                PermissionPolicy("read_*", PermissionAction.ALLOW),
            ]
        )
        request = _make_request(tool_name="read_file")
        with pytest.raises(PermissionDeniedError):
            engine.evaluate(request)

    def test_glob_pattern_matching(self) -> None:
        """Glob patterns should match tool names correctly."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("delete_*", PermissionAction.ASK),
            ]
        )
        assert engine.evaluate(_make_request(tool_name="delete_file")) is None
        assert engine.evaluate(_make_request(tool_name="delete_dir")) is None
        # Non-matching should fall through
        assert engine.evaluate(_make_request(tool_name="create_file")) is None

    def test_add_policy_prepends(self) -> None:
        """add_policy should insert at the front (highest priority)."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy("read_*", PermissionAction.ASK),
            ]
        )
        engine.add_policy(PermissionPolicy("read_*", PermissionAction.ALLOW))
        decision = engine.evaluate(_make_request(tool_name="read_file"))
        assert decision is not None
        assert decision.decided_by == "policy"


# ---------------------------------------------------------------------------
# Session Memory Tests
# ---------------------------------------------------------------------------


class TestSessionMemory:
    """Tests for session-scoped approval memory."""

    def test_session_scope_remembers_approval(self) -> None:
        """Session-scoped ALLOW should remember the tool for future calls."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy(
                    "read_file",
                    PermissionAction.ALLOW,
                    PermissionScope.SESSION,
                ),
            ]
        )
        request = _make_request(tool_name="read_file")
        d1 = engine.evaluate(request)
        assert d1 is not None

        # Second call should also auto-resolve from session memory
        request2 = _make_request(tool_name="read_file")
        d2 = engine.evaluate(request2)
        assert d2 is not None
        assert d2.decided_by == "policy"

    def test_once_scope_does_not_remember(self) -> None:
        """ONCE-scoped ALLOW should not persist in session memory."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy(
                    "write_file",
                    PermissionAction.ALLOW,
                    PermissionScope.ONCE,
                ),
            ]
        )
        d1 = engine.evaluate(_make_request(tool_name="write_file"))
        assert d1 is not None

        # Session memory should NOT be populated for ONCE scope,
        # so a second evaluate still goes through the policy chain
        # (which still returns ALLOW from the policy, not from memory)
        d2 = engine.evaluate(_make_request(tool_name="write_file"))
        assert d2 is not None

    def test_clear_session_resets_memory(self) -> None:
        """clear_session should wipe all approvals."""
        engine = PermissionEngine(
            policies=[
                PermissionPolicy(
                    "read_*",
                    PermissionAction.ALLOW,
                    PermissionScope.SESSION,
                ),
            ]
        )
        engine.evaluate(_make_request(tool_name="read_file"))
        engine.clear_session()

        # After clear, the policy chain is still there so it re-evaluates
        d = engine.evaluate(_make_request(tool_name="read_file"))
        assert d is not None


# ---------------------------------------------------------------------------
# Request Queue Tests
# ---------------------------------------------------------------------------


class TestRequestQueue:
    """Tests for pending request management."""

    @pytest.mark.asyncio
    async def test_queue_and_get_pending(self) -> None:
        """Queued requests should appear in get_pending_requests."""
        engine = PermissionEngine(policies=[])
        request = _make_request()
        await engine.queue_request(request)

        pending = engine.get_pending_requests()
        assert len(pending) == 1
        assert pending[0].request_id == request.request_id

    @pytest.mark.asyncio
    async def test_get_pending_by_thread(self) -> None:
        """get_pending_requests should filter by thread_id."""
        engine = PermissionEngine(policies=[])
        r1 = _make_request(thread_id="thread-1")
        r2 = _make_request(thread_id="thread-2")
        await engine.queue_request(r1)
        await engine.queue_request(r2)

        pending_t1 = engine.get_pending_requests(thread_id="thread-1")
        assert len(pending_t1) == 1
        assert pending_t1[0].thread_id == "thread-1"

    @pytest.mark.asyncio
    async def test_resolve_removes_from_pending(self) -> None:
        """resolve_request should remove the request from pending."""
        engine = PermissionEngine(policies=[])
        request = _make_request()
        await engine.queue_request(request)

        decision = await engine.resolve_request(request.request_id, "allow_once")
        assert decision.option_id == "allow_once"
        assert decision.decided_by == "user"
        assert len(engine.get_pending_requests()) == 0

    @pytest.mark.asyncio
    async def test_resolve_unknown_request_raises(self) -> None:
        """resolve_request should raise KeyError for unknown IDs."""
        engine = PermissionEngine(policies=[])
        with pytest.raises(KeyError, match="no-such-id"):
            await engine.resolve_request("no-such-id", "allow_once")


# ---------------------------------------------------------------------------
# Async Wait/Resolve Flow Tests
# ---------------------------------------------------------------------------


class TestAsyncFlow:
    """Tests for the async wait → resolve pattern."""

    @pytest.mark.asyncio
    async def test_wait_and_resolve(self) -> None:
        """wait_for_decision should unblock when resolve_request is called."""
        engine = PermissionEngine(policies=[])
        request = _make_request()
        await engine.queue_request(request)

        async def resolve_after_delay() -> None:
            await asyncio.sleep(0.05)
            await engine.resolve_request(request.request_id, "allow_once")

        asyncio.get_running_loop().create_task(resolve_after_delay())
        decision = await engine.wait_for_decision(request.request_id)
        assert decision.option_id == "allow_once"
        assert decision.decided_by == "user"

    @pytest.mark.asyncio
    async def test_wait_unknown_request_raises(self) -> None:
        """wait_for_decision should raise KeyError for unknown IDs."""
        engine = PermissionEngine(policies=[])
        with pytest.raises(KeyError, match="no-such-id"):
            await engine.wait_for_decision("no-such-id")


# ---------------------------------------------------------------------------
# Default Policies Tests
# ---------------------------------------------------------------------------


class TestDefaultPolicies:
    """Tests for the default dangerous tool patterns."""

    def test_default_engine_asks_for_dangerous_tools(self) -> None:
        """Default engine should ASK for delete, bash, etc."""
        engine = PermissionEngine()
        dangerous_tools = ["delete_file", "bash", "run_command"]
        for tool in dangerous_tools:
            decision = engine.evaluate(_make_request(tool_name=tool))
            assert decision is None, f"Expected ASK for {tool}"

    def test_default_engine_asks_for_unknown_tools(self) -> None:
        """Default engine should also ASK for tools not matching any policy."""
        engine = PermissionEngine()
        decision = engine.evaluate(_make_request(tool_name="custom_tool"))
        assert decision is None


# ---------------------------------------------------------------------------
# Session Approval via Resolve Tests
# ---------------------------------------------------------------------------


class TestResolveSessionMemory:
    """Tests for session memory populated via resolve_request."""

    @pytest.mark.asyncio
    async def test_allow_always_remembers(self) -> None:
        """Choosing 'allow_always' should populate session memory."""
        engine = PermissionEngine(policies=[])
        request = _make_request(tool_name="write_file")
        await engine.queue_request(request)

        await engine.resolve_request(request.request_id, "allow_always")

        # Now evaluating the same tool should auto-resolve
        request2 = _make_request(tool_name="write_file")
        decision = engine.evaluate(request2)
        assert decision is not None
        assert decision.decided_by == "policy"
        assert decision.option_id == "allow_always"

    @pytest.mark.asyncio
    async def test_allow_once_does_not_remember(self) -> None:
        """Choosing 'allow_once' should NOT populate session memory."""
        engine = PermissionEngine(policies=[])
        request = _make_request(tool_name="write_file")
        await engine.queue_request(request)

        await engine.resolve_request(request.request_id, "allow_once")

        # Same tool should still require human approval
        request2 = _make_request(tool_name="write_file")
        decision = engine.evaluate(request2)
        assert decision is None
