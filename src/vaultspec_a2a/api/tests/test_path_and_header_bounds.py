"""Every bounded value on the versioned surface is refused AT the edge.

A run id has been bounded and confined to its grammar since the verbs were
published. The interrupt handles beside it were not: the respond routes took a
``request_id`` of any length and any shape, and the shared ``Idempotency-Key``
header was unbounded on every verb but one. Two costs followed. An ill-formed
clarification handle reached the domain model, whose own grammar then raised
inside the service and was served as a 500 - a caller's malformed input
reported as the gateway's fault. And an unbounded path segment or header is
work an authenticated caller can demand without limit before anything refuses
it.

Driven over a real socket against a real uvicorn gateway, because the refusal
under test belongs to the request parser rather than to any handler: a
TestClient would exercise the same code, but a 422 that the server never
reaches the handler for is only observable as an HTTP response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ...streaming import RelayHub
from ...testing import serve_on_loopback
from ...thread.constants import MAX_APPROVAL_REQUEST_ID_CHARS, MAX_REQUEST_ID_CHARS
from ...thread.enums import ThreadStatus
from ...thread.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH
from .conftest import make_app, seed_run_with_status

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from .conftest import SessionFactory

_RUN = "bounded-edge-run"

#: The two respond verbs, each with a body its own schema accepts, so a refusal
#: below is always the path or header parameter and never the body.
_RESPOND_VERBS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("clarifications", {"prompt": "continue"}),
    ("permissions", {"option_id": "approve"}),
)


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(("verb", "body"), _RESPOND_VERBS)
async def test_an_over_long_request_id_is_refused_at_the_edge(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    verb: str,
    body: dict[str, Any],
) -> None:
    """A handle wider than the edge publishes is refused before any lookup.

    The width is each verb's own: a clarification handle is one this service
    MINTS, so its bound is the minting cap, while a permission handle covers
    the approval ids the run history already publishes at the wider width. A
    verb bounded below what its own read surface serves would refuse a handle
    a caller was given.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)
    published = (
        MAX_REQUEST_ID_CHARS
        if verb == "clarifications"
        else MAX_APPROVAL_REQUEST_ID_CHARS
    )

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        refused = await client.post(
            f"/v1/runs/{_RUN}/{verb}/{'h' * (published + 1)}/respond", json=body
        )
        admitted = await client.post(
            f"/v1/runs/{_RUN}/{verb}/{'h' * published}/respond", json=body
        )

    assert refused.status_code == 422, refused.text
    # The widest handle the edge publishes still reaches the service, which
    # answers for the request it cannot find. A bound that refused this too
    # would be narrower than the contract says.
    assert admitted.status_code != 422, admitted.text


@pytest.mark.asyncio(loop_scope="function")
async def test_an_ill_formed_clarification_handle_is_refused_not_mishandled(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """``a!b`` is not a handle this service can mint, and says so as a 422.

    The grammar was already enforced, one layer too late: the clarification
    resolution model refused the value and its validation error left the
    service as a 500, reporting a caller's malformed path as a server fault.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        refused = await client.post(
            f"/v1/runs/{_RUN}/clarifications/a!b/respond", json={"prompt": "continue"}
        )

    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("path", ["cancel", "permissions/perm-abc/respond"])
async def test_an_over_long_idempotency_key_is_refused_at_the_edge(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver, path: str
) -> None:
    """One published width for the key, on every verb that takes one.

    The follow-up verb bounded it and the other two did not, so the same
    header meant a bounded value on one route and an unbounded one on the
    next. The refusal has to land before the run is looked up, or an
    unbounded header is work a caller can demand of the database.
    """
    app, _hub, _worker, _cp = make_app(session_factory, checkpointer, RelayHub())
    await seed_run_with_status(session_factory, _RUN, ThreadStatus.RUNNING)
    body: dict[str, Any] = {} if path == "cancel" else {"option_id": "approve"}

    async with (
        serve_on_loopback(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        refused = await client.post(
            f"/v1/runs/{_RUN}/{path}",
            json=body,
            headers={"Idempotency-Key": "k" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1)},
        )

    assert refused.status_code == 422, refused.text
