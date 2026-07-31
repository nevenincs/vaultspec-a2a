"""Field-set parity guard for the mirrored snapshot declarations.

The snapshot surface is deliberately declared twice: ``thread/snapshots.py`` holds
Layer 1 dataclasses and ``api/schemas/snapshots.py`` holds the Pydantic wire
models they project onto.  A third declaration, ``ipc/schemas.py``, carries the
execution-task shape across the gateway-worker wire.  The split is intentional -
Layer 1 stays free of Pydantic - and these tests do not argue with it.

What they guard is the invariant the split silently depends on: the mirrored
declarations must carry the *same field names*.  The production seam is
``Snapshot.model_validate(asdict(data))``, and Pydantic's default ``extra``
policy is ``ignore``, so a field added to a domain dataclass and not to its wire
model is dropped on the floor with no error at any layer.  That is not
hypothetical - it is how ``provider`` and ``model`` reached clients as
unconditional ``null`` from the team-status route until the splat there was
replaced with explicit field names.

These tests fail when the declarations drift apart in either direction.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from ....graph.enums import AgentLifecycleState, Model, Provider
from ....ipc.schemas import ExecutionTaskProjectionPayload
from ....thread import snapshots as domain
from .. import snapshots as wire

if TYPE_CHECKING:
    from _typeshed import DataclassInstance
    from pydantic import BaseModel

# The mirrored declarations, domain type paired with the wire model it projects
# onto.  Every pair is asserted field-for-field below.
_MIRRORS: tuple[tuple[type[DataclassInstance], type[BaseModel]], ...] = (
    (domain.MessageData, wire.MessageSnapshot),
    (domain.ToolCallData, wire.ToolCallSnapshot),
    (domain.ArtifactData, wire.ArtifactSnapshot),
    (domain.PermissionOptionData, wire._PermissionOptionSnapshot),
    (domain.PermissionData, wire._PermissionSnapshot),
    (domain.AgentData, wire._AgentSnapshot),
    (domain.ExecutionTaskData, wire.ExecutionTaskSnapshot),
    (domain.ThreadStateData, wire.ThreadStateSnapshot),
)

# The docstring convention every mirrored domain dataclass declares.  The
# completeness test below reads it, so a newly mirrored type that is not added to
# ``_MIRRORS`` is caught rather than silently going unguarded.
_MIRROR_MARKER = "Layer 1 equivalent of"


def _domain_field_names(cls: type[DataclassInstance]) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def _wire_field_names(cls: type[BaseModel]) -> set[str]:
    return set(cls.model_fields)


@pytest.mark.parametrize(
    ("domain_cls", "wire_cls"),
    _MIRRORS,
    ids=[d.__name__ for d, _ in _MIRRORS],
)
def test_domain_and_wire_declare_the_same_fields(
    domain_cls: type[DataclassInstance], wire_cls: type[BaseModel]
) -> None:
    """A mirrored pair must not drift apart in either direction."""
    domain_only = _domain_field_names(domain_cls) - _wire_field_names(wire_cls)
    wire_only = _wire_field_names(wire_cls) - _domain_field_names(domain_cls)
    assert not domain_only, (
        f"{domain_cls.__name__} declares {sorted(domain_only)} which "
        f"{wire_cls.__name__} does not. The seam is "
        f"{wire_cls.__name__}.model_validate(asdict(...)), which ignores unknown "
        f"keys, so these fields are silently dropped before reaching any client."
    )
    assert not wire_only, (
        f"{wire_cls.__name__} declares {sorted(wire_only)} which "
        f"{domain_cls.__name__} does not, so nothing in the domain layer can ever "
        f"populate them and they reach clients as their declared default."
    )


def test_execution_task_shape_agrees_across_all_three_declarations() -> None:
    """The execution-task shape is declared three times and must agree.

    ``ipc`` carries it worker-to-gateway, ``thread`` is the domain form the
    gateway projects it into, and ``api`` is what reaches the client.  A field
    added to one leg alone is dropped at whichever seam it crosses next.
    """
    ipc_fields = _wire_field_names(ExecutionTaskProjectionPayload)
    domain_fields = _domain_field_names(domain.ExecutionTaskData)
    api_fields = _wire_field_names(wire.ExecutionTaskSnapshot)
    assert ipc_fields == domain_fields, (
        "ExecutionTaskProjectionPayload (ipc) and ExecutionTaskData (thread) "
        f"disagree: ipc-only={sorted(ipc_fields - domain_fields)}, "
        f"domain-only={sorted(domain_fields - ipc_fields)}"
    )
    assert domain_fields == api_fields, (
        "ExecutionTaskData (thread) and ExecutionTaskSnapshot (api) disagree: "
        f"domain-only={sorted(domain_fields - api_fields)}, "
        f"api-only={sorted(api_fields - domain_fields)}"
    )


def test_every_declared_mirror_is_registered() -> None:
    """Each domain dataclass declaring a mirror must be covered by ``_MIRRORS``.

    Without this, adding a tenth mirrored type and forgetting to register it
    would leave it unguarded while the suite still passed.
    """
    registered = {domain_cls for domain_cls, _ in _MIRRORS}
    declared = {
        obj
        for obj in vars(domain).values()
        if dataclasses.is_dataclass(obj)
        and isinstance(obj, type)
        and _MIRROR_MARKER in (obj.__doc__ or "")
    }
    unregistered = declared - registered
    assert not unregistered, (
        f"{sorted(c.__name__ for c in unregistered)} declare themselves mirrors "
        f"but are absent from _MIRRORS, so no test compares their fields."
    )


def _populated_thread_state() -> domain.ThreadStateData:
    """Build a ``ThreadStateData`` with every nested mirrored type populated."""
    return domain.ThreadStateData(
        thread_id="thread-parity",
        status="running",
        last_sequence=11,
        messages=[
            domain.MessageData(
                message_id="m-1",
                role="user",
                content="hello",
                timestamp=datetime.now(UTC),
                agent_id="supervisor",
            )
        ],
        tool_calls=[
            domain.ToolCallData(
                tool_call_id="tc-1",
                title="read file",
                kind="read",
                status="completed",
            )
        ],
        pending_permissions=[
            domain.PermissionData(
                request_id="req-1",
                description="run a command",
                options=[
                    domain.PermissionOptionData(
                        option_id="allow_once", name="Allow once", kind="allow_once"
                    )
                ],
                tool_call="tc-1",
                tool_kind="execute",
            )
        ],
        artifacts=[
            domain.ArtifactData(
                artifact_id="a-1", filename="out.txt", content="body", complete=True
            )
        ],
        agents=[
            domain.AgentData(
                agent_id="supervisor",
                node_name="supervisor",
                state=AgentLifecycleState.WORKING,
                provider=Provider.CLAUDE,
                model=Model.HIGH,
                role="lead",
                display_name="Supervisor",
                description="coordinates",
            )
        ],
        execution_tasks=[domain.ExecutionTaskData(task_id="task-1", name="node")],
    )


def test_production_seam_carries_every_domain_field_to_the_wire() -> None:
    """Drive the real route seam and assert nothing is dropped in transit.

    This exercises the production converter itself rather than re-deriving the
    conversion, so a field that the seam drops fails here even if the pairwise
    declaration checks above were somehow satisfied.
    """
    # Imported inside the test: ``routes.thread_state`` imports this schema
    # module, so a module-level import would close a cycle at collection time.
    from ...routes.thread_state import _to_pydantic

    data = _populated_thread_state()
    snapshot = _to_pydantic(data)
    emitted = snapshot.model_dump()
    missing = set(dataclasses.asdict(data)) - set(emitted)
    assert not missing, (
        f"{sorted(missing)} are declared on ThreadStateData but never reach the "
        f"wire model produced by the route seam."
    )

    # The nested values survive, not merely the keys.
    assert emitted["agents"][0]["provider"] == Provider.CLAUDE
    assert emitted["agents"][0]["model"] == Model.HIGH
    assert emitted["execution_tasks"][0]["task_id"] == "task-1"
    assert emitted["pending_permissions"][0]["options"][0]["option_id"] == "allow_once"
    assert emitted["messages"][0]["agent_id"] == "supervisor"


def test_execution_task_payload_crosses_the_ipc_seam_intact() -> None:
    """An IPC task payload projects onto the domain type without loss.

    The worker emits ``ExecutionTaskProjectionPayload`` as JSON; the gateway
    rebuilds the domain type from it.  Field-name agreement is what makes that
    reconstruction total, so assert it against real serialized bytes.
    """
    payload = ExecutionTaskProjectionPayload(
        task_id="task-9",
        name="supervisor",
        path=["__pregel_pull", "supervisor"],
        has_error=True,
        error_type="ValueError",
        interrupt_ids=["int-1"],
        interrupt_types=["permission_request"],
        has_nested_state=True,
        has_result=True,
    )
    emitted: dict[str, Any] = payload.model_dump(mode="json")
    rebuilt = domain.ExecutionTaskData(**emitted)
    assert dataclasses.asdict(rebuilt) == emitted
