r"""ACP-specific exceptions and error codes.

Derived from Agent Client Protocol and JSON-RPC specifications.
"""

from enum import IntEnum


class AcpErrorCode(IntEnum):
    """ACP and JSON-RPC error codes."""

    # JSON-RPC standard codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # ACP specific codes (placeholder for future spec drift)
    UNKNOWN_ERROR = -1


class AcpError(Exception):
    """Base exception for all ACP-related errors."""

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


class AcpSessionError(AcpError):
    """Raised when session operations (new/load/fork) fail."""


class AcpPromptError(AcpError):
    """Raised when session/prompt fails (e.g. quota, refusal)."""


class AcpAuthError(AcpError):
    """Raised when authentication challenges fail."""
