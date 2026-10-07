"""The published contract describes what the application actually serves.

Four statements in it were false. The progress stream was published as a JSON
response with an empty schema, so a generated client would have been given a
model-free ``application/json`` endpoint for a ``text/event-stream`` it cannot
read, and the frame catalogue the stream really serves appeared nowhere. The
one probe surface external callers have was published as an untyped object.
The worker-to-gateway plane was published as though it were part of the client
surface. And the permission verb's 403 - the one a document-approval pause is
refused with - was undeclared, so a client generated from the contract had no
branch for the refusal it will actually meet.

Each assertion below reads the LIVE document from the production factory, so
it fails on the application rather than on the committed artifact; the
artifact's own tests then hold the file to this same document.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from ...graph.enums import StreamFrameKind
from ...streaming.sse_frames import MAX_PROGRESS_CONTENT_CHARS, PROGRESS_CATALOG
from ..app import create_app
from ..routes import route_signature

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

_STREAM = "/v1/runs/{run_id}/stream"
_PERMISSION_RESPOND = "/v1/runs/{run_id}/permissions/{request_id}/respond"
_SSE_MEDIA_TYPE = "text/event-stream"


@asynccontextmanager
async def _no_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    yield


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """The production application, built by its own factory."""
    return create_app(lifespan=_no_lifespan)


@pytest.fixture(scope="module")
def document(app: FastAPI) -> dict[str, Any]:
    """The live OpenAPI document this application serves."""
    return app.openapi()


def _ok_content(document: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Return the 200 response's content map for one published operation."""
    responses = document["paths"][path][method]["responses"]
    return responses["200"].get("content", {})


def _frame_branches(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the published per-kind branches of the progress-frame schema."""
    schema = _ok_content(document, _STREAM, "get")[_SSE_MEDIA_TYPE]["schema"]
    return schema["anyOf"]


def _branch(document: dict[str, Any], kind: str) -> dict[str, Any]:
    """Return the published schema of one frame kind."""
    return next(
        branch
        for branch in _frame_branches(document)
        if branch["properties"].get("type", {}).get("const") == kind
    )


def _value(field: dict[str, Any]) -> dict[str, Any]:
    """Return a nullable field's value schema, past the null branch."""
    if "anyOf" not in field:
        return field
    return next(option for option in field["anyOf"] if option.get("type") != "null")


def test_the_stream_is_published_as_an_event_stream(
    document: dict[str, Any],
) -> None:
    """The one route that serves SSE says so, and says nothing else.

    A JSON content type on this route is not a cosmetic error: a generated
    client reads the media type to decide how to consume the body, and an
    ``application/json`` declaration tells it to parse one object and stop.
    """
    content = _ok_content(document, _STREAM, "get")
    assert set(content) == {_SSE_MEDIA_TYPE}, content


def test_the_published_frame_schema_names_every_catalogued_kind(
    document: dict[str, Any],
) -> None:
    """The frame schema is the catalogue, not a parallel description of it.

    One source for the served frame shape: the catalogue the encoder already
    projects every outgoing frame onto. A hand-written schema beside it would
    be a second declaration of the same contract, free to drift the moment a
    frame type is added, and the drift would be invisible because both sides
    would still parse.
    """
    published = {
        branch["properties"]["type"]["const"]
        for branch in _frame_branches(document)
        if "const" in branch["properties"].get("type", {})
    }
    assert published == set(PROGRESS_CATALOG)


def test_the_published_frame_schema_carries_the_catalogues_own_bounds(
    document: dict[str, Any],
) -> None:
    """A published field states the cap the encoder truncates it at.

    Read from a frame whose bound is load-bearing for a consumer sizing a
    buffer: the permitted token stream. A schema that omitted the cap would
    describe an unbounded text field the service never serves.
    """
    chunks = _branch(document, "message_chunk")
    content = _value(chunks["properties"]["content"])
    assert content["maxLength"] == MAX_PROGRESS_CONTENT_CHARS


def test_the_published_frame_schema_admits_an_uncatalogued_kind(
    document: dict[str, Any],
) -> None:
    """The closed catalogue degrades an unknown kind; the schema says so.

    Projection is by omission rather than refusal, so a producer ahead of this
    catalogue still reaches a consumer - carrying its identity keys alone. A
    schema listing only the catalogued kinds would describe that frame as
    invalid, which would make an additive producer change read as a contract
    violation.
    """
    branches = _frame_branches(document)
    identity_only = [
        branch for branch in branches if "const" not in branch["properties"]["type"]
    ]
    assert len(identity_only) == 1, branches
    assert "thread_id" in identity_only[0]["properties"]


def test_the_terminal_frame_is_published_with_its_replay_flag(
    document: dict[str, Any],
) -> None:
    """The frame that ends a stream publishes the field that says it is a replay.

    A consumer distinguishing "the run just ended" from "the run had already
    ended when I attached" reads this flag, and the catalogue is the only
    place it is declared.
    """
    terminal = _branch(document, StreamFrameKind.THREAD_TERMINAL)
    assert _value(terminal["properties"]["replay"])["type"] == "boolean"


def test_health_is_published_with_a_named_shape(document: dict[str, Any]) -> None:
    """The one unauthenticated probe surface is not published as "an object".

    An external prober generating against this contract learned nothing from
    it: no field name, no status vocabulary, no way to tell the armed
    profile's minimal liveness body from the unarmed profile's aggregate.
    """
    content = _ok_content(document, "/health", "get")
    schema = content["application/json"]["schema"]
    branches = schema.get("anyOf", [schema])
    referenced = [branch["$ref"] for branch in branches if "$ref" in branch]
    assert referenced, f"/health publishes no named schema: {schema}"
    for ref in referenced:
        assert (
            ref.removeprefix("#/components/schemas/")
            in document["components"]["schemas"]
        ), ref


def test_the_internal_worker_plane_is_not_published(
    document: dict[str, Any],
) -> None:
    """The worker's callback surface is not part of the client contract.

    It verifies a different credential, is reachable only from this service's
    own worker, and publishing it told a client generator to emit methods for
    a plane no client may call.
    """
    internal = sorted(
        path for path in document["paths"] if path.startswith("/internal")
    )
    assert not internal, internal


def test_the_served_route_signature_carries_no_internal_route(app: FastAPI) -> None:
    """The signature a doctor compares describes the client surface.

    The same list is served by ``service-state`` and recomputed by the doctor
    CLI from a locally built app, so an internal-plane entry in it is a fact
    about this service's private wiring published on an authenticated client
    surface.
    """
    signature = route_signature(app)
    assert signature, "the application published no routes at all"
    internal = [entry for entry in signature if " /internal" in entry]
    assert not internal, internal


def test_the_permission_verb_declares_the_refusal_it_serves(
    document: dict[str, Any],
) -> None:
    """A document-approval pause is refused 403, and the contract says so.

    The run parks on the engine's review surface, which decides it; answering
    through this route would resume a run whose verdict nobody recorded. The
    refusal is real and reachable, so a client generated from this contract
    needs a branch for it.
    """
    responses = document["paths"][_PERMISSION_RESPOND]["post"]["responses"]
    assert "403" in responses, sorted(responses)
    assert responses["403"]["description"]
