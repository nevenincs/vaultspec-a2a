"""Run/role authoring authority lives with the worker's active credentials."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..authoring import AuthoringClient
from ..authoring._engine_trust import (
    CHALLENGE_HEADER,
    PID_HEADER,
    PROOF_HEADER,
    STARTED_MS_HEADER,
    proof_digest,
)
from ..authoring._errors import AuthoringError
from ..authoring._relay_client import (
    RELAY_CALL_PATH,
    RELAY_PROOF_PATH,
    relay_proof_message,
)
from ..authoring._tool_calls import private_tool_call_journal_path
from ..authoring.catalog import make_tool_dispatch
from ..authoring.discovery import resolve_engine
from ..thread.constants import (
    MAX_ROLE_ID_CHARS,
    MAX_RUN_ID_CHARS,
    ROLE_ID_PATTERN,
    RUN_ID_PATTERN,
)
from ..utils import bearer_matches

if TYPE_CHECKING:
    from .catalog_store import RunCatalogStore
    from .token_store import RunTokenStore

__all__ = ["AuthoringRelay", "router"]

logger = logging.getLogger(__name__)


class _RelayCall(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    run_id: str = Field(
        min_length=1, max_length=MAX_RUN_ID_CHARS, pattern=RUN_ID_PATTERN
    )
    role: str = Field(
        min_length=1, max_length=MAX_ROLE_ID_CHARS, pattern=ROLE_ID_PATTERN
    )
    name: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any]
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=160)


class AuthoringRelay:
    def __init__(self, tokens: RunTokenStore, catalogs: RunCatalogStore) -> None:
        self._tokens = tokens
        self._catalogs = catalogs
        self._started_ms = time.time_ns() // 1_000_000
        self._locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = (
            WeakValueDictionary()
        )

    def actor(self, run_id: str, role: str) -> str:
        actor = self._tokens.actor_token(run_id, role)
        if not actor or not self._tokens.engine_bearer(run_id):
            raise HTTPException(403, "authoring authority is unavailable")
        return actor

    def authorize(self, call: _RelayCall, authorization: str | None) -> str:
        actor = self.actor(call.run_id, call.role)
        if not bearer_matches(authorization, actor):
            raise HTTPException(403, "authoring authority is unavailable")
        return actor

    def proof(self, request: Request, run_id: str, role: str) -> Response:
        actor = self.actor(run_id, role)
        challenge = request.headers.get(CHALLENGE_HEADER, "")
        if len(challenge) != 64 or any(c not in "0123456789abcdef" for c in challenge):
            raise HTTPException(400, "invalid authoring challenge")
        server = request.scope.get("server")
        if not server:
            raise HTTPException(503, "authoring listener is unavailable")
        path = request.scope["raw_path"].decode("ascii")
        query = request.scope["query_string"].decode("ascii")
        path += "?" + query
        message = relay_proof_message(
            server[1], os.getpid(), self._started_ms, path, challenge
        )
        proof = proof_digest(actor, message)
        return Response(
            headers={
                PROOF_HEADER: proof,
                PID_HEADER: str(os.getpid()),
                STARTED_MS_HEADER: str(self._started_ms),
            }
        )

    async def dispatch(
        self, call: _RelayCall, authorization: str | None
    ) -> dict[str, Any]:
        self.authorize(call, authorization)
        lock = self._locks.setdefault((call.run_id, call.role), asyncio.Lock())
        async with lock:
            actor = self.authorize(call, authorization)
            snapshot = self._catalogs.get(call.run_id)
            if snapshot is None:
                raise HTTPException(409, "authoring catalog is unavailable")
            path = private_tool_call_journal_path(call.run_id, call.role)
            endpoint = await asyncio.to_thread(resolve_engine)
            if endpoint is None:
                raise HTTPException(503, "authoring engine is unavailable")
            # Discovery performs network I/O; run authority can disappear while
            # it waits. Refuse before starting a new engine session in that case.
            actor = self.authorize(call, authorization)
            async with AuthoringClient(
                endpoint.base_url,
                endpoint.bearer_token,
                actor_token=actor,
                bearer_resolver=resolve_engine,
            ) as client:
                dispatch = make_tool_dispatch(
                    client,
                    run_id=call.run_id,
                    actor_token=actor,
                    snapshot=snapshot,
                    call_scope=call.role,
                    journal_path=path,
                )
                return await dispatch(
                    call.name, call.arguments, tool_call_id=call.tool_call_id
                )


router = APIRouter()


def _relay(request: Request) -> AuthoringRelay:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "authoring requires loopback")
    relay = getattr(request.app.state, "authoring_relay", None)
    if not isinstance(relay, AuthoringRelay):
        raise HTTPException(503, "authoring authority is unavailable")
    return relay


@router.get(RELAY_PROOF_PATH, include_in_schema=False)
async def prove_authoring(request: Request, run_id: str, role: str) -> Response:
    return _relay(request).proof(request, run_id, role)


@router.post(RELAY_CALL_PATH, include_in_schema=False)
async def dispatch_authoring(request: Request, call: _RelayCall) -> dict[str, Any]:
    try:
        return await _relay(request).dispatch(
            call, request.headers.get("authorization")
        )
    except ValueError as exc:
        raise HTTPException(
            409, "authoring call identity or state was refused"
        ) from exc
    except (AuthoringError, httpx.HTTPError) as exc:
        logger.warning("Authoring relay call failed (%s)", type(exc).__name__)
        raise HTTPException(
            502, "authoring delivery failed; retry the same logical call identity"
        ) from exc
