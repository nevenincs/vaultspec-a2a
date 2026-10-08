"""Drive the production ACP permission handler and read the outcome it answered."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...testing import request_permission_params
from .._acp_rpc_handlers import on_request_permission

if TYPE_CHECKING:
    from .._acp_types import AcpModelConfig, AcpSessionContext
    from .._json_contract import JsonObject

__all__ = ["acp_permission_outcome"]


async def acp_permission_outcome(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    *,
    options: list[JsonObject],
    tool_call: JsonObject | None = None,
) -> JsonObject:
    """Send one ``session/request_permission`` and return the outcome object."""
    params = request_permission_params(
        ctx.session_id, tool_call=tool_call, options=options
    )
    response = await on_request_permission(1, params, ctx, config)
    result = response.get("result")
    assert isinstance(result, dict)
    outcome = result.get("outcome")
    assert isinstance(outcome, dict)
    return outcome
