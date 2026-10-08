"""The published contract states this side's own bounds, and never skips saying so.

Each repository checks ITS OWN side of the frozen edge against the published
contract, never against the other repository's source. This is a2a's half: the
constants it declares in code must be the constants its served contract tells
a consumer about, asserted in process over the live document. The dashboard
owns the engine-side check and already arbitrates against the served contract.

The test this replaces read the sibling repository's Rust source from fixed
workstation paths and skipped when they were absent, which is every CI runner:
a gate that runs on one workstation is not a gate, and every drift it was
meant to catch passed unanimously because each side compared a copy of one
number against another copy of the same number. Nothing here reads another
repository or the filesystem, so there is no condition under which it declines
to run.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from ...graph.enums import ProviderCondition
from ...thread.actor_tokens import MAX_ROLES_PER_RUN
from ...thread.clarification import MAX_ANSWER_CHARS
from ...thread.constants import (
    MAX_APPROVAL_REQUEST_ID_CHARS,
    MAX_REQUEST_ID_CHARS,
    MAX_RUN_ID_CHARS,
    MAX_RUN_MESSAGE_CHARS,
    REQUEST_ID_PATTERN,
    RUN_ID_PATTERN,
)
from ...thread.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH
from ..app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

_CLARIFICATION_RESPOND = "/v1/runs/{run_id}/clarifications/{request_id}/respond"
_PERMISSION_RESPOND = "/v1/runs/{run_id}/permissions/{request_id}/respond"

#: Every verb that takes the shared idempotency header.
_IDEMPOTENT_VERBS = 3


@asynccontextmanager
async def _no_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    yield


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The live OpenAPI document, built from the production app factory."""
    return create_app(lifespan=_no_lifespan).openapi()


def _branch(parameter: dict[str, Any]) -> dict[str, Any]:
    """Return the string branch of a parameter's published schema.

    An optional parameter is published as ``anyOf`` over its type and null, so
    its bounds sit on the branch rather than on the parameter.
    """
    schema: dict[str, Any] = parameter.get("schema", {})
    if "anyOf" not in schema:
        return schema
    for option in schema["anyOf"]:
        if option.get("type") == "string":
            return option
    return schema


