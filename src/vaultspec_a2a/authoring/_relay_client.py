"""A provider bridge calls its worker without receiving engine authority."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

from ._connection_proof import authenticated_client

if TYPE_CHECKING:
    from types import TracebackType

RELAY_PROOF_DOMAIN = "vaultspec-authoring-relay"
RELAY_CALL_PATH = "/internal/authoring/call"


def relay_proof_path(run_id: str, role: str) -> str:
    return "/internal/authoring/proof?" + urlencode({"run_id": run_id, "role": role})


class AuthoringRelayClient:
    """Prove the run/role listener on every connection before sending its token."""

    def __init__(self, origin: str, actor: str, run_id: str, role: str) -> None:
        self._actor = actor
        self._run_id = run_id
        self._role = role
        self._client = authenticated_client(
            origin,
            actor,
            180.0,
            proof_path=relay_proof_path(run_id, role),
            proof_domain=RELAY_PROOF_DOMAIN,
        )

    async def __aenter__(self) -> AuthoringRelayClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def dispatch(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        response = await self._client.post(
            RELAY_CALL_PATH,
            headers={"Authorization": f"Bearer {self._actor}"},
            json={
                "run_id": self._run_id,
                "role": self._role,
                "name": name,
                "arguments": arguments,
                "tool_call_id": tool_call_id,
            },
        )
        response.raise_for_status()
        result: object = response.json()
        if not isinstance(result, dict):
            raise ValueError("authoring relay returned an invalid result")
        return cast("dict[str, Any]", result)
