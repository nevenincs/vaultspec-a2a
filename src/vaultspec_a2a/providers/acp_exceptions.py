r"""ACP-specific exceptions and error codes.

Derived from Agent Client Protocol and JSON-RPC specifications.
"""

from enum import IntEnum

__all__ = [
    "AcpAuthError",
    "AcpError",
    "AcpErrorCode",
    "AcpPromptError",
    "AcpProtocolError",
    "AcpSessionError",
    "IsolationRequiredError",
]


class AcpErrorCode(IntEnum):
    """ACP and JSON-RPC error codes."""

    # JSON-RPC standard codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # ACP specific codes
    UNKNOWN_ERROR = -1
    # Authentication required — agent returned authRequired error during session setup.
    # Numeric value chosen to avoid collisions with JSON-RPC standard range.
    UNAUTHENTICATED = -32000


class AcpError(Exception):
    """Base exception for all ACP-related errors."""

    __slots__ = ("code", "data", "message", "request_id")

    def __init__(
        self,
        message: str,
        code: int = AcpErrorCode.INTERNAL_ERROR,
        data: object = None,
        request_id: str | int | None = None,
    ) -> None:
        """Initialize the ACP error.

        Args:
            message: Human-readable error message.
            code: ACP or JSON-RPC error code.
            data: Optional structured data related to the error.
            request_id: Optional ID of the request that failed.
        """
        self.message = message
        self.code = code
        self.data = data
        self.request_id = request_id
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = f"ACP Error [{self.code}]: {self.message}"
        if self.request_id is not None:
            msg = f"({self.request_id}) {msg}"
        if self.data:
            msg += f" | Data: {self.data}"
        return msg


class AcpProtocolError(AcpError):
    """Raised when the agent sends malformed protocol data."""

    __slots__ = ()


class AcpSessionError(AcpError):
    """Raised when session operations (new/load/fork) fail."""

    __slots__ = ()


class AcpPromptError(AcpError):
    """Raised when session/prompt fails (e.g. quota, refusal)."""

    __slots__ = ()


class AcpAuthError(AcpError):
    """Raised when authentication challenges fail."""

    __slots__ = ()


class IsolationRequiredError(AcpError):
    """Raised when an armed run would spawn without CLI config-home isolation.

    The agent-harness-provisioning ADR binds the spawned agent's MCP surface to
    an allowlist equal to the declared harness servers; enforcing that requires a
    per-run isolated ``CLAUDE_CONFIG_DIR`` (which suppresses the operator's
    ambient user-global MCP and pins out the workspace's project ``.mcp.json``).
    A harness-armed preset that reaches the spawn without that isolation - or that
    resolves to ``auth_mode == "none_detected"`` so isolation cannot be
    established from an env-carried token - must fail loud here rather than launch
    an agent with an unbounded MCP surface.
    """

    __slots__ = ()