def _parameters(
    document: dict[str, Any], *, where: str
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Index every ``in=where`` parameter by method, path and name."""
    return {
        (method.upper(), path, parameter["name"]): _branch(parameter)
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        for parameter in operation.get("parameters", [])
        if parameter["in"] == where
    }


def test_every_published_path_parameter_states_a_width(
    document: dict[str, Any],
) -> None:
    """No path segment on any route is published without a width.

    A sweep rather than a per-route list, so a verb added later cannot quietly
    introduce an unbounded segment. A path parameter is a value an
    authenticated caller chooses, and the only honest contract for one is the
    width at which it is refused.
    """
    unbounded = sorted(
        f"{method} {path} {name}"
        for (method, path, name), schema in _parameters(document, where="path").items()
        if "maxLength" not in schema
    )
    assert not unbounded, f"path parameters published without a width: {unbounded}"


def test_the_run_id_segment_publishes_its_grammar_and_width(
    document: dict[str, Any],
) -> None:
    """One grammar and one width for a run id, on every route that takes one."""
    segments = {
        key: schema
        for key, schema in _parameters(document, where="path").items()
        if key[2] == "run_id"
    }
    assert segments, "no route publishes a run_id path parameter"
    for key, schema in segments.items():
        assert schema["maxLength"] == MAX_RUN_ID_CHARS, key
        assert schema["minLength"] == 1, key
        assert schema["pattern"] == RUN_ID_PATTERN, key


def test_the_clarification_handle_publishes_the_grammar_it_is_minted_in(
    document: dict[str, Any],
) -> None:
    """The handle this service mints is published at its minting cap and shape.

    The clarification resolution model admits exactly this grammar and width,
    so publishing them is what lets the edge refuse what the domain would have
    refused - as a 422 rather than as a fault inside the service.
    """
    schema = _parameters(document, where="path")[
        ("POST", _CLARIFICATION_RESPOND, "request_id")
    ]
    assert schema["maxLength"] == MAX_REQUEST_ID_CHARS
    assert schema["minLength"] == 1
    assert schema["pattern"] == REQUEST_ID_PATTERN


def test_the_permission_handle_publishes_the_width_its_read_surface_serves(
    document: dict[str, Any],
) -> None:
    """The approval handle is admitted at the width run history reports it.

    Deliberately wider than the minting cap and deliberately without a
    grammar: a document approval is answered by an id the authoring engine
    minted, which this service only transports, and the run record already
    publishes it at this width. A narrower bound would refuse a handle a
    caller read from this service's own read surface.
    """
    schema = _parameters(document, where="path")[
        ("POST", _PERMISSION_RESPOND, "request_id")
    ]
    assert schema["maxLength"] == MAX_APPROVAL_REQUEST_ID_CHARS
    assert schema["minLength"] == 1
    assert "pattern" not in schema


def test_the_approval_handle_is_admitted_at_the_width_it_is_reported_at(
    document: dict[str, Any],
) -> None:
    """The respond verb and the read surface agree on one width.

    Not two assertions about one number: the read surface REPORTS the handle
    and the respond verb ADMITS it, so a caller round-trips the value. The
    narrower of the two would be the real bound, silently.
    """
    admitted = _parameters(document, where="path")[
        ("POST", _PERMISSION_RESPOND, "request_id")
    ]["maxLength"]
    reported = _branch(
        {
            "schema": document["components"]["schemas"]["RunSummaryRecord"][
                "properties"
            ]["approval_request_id"]
        }
    )["maxLength"]
    assert admitted == reported


def test_every_surface_reporting_the_approval_handle_publishes_one_width(
    document: dict[str, Any],
) -> None:
    """The listing and run-status report the handle at the same width.

    Three surfaces carry this id - the listing record, the run-status response
    and the run read model run-history serves - and a caller round-trips it from
    whichever one it read. Bounded on one and unbounded on the others, the
    published contract told a consumer the field was capped or uncapped
    depending on which read it happened to make, and only the capped surface
    stated the cap the respond verb actually admits.
    """
    schemas = document["components"]["schemas"]
    widths = {
        component: _branch(
            {"schema": schemas[component]["properties"]["approval_request_id"]}
        ).get("maxLength")
        for component in (
            "RunSummaryRecord",
            "RunStatusResponse",
            "ThreadStateSnapshot",
        )
    }
    assert set(widths.values()) == {MAX_APPROVAL_REQUEST_ID_CHARS}, widths


def test_every_verb_publishes_one_width_for_the_idempotency_key(
    document: dict[str, Any],
) -> None:
    """The shared header is one bound, not a per-verb accident.

    Three verbs take the key and only one bounded it, so the same header name
    meant a bounded value on one route and an unbounded one on the next - a
    contract a client cannot read, because the width depended on which verb
    it happened to be calling.
    """
    keys = {
        key: schema
        for key, schema in _parameters(document, where="header").items()
        if key[2] == "Idempotency-Key"
    }
    assert len(keys) == _IDEMPOTENT_VERBS, sorted(keys)
    for key, schema in keys.items():
        assert schema["maxLength"] == IDEMPOTENCY_KEY_MAX_LENGTH, key


def test_the_turn_budget_is_published_where_a_turn_is_composed(
    document: dict[str, Any],
) -> None:
    """One turn's character budget, readable by whatever composes a turn."""
    content = document["components"]["schemas"]["RunMessageRequest"]["properties"]
    assert content["content"]["maxLength"] == MAX_RUN_MESSAGE_CHARS


def test_the_clarification_answer_cap_is_published_for_the_engine_to_mirror(
    document: dict[str, Any],
) -> None:
    """The cap an answer is forwarded against is readable in the contract.

    This number drifted once with no symptom until a full round trip: the
    engine carried 4096 against this side's 2048, a human typed 4096
    characters, the composer accepted them, the engine forwarded them, and
    this side answered 422 with nothing to say which layer objected.
    """
    answers = document["components"]["schemas"]["RunClarificationRespondRequest"][
        "properties"
    ]["answers"]
    answer_schemas = [
        option["patternProperties"]
        for option in answers["anyOf"]
        if "patternProperties" in option
    ]
    assert answer_schemas, f"the answers map publishes no value schema: {answers}"
    for by_pattern in answer_schemas:
        for value_schema in by_pattern.values():
            assert value_schema["maxLength"] == MAX_ANSWER_CHARS


def test_the_role_ceiling_is_published_where_a_caller_mints_against_it(
    document: dict[str, Any],
) -> None:
    """The per-run role ceiling is in the contract, not only in a comment.

    The engine applies the same ceiling before minting actor credentials, and
    its own check reads the served contract. Prepare is where a caller learns
    which roles to mint, so it is where the ceiling has to be legible: a
    ceiling asserted only in prose on both sides is one neither side can
    verify.
    """
    prepared = document["components"]["schemas"]["RunPrepareResponse"]["properties"]
    assert prepared["required_roles"]["maxItems"] == MAX_ROLES_PER_RUN


def test_the_provider_condition_vocabulary_is_published_in_full(
    document: dict[str, Any],
) -> None:
    """Every condition this side can emit is named in the contract.

    The engine refuses a condition it does not recognise AT ITS WRITE
    BOUNDARY, so a member this side emits without the engine having been
    taught it loses the whole run's settlement rather than one field.
    Publishing the closed set in order is what lets the engine be taught from
    the contract instead of from this repository's source.
    """
    published = document["components"]["schemas"]["ProviderCondition"]["enum"]
    assert published == [member.value for member in ProviderCondition]
