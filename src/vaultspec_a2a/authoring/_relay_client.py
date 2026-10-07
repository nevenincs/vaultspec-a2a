"""A provider bridge calls its worker without receiving engine authority."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

from ..utils import bearer_header
from ._connection_proof import authenticated_client

if TYPE_CHECKING:
    from types import TracebackType

__all__ = [
    "RELAY_CALL_PATH",
    "RELAY_PROOF_PATH",
    "AuthoringRelayClient",
    "relay_proof_message",
]

_RELAY_PROOF_DOMAIN = "vaultspec-authoring-relay"
RELAY_CALL_PATH = "/internal/authoring/call"
RELAY_PROOF_PATH = "/internal/authoring/proof"


def _relay_proof_path(run_id: str, role: str) -> str:
    return f"{RELAY_PROOF_PATH}?{urlencode({'run_id': run_id, 'role': role})}"


def relay_proof_message(
    port: int, pid: int, started_ms: int, path: str, challenge: str
) -> bytes:
    """Bind a fresh challenge to the relay listener's lifecycle and proof target.

    The one spelling of what the relay proof signs: the worker's proof route
    answers with it and the relay client verifies it, so the producer and the
    consumer cannot drift apart.
    """
    return (
        f"{_RELAY_PROOF_DOMAIN}:1\n{port}\n{pid}\n{started_ms}\n{path}\n{challenge}"
    ).encode("ascii")


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
            proof_path=_relay_proof_path(run_id, role),
            proof_message=relay_proof_message,
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
            headers=bearer_header(self._actor),
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
