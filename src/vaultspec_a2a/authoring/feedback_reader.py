"""Read-path retrieval of an engine feedback batch for worker grounding.

The consuming half of the a2a feedback loop (edge ADR D5, feedback-loop ADR D4):
when a run carries an opaque ``feedback_batch_id`` in graph state (threaded from
run-start, S11), the worker retrieves the authoritative batch BY ID from the
engine and mounts its comments as grounding context for the writer's revision.
a2a never owns or parses the batch as state - it reads the content fresh each
mount pass and renders it into the transient mounted context, exactly as the
vault-document and task-queue mounts do.

Retrieval is best-effort: an unreachable engine, a missing credential, or an
unknown id degrades to no grounding block rather than failing the worker turn
(parity with the vault/queue mounts, which skip a missing document).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._errors import AuthoringError, AuthoringTransportError
from .client import AuthoringClient
from .discovery import resolve_engine

if TYPE_CHECKING:
    from ..worker.token_store import RunTokenStore

__all__ = ["FeedbackContextReader", "render_feedback_batch"]


def render_feedback_batch(data: Any) -> str | None:
    """Render an engine feedback-batch snapshot into a grounding text block.

    Pure and exported so the rendering is unit-tested directly. Reads only the
    stable served fields (``items[].anchor.heading_path`` / ``body`` and the
    optional whole-batch ``instruction``); an item without a body is skipped and
    an empty batch yields ``None`` (nothing to ground on). Never raises on a
    malformed shape - a non-conforming payload renders whatever it can and falls
    back to ``None`` when nothing usable remains.
    """
    if not isinstance(data, dict):
        return None
    # The engine read route nests the batch under a "batch" key (data.batch);
    # tolerate both that and a flat batch payload so the reader is robust to the
    # served envelope shape (the id field is likewise feedback_batch_id or
    # batch_id - not read here, only the items/instruction ground the writer).
    inner = data.get("batch")
    batch = inner if isinstance(inner, dict) else data
    items = batch.get("items")
    if not isinstance(items, list):
        return None

    lines: list[str] = []
    instruction = batch.get("instruction")
    if isinstance(instruction, str) and instruction.strip():
        lines.append(instruction.strip())

    for item in items:
        if not isinstance(item, dict):
            continue
        body = item.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        anchor = item.get("anchor")
        heading_path = anchor.get("heading_path") if isinstance(anchor, dict) else None
        if isinstance(heading_path, list) and heading_path:
            location = " > ".join(str(seg) for seg in heading_path)
            lines.append(f"- {location}: {body.strip()}")
        else:
            lines.append(f"- {body.strip()}")

    if not lines:
        return None
    return "\n".join(lines)


class FeedbackContextReader:
    """Retrieve and render a run's feedback batch as worker grounding context.

    Parameters mirror the document submitter's construction: the engine origin
    plus the run token store the bearer and the per-role actor token are read
    from. The batch read is capability-by-id (the unguessable content-addressed
    id is the capability), so any of the run's registered role tokens authorizes
    it; ``read_role`` names the role whose actor token is presented.
    """

    def __init__(
        self,
        *,
        engine_base_url: str,
        token_store: RunTokenStore,
        read_role: str,
    ) -> None:
        self._engine_base_url = engine_base_url
        self._token_store = token_store
        self._read_role = read_role

    async def read(self, thread_id: str, batch_id: str) -> str | None:
        """Retrieve *batch_id* and render its grounding block, or ``None``.

        Best-effort by contract: a missing credential or a transport/typed fault
        (engine down, unknown id -> 404) returns ``None`` so the worker turn
        proceeds ungrounded rather than crashing. Only a genuine batch with
        renderable comments yields a block.
        """
        bearer = self._token_store.engine_bearer(thread_id)
        actor_token = self._token_store.actor_token(thread_id, self._read_role)
        if not bearer or not actor_token:
            return None
        try:
            async with AuthoringClient(
                self._engine_base_url,
                bearer,
                actor_token=actor_token,
                bearer_resolver=resolve_engine,
            ) as client:
                response = await client.get_feedback_batch(batch_id)
        except (AuthoringError, AuthoringTransportError):
            return None
        return render_feedback_batch(response.data)
