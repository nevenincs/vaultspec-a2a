"""Session authority shared by ACP client callback requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ._acp_types import MAX_ACP_SESSION_ID_LENGTH

if TYPE_CHECKING:
    from ._acp_types import AcpSessionContext

__all__: list[str] = []


class AcpSessionRequest(BaseModel):
    """A strictly typed request naming its owning negotiated session."""

    model_config = ConfigDict(strict=True, extra="ignore")

    session_id: str = Field(
        alias="sessionId", min_length=1, max_length=MAX_ACP_SESSION_ID_LENGTH
    )

    def require_active_session(self, ctx: AcpSessionContext) -> None:
        """Reject authority that is absent or belongs to another session."""
        if ctx.closing:
            raise ValueError("ACP session is closing")
        if ctx.session_id is None or self.session_id != ctx.session_id:
            raise ValueError("ACP sessionId does not match the active session")
