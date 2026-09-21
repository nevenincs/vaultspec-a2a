"""Best-effort authoring-session close after a successful graph run."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from ..domain_config import domain_config

if TYPE_CHECKING:
    from ..streaming.types import StreamableGraph
    from .token_store import RunTokenStore

logger = logging.getLogger("vaultspec_a2a.worker.executor")

# The authoring role owns the engine session opened by this run.
_CLOSE_SESSION_ROLE = "vaultspec-synthesist"


async def close_authoring_session_best_effort(
    thread_id: str,
    graph: StreamableGraph,
    config: dict[str, Any],
    token_store: RunTokenStore,
) -> None:
    """Close the engine session after terminal success without failing the run."""
    from ..authoring import AuthoringClient, close_authoring_session, resolve_engine
    from ..authoring._ids import derive_idempotency_key

    try:
        snapshot = await asyncio.wait_for(
            graph.aget_state(config),
            timeout=domain_config.aget_state_timeout_seconds,
        )
        values: object = getattr(snapshot, "values", None)
        session_id: object = (
            cast("dict[str, object]", values).get("authoring_session_id")
            if isinstance(values, dict)
            else None
        )
        if not isinstance(session_id, str) or not session_id:
            return
        actor_token = token_store.actor_token(thread_id, _CLOSE_SESSION_ROLE)
        engine = resolve_engine()
        if not actor_token or engine is None:
            return
        # Origin and fallback bearer come from the same engine resolution.
        bearer = token_store.engine_bearer(thread_id) or engine.bearer_token
        async with AuthoringClient(
            engine.base_url,
            bearer,
            actor_token=actor_token,
            bearer_resolver=resolve_engine,
        ) as client:
            await close_authoring_session(
                client,
                session_id,
                idempotency_key=derive_idempotency_key(thread_id, "close_session"),
            )
    except Exception:
        # Housekeeping after terminal success must not propagate a failure.
        logger.warning(
            "best-effort close of the authoring session for run %s failed",
            thread_id,
            exc_info=True,
        )
