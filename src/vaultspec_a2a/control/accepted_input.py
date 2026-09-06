"""Closed, non-secret effective input retained by an accepted action."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from ..ipc.schemas import DispatchRequest
from ..thread.executable_graph import FrozenGraphDefinition

_TRANSPORT_FIELDS = frozenset({"dispatch_id", "graph_action_receipt", "actor_tokens"})
_INPUT_FIELDS = frozenset(DispatchRequest.model_fields) - _TRANSPORT_FIELDS


class ActorCredentialsRequiredError(ValueError):
    """Accepted work requires newly provisioned transport credentials."""


class AcceptedActionInput(BaseModel):
    """Current accepted input; absent fields never inherit construction defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["accepted-action-input-v2"]
    intent: dict[str, object]
    dispatch: dict[str, object]
    actor_tokens_required: bool

    @field_validator("dispatch")
    @classmethod
    def complete_effective_input(cls, value: dict[str, object]) -> dict[str, object]:
        if set(value) != _INPUT_FIELDS:
            raise ValueError("accepted dispatch does not carry complete current input")
        if value["action"] != "cancel":
            definition = FrozenGraphDefinition.model_validate(value["graph_definition"])
            if definition.team["id"] != value["team_preset"]:
                raise ValueError("accepted graph definition has a different preset")
        return value


def freeze_accepted_input(
    dispatch: DispatchRequest,
    *,
    intent: dict[str, object],
) -> dict[str, object]:
    """Freeze already resolved input without transport credentials or identity."""
    return AcceptedActionInput(
        schema_version="accepted-action-input-v2",
        intent=intent,
        dispatch=dispatch.model_dump(mode="json", exclude=set(_TRANSPORT_FIELDS)),
        actor_tokens_required=dispatch.actor_tokens is not None,
    ).model_dump(mode="json")


def restore_accepted_dispatch(
    accepted: AcceptedActionInput,
    *,
    dispatch_id: str,
) -> DispatchRequest:
    """Recreate only the stored input under the journal's stable dispatch ID."""
    if accepted.actor_tokens_required:
        raise ActorCredentialsRequiredError(
            "accepted execution requires fresh actor credentials"
        )
    return DispatchRequest.model_validate(
        {
            **accepted.dispatch,
            "dispatch_id": dispatch_id,
            "graph_action_receipt": None,
            "actor_tokens": None,
        }
    )


def dispatch_matches_accepted_input(
    dispatch: DispatchRequest, accepted: AcceptedActionInput
) -> bool:
    return (
        dispatch.model_dump(mode="json", exclude=set(_TRANSPORT_FIELDS))
        == accepted.dispatch
        and (dispatch.actor_tokens is not None) == accepted.actor_tokens_required
    )
