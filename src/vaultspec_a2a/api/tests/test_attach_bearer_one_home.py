"""One attach rule, applied by both surfaces that gate on the attach credential.

Two surfaces prove the same credential and act on it differently. The
engine-facing dependency REFUSES an unproven request outright; the desktop
health endpoint answers everyone and merely WITHHOLDS the readiness projection
from an unproven caller. Different answers, one rule - and while the rule was
written out twice, nothing made the two agree except that they happened to.

The drift that matters is one-directional: a disclosure gate that accepted
anything the refusing gate rejects would hand an unauthenticated caller the
projection the refusing gate exists to protect. Neither site would look wrong on
its own, because the defect is only visible by comparing them.

So these tests do NOT compare the two gates to each other. Both now consume one
predicate, which means a single defect inside it would keep them perfectly
consistent while making both wrong, and a consistency check would pass. Each
gate is instead measured against the specification written down in
``_PRESENTATIONS`` below - an oracle independent of the code under test, derived
from the rule ("the header is exactly ``Bearer `` followed by the credential")
rather than from either implementation or from any observed output.

Everything drives real objects: the refusing gate over real HTTP through the
real app, and the disclosure gate through the real production function with a
real ASGI request scope.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from starlette.requests import Request

from ..app import _http_attach_authorized
from .conftest import make_app

_SERVICE_TOKEN = "attach-credential-under-test"

# The specification, stated rather than measured. A presentation authorizes
# exactly when it is the literal "Bearer " followed by the configured
# credential; every other presentation - including ones that CONTAIN the
# credential - does not. Asserting the admitted case matters as much as the
# refused ones: refusals alone are also what a gate that rejects everything
# would produce.
_PRESENTATIONS: tuple[tuple[str, str | None, bool], ...] = (
    ("the exact credential", f"Bearer {_SERVICE_TOKEN}", True),
    ("no header at all", None, False),
    ("an empty header", "", False),
    ("a wrong credential", "Bearer not-the-credential", False),
    ("the credential with no scheme", _SERVICE_TOKEN, False),
    ("a lowercased scheme", f"bearer {_SERVICE_TOKEN}", False),
    ("the credential as a prefix", f"Bearer {_SERVICE_TOKEN}-extra", False),
    ("a doubled separating space", f"Bearer  {_SERVICE_TOKEN}", False),
    ("the scheme alone", "Bearer", False),
)


def _armed_app(session_factory: Any, checkpointer: Any) -> Any:
    """Build the real gateway app with its production attach boundary armed."""
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = _SERVICE_TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    return app


def _request_carrying(authorization: str | None) -> Request:
    """Build a real ASGI request scope presenting *authorization*, or none."""
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "query_string": b"",
            "headers": headers,
        }
    )


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(("label", "authorization", "authorized"), _PRESENTATIONS)
async def test_the_refusing_gate_applies_the_specified_rule(
    session_factory: Any,
    checkpointer: Any,
    label: str,
    authorization: str | None,
    authorized: bool,
) -> None:
    """The engine-facing boundary admits exactly the specified presentation."""
    app = _armed_app(session_factory, checkpointer)
    headers = {"Authorization": authorization} if authorization is not None else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        headers=headers,
    ) as client:
        response = await client.get("/v1/runs")

    expected = 200 if authorized else 401
    assert response.status_code == expected, f"{label}: {response.text}"


@pytest.mark.parametrize(("label", "authorization", "authorized"), _PRESENTATIONS)
def test_the_disclosure_gate_applies_the_same_specified_rule(
    session_factory: Any,
    checkpointer: Any,
    label: str,
    authorization: str | None,
    authorized: bool,
) -> None:
    """The readiness-disclosure gate discloses on exactly the same presentation.

    Measured against the same specification the refusing gate is measured
    against, so a presentation one admits and the other does not is a failure
    here rather than an asymmetry nobody is looking at.
    """
    app = _armed_app(session_factory, checkpointer)

    disclosed = _http_attach_authorized(_request_carrying(authorization), app)

    assert disclosed is authorized, label


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("configured", [None, ""])
async def test_an_unconfigured_credential_reaches_each_surfaces_own_failure(
    session_factory: Any,
    checkpointer: Any,
    configured: str | None,
) -> None:
    """A gateway with no credential fails closed, in each surface's own idiom.

    This is the one place the two surfaces legitimately differ, and the reason
    the shared rule returns a verdict instead of raising: corrupted runtime state
    is a 503 on a boundary whose job is to refuse, and simply nothing disclosed
    on a boundary whose job is to answer with less. Both are the same verdict
    mapped onto different transports, so both are asserted here - taking one on
    faith would leave a gate that fails OPEN on missing state indistinguishable
    from one that fails closed.
    """
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.v1_service_token = configured
    app.state.allow_unauthenticated_v1_for_testing = False

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        refused = await client.get("/v1/runs")

    assert refused.status_code == 503
    assert refused.json() == {"detail": "Gateway service token is not configured"}

    # The same corrupted state, on the surface that answers rather than refuses:
    # a caller presenting nothing, and a caller presenting what WOULD have been
    # the credential, are both told nothing.
    assert _http_attach_authorized(_request_carrying(None), app) is False
    assert (
        _http_attach_authorized(_request_carrying(f"Bearer {_SERVICE_TOKEN}"), app)
        is False
    )
