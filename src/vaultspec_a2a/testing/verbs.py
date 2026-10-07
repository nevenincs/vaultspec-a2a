"""The versioned run-start verb, shaped once for every tier that drives it.

``POST /v1/runs`` carries four stages: ``prepare`` reserves a bounded admission
slot, ``commit`` binds actor tokens under that reservation and creates the
durable run, ``release`` frees an uncommitted reservation, and ``start`` creates
and dispatches in one call. Every real-process tier drives some of them, and
each used to shape the request body itself. The copies drifted in exactly the
fields the broker binds on: the release binding is the digest of the PREPARED
request, so a release that differs from its prepare in one field is a different
request and is refused, and a replayed commit is recognised as a replay only
while it is byte-identical.

:class:`RunVerbs` is the one place a body is shaped. What varies between tiers -
the preset, the workspace, how a served selection is resolved, which actor
tokens a run binds - is a field of the handle, so a scenario states its policy
once and every stage presents it identically. Responses are returned whole; a
scenario asserts on them rather than on a re-derived request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

from .boot import FIRST_DEMAND_TIMEOUT, GatewayBootError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = ["RunVerbs", "actor_tokens_body", "status_and_json"]

type RunStage = Literal["start", "prepare", "commit", "release"]

# The run the first-demand warm-up reserves and immediately releases.
_WARM_UP_RUN_ID = "run-first-demand-warmup"


def status_and_json(response: httpx.Response) -> tuple[int, dict[str, Any]]:
    """Return *response*'s status and JSON body, or its text as ``detail``."""
    try:
        body = response.json()
    except json.JSONDecodeError:
        return response.status_code, {"detail": response.text}
    return response.status_code, body


def actor_tokens_body(
    tokens: Mapping[str, str], *, engine_bearer: str = "bearer"
) -> dict[str, object]:
    """The wire ``actor_tokens`` bundle: per-role *tokens* plus the engine bearer."""
    return {"tokens": dict(tokens), "engine_bearer": engine_bearer}


@dataclass(frozen=True, slots=True)
class RunVerbs:
    """Drive one gateway's run-start verb under one fixed policy.

    *authorization* is the whole ``Authorization`` header value. *selection*
    resolves the served catalog selection for a workspace: run start revalidates
    it against the catalog served for the run's workspace, so it is resolved per
    workspace rather than written by hand, and a caller caches it so prepare and
    its release or commit present the same one. *tokens* is the actor-token
    bundle a ``start`` or ``commit`` binds unless the call names its own, beside
    *engine_bearer*; ``None`` sends none.
    """

    base_url: str
    authorization: str
    team_preset: str
    workspace_root: str
    selection: Callable[[str], Mapping[str, object]]
    tokens: Mapping[str, str] | None = None
    message: str = "build it"
    engine_bearer: str = "bearer"

    def prepare(
        self, run_id: str, *, metadata: Mapping[str, object] | None = None
    ) -> httpx.Response:
        """Reserve a bounded admission slot for *run_id* (readiness-gated).

        Blocks inside the gateway until a cold worker start reaches readiness,
        so parallel calls model concurrent first demand.
        """
        return self._post("prepare", run_id, metadata=metadata)

    def commit(
        self,
        run_id: str,
        reservation_id: str,
        *,
        tokens: Mapping[str, str] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        """Bind actor tokens under *reservation_id*, creating the durable run."""
        return self._post(
            "commit",
            run_id,
            metadata=metadata,
            reservation_id=reservation_id,
            message=self.message,
            tokens=self.tokens if tokens is None else tokens,
        )

    def release(
        self,
        run_id: str,
        reservation_id: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        """Explicitly free an uncommitted prepared reservation.

        The body mirrors the prepare that opened the reservation field for
        field, including *metadata*: a release that omits a field is not a
        weaker request but a DIFFERENT one, which the broker refuses to match.
        """
        return self._post(
            "release", run_id, metadata=metadata, reservation_id=reservation_id
        )

    def start(
        self,
        run_id: str,
        *,
        message: str | None = None,
        tokens: Mapping[str, str] | None = None,
        metadata: Mapping[str, object] | None = None,
        title: str | None = None,
        autonomous: bool | None = True,
    ) -> httpx.Response:
        """Drive the one-shot ``start`` stage: create and dispatch in one call."""
        return self._post(
            "start",
            run_id,
            metadata=metadata,
            message=self.message if message is None else message,
            tokens=self.tokens if tokens is None else tokens,
            title=title,
            autonomous=autonomous,
        )

    def warm_first_demand(self) -> None:
        """Pay the gateway-owned worker's cold start at ARM time, then free it.

        First demand is the prepare that finds no worker: it triggers the spawn
        and waits for a new interpreter to import the worker stack and answer.
        That cost belongs to nobody's reservation. Left inside a scenario's first
        prepare, it runs INSIDE the admission window the scenario then reasons
        about, and a stack booting on a loaded host fails a readiness-gated
        prepare for a reason that has nothing to do with the contract under
        proof. The reservation is released immediately, so each scenario still
        meets the stack's full bounded capacity.
        """
        prepared = self.prepare(_WARM_UP_RUN_ID)
        if prepared.status_code != 201:
            raise GatewayBootError(
                f"the gateway refused its warm-up prepare: "
                f"{prepared.status_code} {prepared.text}"
            )
        released = self.release(_WARM_UP_RUN_ID, prepared.json()["reservation_id"])
        if released.status_code != 201 or released.json().get("released") is not True:
            raise GatewayBootError(
                f"the gateway could not release its warm-up reservation: "
                f"{released.status_code} {released.text}"
            )

    def _post(
        self,
        stage: RunStage,
        run_id: str,
        *,
        metadata: Mapping[str, object] | None,
        reservation_id: str | None = None,
        message: str | None = None,
        tokens: Mapping[str, str] | None = None,
        title: str | None = None,
        autonomous: bool | None = True,
    ) -> httpx.Response:
        # The workspace anchors the selection, so it rides even when the caller
        # declared no metadata of its own, and a caller's own workspace wins.
        run_metadata: dict[str, object] = {
            "workspace_root": self.workspace_root,
            **(metadata or {}),
        }
        body: dict[str, object] = {
            "team_preset": self.team_preset,
            "stage": stage,
            "run_id": run_id,
            "metadata": run_metadata,
            "selection": dict(self.selection(str(run_metadata["workspace_root"]))),
        }
        if autonomous is not None:
            body["autonomous"] = autonomous
        if reservation_id is not None:
            body["reservation_id"] = reservation_id
        if message is not None:
            body["message"] = message
        if tokens is not None:
            body["actor_tokens"] = actor_tokens_body(
                tokens, engine_bearer=self.engine_bearer
            )
        if title is not None:
            body["title"] = title
        with httpx.Client(
            base_url=self.base_url,
            timeout=FIRST_DEMAND_TIMEOUT,
            headers={"Authorization": self.authorization},
        ) as client:
            return client.post("/v1/runs", json=body)
