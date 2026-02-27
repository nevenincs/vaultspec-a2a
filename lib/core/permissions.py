"""Runtime policy engine for tool and workspace permissions.

Evaluates tool invocation requests against configurable policies,
manages pending requests requiring human approval, and records
decisions to the database audit log.

The engine integrates with LangGraph's ``interrupt()`` mechanism:
- If a policy auto-resolves → the callback returns immediately.
- If human approval is needed → the callback raises ``GraphInterrupt``
  via ``interrupt()``, and the engine queues the request for the frontend.

References:
    - ADR-003: Protocol bridging (MCP state mapping)
    - ADR-009: Module hierarchy
    - Gap 5: Permission engine
"""

import asyncio

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from fnmatch import fnmatch
from uuid import uuid4

from .exceptions import PermissionDeniedError


__all__ = [
    "PermissionAction",
    "PermissionDecision",
    "PermissionEngine",
    "PermissionPolicy",
    "PermissionRequest",
    "PermissionScope",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PermissionAction(StrEnum):
    """Action a policy takes when a tool matches."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionScope(StrEnum):
    """How long a policy or decision persists."""

    ONCE = "once"
    SESSION = "session"
    ALWAYS = "always"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """A configurable rule matching tools to actions.

    Attributes:
        tool_pattern: Glob pattern matching tool names
                      (e.g. ``"delete_*"``, ``"run_command"``).
        action: What to do when the pattern matches.
        scope: How long the policy applies.
    """

    tool_pattern: str
    action: PermissionAction
    scope: PermissionScope = PermissionScope.SESSION


@dataclass(slots=True)
class PermissionRequest:
    """A pending request for human approval.

    Attributes:
        request_id: Unique identifier for this request.
        tool_name: The tool being invoked.
        tool_input: Parameters the tool was called with.
        agent_id: The agent requesting permission.
        thread_id: The thread context.
        options: Available approval options (ACP format).
        created_at: When the request was created.
    """

    tool_name: str
    tool_input: dict[str, object]
    agent_id: str
    thread_id: str
    options: list[dict[str, object]] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """The outcome of evaluating or resolving a permission request.

    Attributes:
        request_id: The request this decision resolves.
        option_id: The chosen option ID.
        decided_by: Whether the decision was automatic or human.
        decided_at: When the decision was made.
    """

    request_id: str
    option_id: str
    decided_by: str  # "policy" or "user"
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Default dangerous tool patterns
# ---------------------------------------------------------------------------

DANGEROUS_TOOL_PATTERNS: list[PermissionPolicy] = [
    PermissionPolicy("delete_file", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("delete_*", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("run_command", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("bash", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("shell_*", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("execute_*", PermissionAction.ASK, PermissionScope.ONCE),
    PermissionPolicy("rm_*", PermissionAction.ASK, PermissionScope.ONCE),
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PermissionEngine:
    """Runtime policy engine for tool invocation permissions.

    Maintains a stack of policies (checked in order) and a session-scoped
    memory of prior approvals. Thread-safe for concurrent async callers
    via an ``asyncio.Lock`` per pending-request map.

    Usage::

        engine = PermissionEngine()
        decision = engine.evaluate(request)
        if decision is None:
            # Needs human approval — queue and interrupt
            engine.queue_request(request)
            ...
        else:
            # Auto-resolved by policy
            ...
    """

    def __init__(
        self,
        policies: Sequence[PermissionPolicy] | None = None,
    ) -> None:
        """Initialise the engine.

        Args:
            policies: Custom policies. Defaults to
                      :data:`DANGEROUS_TOOL_PATTERNS` if not provided.
        """
        self._policies: list[PermissionPolicy] = list(
            policies if policies is not None else DANGEROUS_TOOL_PATTERNS
        )
        # Session-scoped approvals: tool_name → option_id
        self._session_approvals: dict[str, str] = {}
        # Pending requests awaiting human resolution: request_id → request
        self._pending: dict[str, PermissionRequest] = {}
        # Futures for pending requests: request_id → Future[PermissionDecision]
        self._waiters: dict[str, asyncio.Future[PermissionDecision]] = {}
        self._lock = asyncio.Lock()

    @property
    def policies(self) -> list[PermissionPolicy]:
        """Return the current policy list (read-only copy)."""
        return list(self._policies)

    def add_policy(self, policy: PermissionPolicy) -> None:
        """Add a policy to the front of the evaluation chain.

        Policies added later take priority (evaluated first).

        Args:
            policy: The policy to prepend.
        """
        self._policies.insert(0, policy)

    def evaluate(self, request: PermissionRequest) -> PermissionDecision | None:
        """Evaluate a permission request against policies.

        Checks in order:
        1. Session-scoped prior approvals
        2. Policy chain (first match wins)
        3. No match → default to ASK (return None)

        Args:
            request: The permission request to evaluate.

        Returns:
            A ``PermissionDecision`` if the request can be auto-resolved,
            or ``None`` if human approval is needed.

        Raises:
            PermissionDeniedError: If a DENY policy matches.
        """
        # 1. Check session-scoped memory
        if request.tool_name in self._session_approvals:
            return PermissionDecision(
                request_id=request.request_id,
                option_id=self._session_approvals[request.tool_name],
                decided_by="policy",
            )

        # 2. Check policy chain (first match wins)
        for policy in self._policies:
            if not fnmatch(request.tool_name, policy.tool_pattern):
                continue

            if policy.action == PermissionAction.DENY:
                raise PermissionDeniedError(
                    f"Tool {request.tool_name!r} denied by policy "
                    f"pattern {policy.tool_pattern!r}"
                )

            if policy.action == PermissionAction.ALLOW:
                option_id = self._extract_allow_option(request.options)
                decision = PermissionDecision(
                    request_id=request.request_id,
                    option_id=option_id,
                    decided_by="policy",
                )
                if policy.scope in (PermissionScope.SESSION, PermissionScope.ALWAYS):
                    self._session_approvals[request.tool_name] = option_id
                return decision

            # ASK → human approval needed
            return None

        # 3. No matching policy → default to ASK
        return None

    async def queue_request(self, request: PermissionRequest) -> None:
        """Queue a permission request for human resolution.

        Args:
            request: The request to queue.
        """
        async with self._lock:
            self._pending[request.request_id] = request
            loop = asyncio.get_running_loop()
            self._waiters[request.request_id] = loop.create_future()

    async def resolve_request(
        self,
        request_id: str,
        option_id: str,
    ) -> PermissionDecision:
        """Resolve a pending request with the human's chosen option.

        Args:
            request_id: The request to resolve.
            option_id: The chosen option ID from the frontend.

        Returns:
            The ``PermissionDecision`` recording the human's choice.

        Raises:
            KeyError: If the request_id is not pending.
        """
        async with self._lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                msg = f"No pending request with id {request_id!r}"
                raise KeyError(msg)

            decision = PermissionDecision(
                request_id=request_id,
                option_id=option_id,
                decided_by="user",
            )

            # Remember session-scoped approvals
            self._remember_session_approval(
                request.tool_name, option_id, request.options
            )

            # Unblock any waiter
            future = self._waiters.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(decision)

            return decision

    async def wait_for_decision(
        self,
        request_id: str,
    ) -> PermissionDecision:
        """Block until a pending request is resolved by a human.

        Args:
            request_id: The request to wait on.

        Returns:
            The ``PermissionDecision`` once resolved.

        Raises:
            KeyError: If the request_id is not pending.
        """
        async with self._lock:
            future = self._waiters.get(request_id)
            if future is None:
                msg = f"No pending request with id {request_id!r}"
                raise KeyError(msg)

        return await future

    def get_pending_requests(
        self,
        thread_id: str | None = None,
    ) -> list[PermissionRequest]:
        """Return all pending permission requests, optionally filtered.

        Args:
            thread_id: If provided, filter to requests for this thread.

        Returns:
            A list of pending ``PermissionRequest`` instances in FIFO order.
        """
        requests = list(self._pending.values())
        if thread_id is not None:
            requests = [r for r in requests if r.thread_id == thread_id]
        return requests

    def clear_session(self) -> None:
        """Clear all session-scoped approvals and pending requests."""
        self._session_approvals.clear()
        self._pending.clear()
        for future in self._waiters.values():
            if not future.done():
                future.cancel()
        self._waiters.clear()

    # -- private helpers --

    @staticmethod
    def _extract_allow_option(options: list[dict[str, object]]) -> str:
        """Extract the first 'allow' option ID, or default to 'allow_once'."""
        for opt in options:
            oid = opt.get("optionId", "")
            if isinstance(oid, str) and "allow" in oid:
                return oid
        return "allow_once"

    def _remember_session_approval(
        self,
        tool_name: str,
        option_id: str,
        options: list[dict[str, object]],
    ) -> None:
        """Remember the approval if the chosen option is 'allow_always'."""
        for opt in options:
            if opt.get("optionId") == option_id:
                kind = opt.get("kind", "")
                if kind == "allow_always":
                    self._session_approvals[tool_name] = option_id
                return
