"""Closed, non-secret effective input retained by an accepted action."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    PrivateAttr,
    field_validator,
    model_validator,
)

from ..ipc.schemas import DispatchRequest
from ..thread.executable_graph import FrozenGraphDefinition
from .workspace import require_admitted_workspace_root

if TYPE_CHECKING:
    from ..database import ControlActionModel

__all__ = [
    "AcceptedActionInput",
    "ActorCredentialsRequiredError",
    "dispatch_matches_accepted_input",
    "freeze_accepted_input",
    "read_accepted_input",
    "restore_accepted_dispatch",
]

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

    # The definition the one validation below admits, so no reader parses the
    # persisted graph again. ``None`` for a cancel, which enters no graph.
    _graph_definition: FrozenGraphDefinition | None = PrivateAttr(default=None)

    @field_validator("dispatch")
    @classmethod
    def complete_effective_input(cls, value: dict[str, object]) -> dict[str, object]:
        if set(value) != set(_INPUT_FIELDS):
            raise ValueError("accepted dispatch does not carry complete current input")
        return value

    @model_validator(mode="after")
    def admit_graph_definition(self) -> Self:
        if self.dispatch["action"] != "cancel":
            definition = FrozenGraphDefinition.model_validate(
                self.dispatch["graph_definition"]
            )
            if definition.team_id != self.dispatch["team_preset"]:
                raise ValueError("accepted graph definition has a different preset")
            self._graph_definition = definition
        return self

    @property
    def graph_definition(self) -> FrozenGraphDefinition | None:
        """The validated executable program, absent for a cancel."""
        return self._graph_definition


def read_accepted_input(action: ControlActionModel) -> AcceptedActionInput:
    """Return the accepted input a journal action's stored payload holds.

    Raises:
        ValueError: When the action stores no payload, or the payload is not the
            current accepted-input shape.
    """
    if action.payload_json is None:
        raise ValueError("action stores no accepted input")
    return AcceptedActionInput.model_validate_json(action.payload_json)


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
    dispatch = DispatchRequest.model_validate(
        {
            **accepted.dispatch,
            "dispatch_id": dispatch_id,
            "graph_action_receipt": None,
            "actor_tokens": None,
        }
    )
    if dispatch.requires_graph_receipt and dispatch.workspace_root is not None:
        require_admitted_workspace_root(dispatch.workspace_root)
    return dispatch


def dispatch_matches_accepted_input(
    dispatch: DispatchRequest, accepted: AcceptedActionInput
) -> bool:
    return (
        dispatch.model_dump(mode="json", exclude=set(_TRANSPORT_FIELDS))
        == accepted.dispatch
        and (dispatch.actor_tokens is not None) == accepted.actor_tokens_required
    )
